# routes/inmate.py
import base64
import os
import secrets
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, session, current_app, jsonify, abort,
                   send_from_directory)
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import (
    DecimalField, HiddenField, SelectField, StringField, SubmitField, TextAreaField,
)
from wtforms.validators import (
    DataRequired, InputRequired, Length, NumberRange, Optional,
)
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from extensions import csrf, db
from models.cell import CellBlock
from services.rbac import require_permission, Permissions, has_permission
from services.inmate_service import InmateService
from services.inmate_matcher import InmateMatcher
from services.biometric_agent_client import BiometricAgentClient, BiometricAgentError
from models.inmate import AdmissionEpisode, Inmate
from models.audit import AuditEvent
from models.medical import (
    DisciplinaryLog, EscapeAttemptLog, MedicalRecord, WorkTransferLog,
)
from models.visit import VisitLog
from models.user import UserAccount
from services.biometric_matcher import compare_templates
from services.person_photo_service import PersonPhotoService
from services.medical_record_service import MedicalRecordService


inmate_bp = Blueprint('inmate', __name__, url_prefix='/inmate')
csrf.exempt(inmate_bp)

RELEASE_TYPES = (
    'Sentence completed',
    'Court order',
    'Parole',
    'Transfer',
    'Other',
)
TRANSFER_PRISONS = (
    'Kigo Prison',
    'Nalufenya Prison',
    'Mubuku Juvenile Prison',
)


class InmateReleaseForm(FlaskForm):
    inmate_id = HiddenField(validators=[DataRequired()])
    release_type = SelectField(
        'Release type',
        choices=[(release_type, release_type) for release_type in RELEASE_TYPES],
        validators=[DataRequired()],
    )
    release_notes = TextAreaField(
        'Release notes', validators=[Optional(), Length(max=2000)]
    )
    release_cash_amount = DecimalField(
        'Cash or savings returned (UGX)',
        places=2,
        default=Decimal('0.00'),
        validators=[InputRequired(), NumberRange(min=Decimal('0.00'))],
    )
    release_property_claims = TextAreaField(
        'Property returned or claims',
        validators=[Optional(), Length(max=4000)],
    )
    submit = SubmitField('Record release')


class InmateMedicalIsolationForm(FlaskForm):
    requires_isolation = HiddenField()
    cell_block = StringField(validators=[Optional(), Length(max=50)])
    cell_number = StringField(validators=[Optional(), Length(max=20)])
    medical_isolation_reason = TextAreaField(
        validators=[Optional(), Length(max=2000)]
    )
    submit = SubmitField('Update medical isolation')


def _agent():
    return BiometricAgentClient(
        base_url=current_app.config['BIOMETRIC_AGENT_URL'],
        timeout=25,
    )


def _mock_mode():
    return current_app.config.get('BIOMETRIC_MOCK_MODE', False)


@inmate_bp.route('/release', methods=['GET', 'POST'])
@login_required
@require_permission(Permissions.INMATE_RELEASE)
def release_form():
    form = InmateReleaseForm()
    if form.validate_on_submit():
        try:
            selected_inmate_id = int(form.inmate_id.data)
        except (TypeError, ValueError):
            selected_inmate_id = 0
        inmate = Inmate.query.filter_by(inmate_id=selected_inmate_id, status='Active').with_for_update().first()
        if not inmate:
            flash('Select an active inmate before recording a release.', 'danger')
            return render_template(
                'inmate/release.html',
                form=form,
                transfer_prisons=TRANSFER_PRISONS,
            )

        scan_proof = session.get('release_fingerprint_verified')
        if not _valid_release_scan_proof(scan_proof, inmate.inmate_id):
            flash('Scan and verify this inmate’s fingerprint before recording the release.', 'danger')
            return render_template(
                'inmate/release.html',
                form=form,
                selected_inmate_id=inmate.inmate_id,
                transfer_prisons=TRANSFER_PRISONS,
            )

        discharged_at = datetime.now(ZoneInfo('Africa/Kampala')).replace(tzinfo=None)
        release_date = discharged_at.date()
        release_type = form.release_type.data
        transfer_destination = ''
        if release_type == 'Transfer':
            selected_destination = (request.form.get('transfer_prison') or '').strip()
            manual_destination = (
                request.form.get('transfer_prison_other') or ''
            ).strip()
            if selected_destination == 'Other':
                transfer_destination = manual_destination
            elif selected_destination in TRANSFER_PRISONS:
                transfer_destination = selected_destination
            if (
                not transfer_destination
                or len(transfer_destination) > 100
                or (selected_destination != 'Other' and manual_destination)
            ):
                flash(
                    'Select a receiving prison or enter its name for this transfer.',
                    'danger',
                )
                return render_template(
                    'inmate/release.html',
                    form=form,
                    selected_inmate_id=inmate.inmate_id,
                    transfer_prisons=TRANSFER_PRISONS,
                )
        elif (
            request.form.get('transfer_prison')
            or request.form.get('transfer_prison_other')
        ):
            flash('Receiving prison is only required for a transfer.', 'danger')
            return render_template(
                'inmate/release.html',
                form=form,
                selected_inmate_id=inmate.inmate_id,
                transfer_prisons=TRANSFER_PRISONS,
            )

        open_work_transfer = WorkTransferLog.query.filter_by(
            inmate_id=inmate.inmate_id,
            checked_in_at=None,
        ).first()
        if open_work_transfer:
            flash(
                'This inmate is currently out for work. Record their fingerprint check-in before discharge.',
                'danger',
            )
            return render_template(
                'inmate/release.html',
                form=form,
                selected_inmate_id=inmate.inmate_id,
                transfer_prisons=TRANSFER_PRISONS,
            )

        episode = inmate.admission_episodes.filter_by(is_current=True).first()
        if not episode:
            episode = AdmissionEpisode(
                inmate_id=inmate.inmate_id,
                admission_date=inmate.current_admission_date or date.today(),
                admission_type='Imported',
                admission_reason='Existing active record without an open admission episode',
                receiving_officer_id=current_user.user_id,
                is_current=True,
            )
            db.session.add(episode)

        old_cell = inmate.cell_block

        episode.release_date = release_date
        episode.release_type = release_type
        episode.transfer_to = transfer_destination or None
        episode.release_notes = (form.release_notes.data or '').strip() or None
        episode.release_cash_amount = form.release_cash_amount.data
        episode.release_property_claims = (
            (form.release_property_claims.data or '').strip() or None
        )
        episode.released_at = discharged_at
        episode.release_fingerprint_score = Decimal(str(scan_proof['score']))
        episode.releasing_officer_id = current_user.user_id
        episode.is_current = False

        inmate.actual_release_date = release_date
        inmate.status = 'Transferred' if release_type == 'Transfer' else 'Released'
        inmate.cell_block = None
        inmate.cell_number = None

        AuditEvent.log_event(
            event_category='Inmate',
            event_type='Release',
            event_description=(
                f'Released inmate {inmate.inmate_number} ({inmate.full_name}); '
                f'type: {release_type}'
            ),
            entity_type='Inmate',
            entity_id=inmate.inmate_id,
            user_id=current_user.user_id,
            username=current_user.username,
            user_role=current_user.role_name,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
            old_values={'status': 'Active', 'cell_block': old_cell},
            new_values={
                'status': inmate.status,
                'release_date': release_date.isoformat(),
                'release_type': release_type,
                'transfer_to': episode.transfer_to,
                'release_cash_amount': str(episode.release_cash_amount),
                'release_property_claims': episode.release_property_claims,
                'released_at': discharged_at.isoformat(),
                'release_fingerprint_score': str(episode.release_fingerprint_score),
            },
        )
        db.session.commit()
        session.pop('release_fingerprint_verified', None)

        flash(
            f'{inmate.full_name} was recorded as {inmate.status.lower()}.',
            'success',
        )
        return redirect(url_for('inmate.release_print', episode_id=episode.episode_id))

    return render_template(
        'inmate/release.html',
        form=form,
        transfer_prisons=TRANSFER_PRISONS,
    )


def _valid_release_scan_proof(proof, inmate_id):
    if not proof or proof.get('inmate_id') != inmate_id:
        return False
    try:
        verified_at = datetime.fromisoformat(proof['verified_at'])
    except (KeyError, TypeError, ValueError):
        return False
    age = datetime.now(timezone.utc) - verified_at
    return timedelta(0) <= age <= timedelta(minutes=5)


@inmate_bp.route('/api/release-search')
@login_required
@require_permission(Permissions.INMATE_RELEASE)
def api_release_search():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'results': []})

    session.pop('release_fingerprint_verified', None)
    pattern = f'%{query}%'
    matches = Inmate.query.filter(
        Inmate.status == 'Active',
        ~Inmate.work_transfer_logs.any(
            WorkTransferLog.checked_in_at.is_(None)
        ),
        or_(
            Inmate.full_name.ilike(pattern),
            Inmate.inmate_number.ilike(pattern),
            Inmate.national_id_number.ilike(pattern),
            Inmate.court_case_number.ilike(pattern),
            Inmate.alias_names.ilike(pattern),
        ),
    ).order_by(Inmate.full_name.asc()).limit(20).all()

    return jsonify({
        'results': [{
            'inmate_id': inmate.inmate_id,
            'inmate_number': inmate.inmate_number,
            'full_name': inmate.full_name,
            'cell_block': inmate.cell_block,
            'biometric_enrolled': bool(inmate.biometric_enrolled and inmate.fingerprint_template),
        } for inmate in matches],
    })


@inmate_bp.route('/api/release-history/<int:inmate_id>')
@login_required
@require_permission(Permissions.INMATE_RELEASE)
def api_release_history(inmate_id):
    inmate = Inmate.query.filter_by(inmate_id=inmate_id, status='Active').first_or_404()
    episodes = inmate.admission_episodes.order_by(
        AdmissionEpisode.admission_date.desc()
    ).all()
    medical_records = MedicalRecord.query.filter_by(
        inmate_id=inmate.inmate_id
    ).order_by(MedicalRecord.record_date.desc()).all()
    disciplinary_logs = DisciplinaryLog.query.filter_by(
        inmate_id=inmate.inmate_id
    ).order_by(DisciplinaryLog.incident_date.desc()).all()
    escape_attempt_logs = EscapeAttemptLog.query.filter_by(
        inmate_id=inmate.inmate_id
    ).order_by(
        EscapeAttemptLog.incident_date.desc(),
        EscapeAttemptLog.incident_time.desc(),
        EscapeAttemptLog.event_id.desc(),
    ).all()
    work_transfer_logs = WorkTransferLog.query.filter_by(
        inmate_id=inmate.inmate_id
    ).order_by(
        WorkTransferLog.checked_out_at.desc(),
        WorkTransferLog.transfer_id.desc(),
    ).all()
    audit_history = AuditEvent.query.filter_by(
        entity_type='Inmate',
        entity_id=inmate.inmate_id,
    ).order_by(AuditEvent.event_timestamp.desc()).limit(100).all()

    return jsonify({
        'inmate': {
            'inmate_id': inmate.inmate_id,
            'inmate_number': inmate.inmate_number,
            'full_name': inmate.full_name,
            'date_of_birth': inmate.date_of_birth.isoformat() if inmate.date_of_birth else None,
            'gender': inmate.gender,
            'nationality': inmate.nationality,
            'tribe': inmate.tribe,
            'religion': inmate.religion,
            'national_id_number': inmate.national_id_number,
            'passport_number': inmate.passport_number,
            'alias_names': inmate.alias_names,
            'next_of_kin_name': inmate.next_of_kin_name,
            'next_of_kin_relationship': inmate.next_of_kin_relationship,
            'next_of_kin_phone': inmate.next_of_kin_phone,
            'next_of_kin_phone_2': inmate.next_of_kin_phone_2,
            'next_of_kin_address': inmate.next_of_kin_address,
            'height_cm': inmate.height_cm,
            'weight_kg': inmate.weight_kg,
            'education': inmate.education,
            'arrested_from': inmate.arrested_from,
            'overall_description': inmate.overall_description,
            'eye_color': inmate.eye_color,
            'hair_color': inmate.hair_color,
            'distinguishing_marks': inmate.distinguishing_marks,
            'crime_category': inmate.crime_category,
            'crime_description': inmate.crime_description,
            'court_case_number': inmate.court_case_number,
            'sentencing_court': inmate.sentencing_court,
            'sentence_type': inmate.sentence_type,
            'sentence_duration': inmate.sentence_duration,
            'sentence_start_date': inmate.sentence_start_date.isoformat() if inmate.sentence_start_date else None,
            'expected_release_date': inmate.expected_release_date.isoformat() if inmate.expected_release_date else None,
            'next_court_date': inmate.next_court_date.isoformat() if inmate.next_court_date else None,
            'cell_block': inmate.cell_block,
            'cell_number': inmate.cell_number,
            'security_classification': inmate.security_classification,
            'has_medical_condition': inmate.has_medical_condition,
            'medical_alert': inmate.medical_alert,
            'risk_level': inmate.risk_level,
            'violence_history': inmate.violence_history,
            'escape_attempt_history': inmate.escape_attempt_history,
            'work_status': (
                'Out for work' if any(log.is_out for log in work_transfer_logs)
                else 'Inside'
            ),
            'status': inmate.status,
            'total_admissions': inmate.total_admissions,
            'biometric_enrolled': bool(inmate.biometric_enrolled and inmate.fingerprint_template),
        },
        'admissions': [{
            'date': episode.admission_date.isoformat() if episode.admission_date else None,
            'type': episode.admission_type,
            'reason': episode.admission_reason,
            'release_date': episode.release_date.isoformat() if episode.release_date else None,
            'release_type': episode.release_type,
            'release_notes': episode.release_notes,
            'release_cash_amount': (
                str(episode.release_cash_amount)
                if episode.release_cash_amount is not None else None
            ),
            'release_property_claims': episode.release_property_claims,
            'transfer_to': episode.transfer_to,
            'released_at': episode.released_at.isoformat() if episode.released_at else None,
            'current': bool(episode.is_current),
        } for episode in episodes],
        'medical_records': [{
            'date': record.record_date.isoformat() if record.record_date else None,
            'type': record.record_type,
            'diagnosis': record.diagnosis,
            'treatment': record.treatment_prescribed,
            'notes': record.notes,
        } for record in medical_records],
        'disciplinary_history': [{
            'date': log.incident_date.isoformat() if log.incident_date else None,
            'time': log.incident_time.strftime('%H:%M') if log.incident_time else None,
            'type': log.incident_type,
            'description': log.description,
            'action': log.action_taken,
            'punishment': log.punishment_assigned,
            'injured_count': (
                log.injured_count if log.injured_count is not None
                else 'Not recorded'
            ),
            'is_violent': (
                'Yes' if log.is_violent is True
                else 'No' if log.is_violent is False
                else 'Not classified'
            ),
            'witnesses': log.witnesses,
        } for log in disciplinary_logs],
        'escape_history': [{
            'date': event.incident_date.isoformat() if event.incident_date else None,
            'time': event.incident_time.strftime('%H:%M') if event.incident_time else None,
            'description': event.description,
            'outcome': event.outcome,
            'action_taken': event.action_taken,
        } for event in escape_attempt_logs],
        'work_transfer_history': [{
            'location': log.work_location,
            'description': log.work_description,
            'checked_out_at': log.checked_out_at.isoformat(sep=' ', timespec='minutes'),
            'checked_in_at': (
                log.checked_in_at.isoformat(sep=' ', timespec='minutes')
                if log.checked_in_at else None
            ),
            'status': 'Out for work' if log.is_out else 'Inside',
            'time_out_minutes': log.time_out,
        } for log in work_transfer_logs],
        'audit_history': [{
            'date': event.event_timestamp.isoformat() if event.event_timestamp else None,
            'type': event.event_type,
            'description': event.event_description,
        } for event in audit_history],
    })


@inmate_bp.route('/api/release-fingerprint', methods=['POST'])
@login_required
@require_permission(Permissions.INMATE_RELEASE)
def api_release_fingerprint():
    if _mock_mode():
        return jsonify({
            'ok': False,
            'error': 'Fingerprint release confirmation requires real hardware. Disable biometric mock mode first.',
        }), 503

    data = request.get_json(silent=True) or {}
    try:
        inmate_id = int(data.get('inmate_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'Select an active inmate first.'}), 400

    inmate = Inmate.query.filter_by(inmate_id=inmate_id, status='Active').first()
    if not inmate:
        return jsonify({'ok': False, 'error': 'The selected inmate is not active.'}), 404
    if not inmate.biometric_enrolled or not inmate.fingerprint_template:
        return jsonify({
            'ok': False,
            'error': 'This inmate has no enrolled fingerprint. Release cannot be confirmed biometrically.',
        }), 400

    session.pop('release_fingerprint_verified', None)
    try:
        probe = _agent().scan()
    except BiometricAgentError as error:
        return jsonify({'ok': False, 'error': str(error)}), 503

    if not probe.get('success') or not probe.get('template'):
        return jsonify({
            'ok': False,
            'error': probe.get('error', 'Fingerprint scan did not return a template.'),
        }), 400

    try:
        quality = float(probe['quality'])
    except (KeyError, TypeError, ValueError):
        quality = None
    quality_threshold = current_app.config.get('BIOMETRIC_QUALITY_MIN', 60)
    if quality is None or not 0 <= quality <= 100:
        return jsonify({
            'ok': False,
            'error': 'The scanner did not report valid fingerprint quality; try again.',
        }), 400
    if quality < quality_threshold:
        return jsonify({
            'ok': False,
            'error': f'Fingerprint quality is too low ({quality}%). Try again.',
        }), 400

    score = compare_templates(probe['template'], inmate.fingerprint_template)
    threshold = current_app.config.get('BIOMETRIC_MATCH_THRESHOLD', 75)
    if score < threshold:
        session.pop('release_fingerprint_verified', None)
        return jsonify({
            'ok': False,
            'score': round(score, 2),
            'error': 'Scanned fingerprint does not match the selected inmate.',
        }), 403

    session['release_fingerprint_verified'] = {
        'inmate_id': inmate.inmate_id,
        'score': round(score, 2),
        'verified_at': datetime.now(timezone.utc).isoformat(),
    }
    return jsonify({
        'ok': True,
        'score': round(score, 2),
        'message': 'Fingerprint matched. Complete and record the discharge form.',
    })


@inmate_bp.route(
    '/api/<int:inmate_id>/work-transfer/<action>', methods=['POST']
)
@login_required
@require_permission(Permissions.INMATE_RELEASE)
def work_transfer_action(inmate_id, action):
    if action not in {'checkout', 'checkin'}:
        abort(404)
    if _mock_mode():
        return jsonify({
            'ok': False,
            'error': 'Work-transfer fingerprint confirmation requires real hardware. Disable biometric mock mode first.',
        }), 503

    inmate = Inmate.query.filter_by(
        inmate_id=inmate_id, status='Active'
    ).with_for_update().first_or_404()
    if not inmate.biometric_enrolled or not inmate.fingerprint_template:
        return jsonify({
            'ok': False,
            'error': 'This inmate has no enrolled fingerprint. Work transfer cannot be confirmed.',
        }), 400

    open_transfer = WorkTransferLog.query.filter_by(
        inmate_id=inmate.inmate_id,
        checked_in_at=None,
    ).first()
    payload = request.get_json(silent=True) or {}

    if action == 'checkout':
        if inmate.medical_isolation_required:
            return jsonify({
                'ok': False,
                'error': 'Medical isolation is required; a Medical Officer must clear it before a work checkout.',
            }), 409
        if open_transfer:
            return jsonify({
                'ok': False,
                'error': 'This inmate is already marked Out for work. Check them in before starting another trip.',
            }), 409
        work_location = (payload.get('work_location') or '').strip()
        work_description = (payload.get('work_description') or '').strip()
        if not work_location or len(work_location) > 200:
            return jsonify({
                'ok': False,
                'error': 'Enter a work destination of no more than 200 characters.',
            }), 400
        if len(work_description) > 2000:
            return jsonify({
                'ok': False,
                'error': 'Work details must be no more than 2,000 characters.',
            }), 400
    elif not open_transfer:
        return jsonify({
            'ok': False,
            'error': 'There is no open work trip to check in.',
        }), 409

    try:
        probe = _agent().scan()
    except BiometricAgentError as error:
        return jsonify({'ok': False, 'error': str(error)}), 503

    if not probe.get('success') or not probe.get('template'):
        return jsonify({
            'ok': False,
            'error': probe.get('error', 'Fingerprint scan did not return a template.'),
        }), 400
    try:
        quality = float(probe['quality'])
    except (KeyError, TypeError, ValueError):
        return jsonify({
            'ok': False,
            'error': 'The scanner did not report valid fingerprint quality; try again.',
        }), 400
    quality_threshold = current_app.config.get('BIOMETRIC_QUALITY_MIN', 60)
    if not 0 <= quality <= 100 or quality < quality_threshold:
        return jsonify({
            'ok': False,
            'error': f'Fingerprint quality is too low ({quality:g}%). Try again.',
        }), 400

    score = compare_templates(probe['template'], inmate.fingerprint_template)
    threshold = current_app.config.get('BIOMETRIC_MATCH_THRESHOLD', 75)
    if score < threshold:
        return jsonify({
            'ok': False,
            'score': round(score, 2),
            'error': 'Scanned fingerprint does not match the selected inmate.',
        }), 403

    action_at = datetime.now(ZoneInfo('Africa/Kampala')).replace(tzinfo=None)
    if action == 'checkout':
        transfer = WorkTransferLog(
            inmate_id=inmate.inmate_id,
            work_location=work_location,
            work_description=work_description or None,
            checked_out_at=action_at,
            checkout_fingerprint_score=Decimal(str(score)),
            checked_out_by=current_user.user_id,
        )
        db.session.add(transfer)
        event_description = (
            f'Checked inmate {inmate.inmate_number} out for work at {work_location}'
        )
        response_message = 'Fingerprint matched. Inmate is now Out for work.'
        new_values = {
            'status': 'Out for work',
            'work_location': work_location,
            'work_description': work_description or None,
            'checked_out_at': action_at.isoformat(),
            'checkout_fingerprint_score': round(score, 2),
        }
    else:
        open_transfer.checked_in_at = action_at
        open_transfer.checkin_fingerprint_score = Decimal(str(score))
        open_transfer.checked_in_by = current_user.user_id
        event_description = (
            f'Checked inmate {inmate.inmate_number} back in from work'
        )
        response_message = 'Fingerprint matched. Inmate is now Inside.'
        new_values = {
            'status': 'Inside',
            'work_location': open_transfer.work_location,
            'checked_in_at': action_at.isoformat(),
            'time_out_minutes': max(
                0, int((action_at - open_transfer.checked_out_at).total_seconds() // 60)
            ),
            'checkin_fingerprint_score': round(score, 2),
        }

    AuditEvent.log_event(
        event_category='Inmate',
        event_type=f'Work {action.title()}',
        event_description=event_description,
        entity_type='Inmate',
        entity_id=inmate.inmate_id,
        user_id=current_user.user_id,
        username=current_user.username,
        user_role=current_user.role_name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        new_values=new_values,
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'ok': False,
            'error': 'Another work-transfer action was just recorded. Refresh the inmate record and try again.',
        }), 409

    flash(response_message, 'success')
    return jsonify({
        'ok': True,
        'score': round(score, 2),
        'message': response_message,
        'status': 'Out for work' if action == 'checkout' else 'Inside',
    })


@inmate_bp.route('/release/<int:episode_id>/print')
@login_required
@require_permission(Permissions.INMATE_RELEASE)
def release_print(episode_id):
    episode = AdmissionEpisode.query.filter(
        AdmissionEpisode.episode_id == episode_id,
        AdmissionEpisode.release_date.isnot(None),
    ).first_or_404()
    inmate = episode.inmate
    officer = db.session.get(UserAccount, episode.releasing_officer_id)
    admission_episodes = inmate.admission_episodes.order_by(
        AdmissionEpisode.admission_date.asc(),
        AdmissionEpisode.episode_id.asc(),
    ).all()
    disciplinary_logs = DisciplinaryLog.query.filter_by(
        inmate_id=inmate.inmate_id
    ).order_by(
        DisciplinaryLog.incident_date.desc(),
        DisciplinaryLog.incident_time.desc(),
        DisciplinaryLog.log_id.desc(),
    ).all()
    escape_attempt_logs = EscapeAttemptLog.query.filter_by(
        inmate_id=inmate.inmate_id
    ).order_by(
        EscapeAttemptLog.incident_date.desc(),
        EscapeAttemptLog.incident_time.desc(),
        EscapeAttemptLog.event_id.desc(),
    ).all()
    work_transfer_logs = WorkTransferLog.query.filter_by(
        inmate_id=inmate.inmate_id
    ).order_by(
        WorkTransferLog.checked_out_at.asc(),
        WorkTransferLog.transfer_id.asc(),
    ).all()

    medical_records = []
    if has_permission(Permissions.MEDICAL_RECORD_VIEW):
        medical_records = MedicalRecord.query.filter(
            MedicalRecord.inmate_id == inmate.inmate_id,
            or_(
                MedicalRecord.approval_status == 'Approved',
                MedicalRecord.recorded_by == current_user.user_id,
                MedicalRecord.approval_status == 'Pending',
            ),
        ).order_by(
            MedicalRecord.record_date.asc(),
            MedicalRecord.record_id.asc(),
        ).all()
        if not has_permission(Permissions.MEDICAL_RECORD_APPROVE):
            medical_records = [
                record for record in medical_records
                if record.approval_status == 'Approved'
                or record.recorded_by == current_user.user_id
            ]

    visit_logs = []
    if has_permission(Permissions.VISIT_VIEW):
        visit_logs = inmate.visit_logs.order_by(
            VisitLog.check_in_time.asc(),
            VisitLog.visit_id.asc(),
        ).all()

    return render_template(
        'inmate/release_print.html',
        episode=episode,
        inmate=inmate,
        officer=officer,
        admission_episodes=admission_episodes,
        disciplinary_logs=disciplinary_logs,
        escape_attempt_logs=escape_attempt_logs,
        work_transfer_logs=work_transfer_logs,
        medical_records=medical_records,
        show_medical=has_permission(Permissions.MEDICAL_RECORD_VIEW),
        visit_logs=visit_logs,
        show_visits=has_permission(Permissions.VISIT_VIEW),
    )


# ---------- List ----------
@inmate_bp.route('/')
@login_required
@require_permission(Permissions.INMATE_VIEW)
def list_inmates():
    search = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip() or None
    page   = request.args.get('page', 1, type=int)

    pagination = InmateService.list_inmates(
        search=search, status=status, page=page, per_page=15
    )
    return render_template(
        'inmate/list.html',
        pagination=pagination, inmates=pagination.items,
        search=search, status=status,
    )


# ---------- Scan page ----------
@inmate_bp.route('/intake')
@login_required
@require_permission(Permissions.INMATE_CREATE)
def intake_scan():
    return render_template(
        'inmate/scan.html',
        agent_url=current_app.config['BIOMETRIC_AGENT_URL'],
        mock_mode=_mock_mode(),
    )


# ---------- API: scan + 1:N identify ----------
@inmate_bp.route('/api/scan-identify', methods=['POST'])
@login_required
@require_permission(Permissions.INMATE_CREATE)
def api_scan_identify():
    try:
        if _mock_mode():
            seed = (current_app.config.get('SECRET_KEY') or 'x') * 4
            template = base64.b64encode((seed.encode() * 4)[:256]).decode('utf-8')
            probe = {'success': True, 'template': template, 'quality': 90}
        else:
            probe = _agent().scan()
    except BiometricAgentError as e:
        return jsonify({'ok': False, 'error': str(e)}), 503

    if not probe.get('success'):
        return jsonify({'ok': False, 'error': probe.get('error', 'Scan failed')}), 400

    probe_template = probe['template']
    threshold = current_app.config.get('BIOMETRIC_MATCH_THRESHOLD', 75)

    result = InmateMatcher.identify(probe_template, threshold=threshold)

    if result['match']:
        m = result['inmate']
        return jsonify({
            'ok': True,
            'match': True,
            'score': round(result['score'], 1),
            'enrolled_count': result['enrolled_count'],
            'inmate': {
                'inmate_id': m.inmate_id,
                'inmate_number': m.inmate_number,
                'full_name': m.full_name,
                'crime_category': m.crime_category,
                'status': m.status,
                'total_admissions': m.total_admissions,
                'cell_block': m.cell_block,
            },
            'redirect': url_for('inmate.readmit', inmate_id=m.inmate_id),
        })

    return jsonify({
        'ok': True,
        'match': False,
        'score': round(result['score'], 1),
        'enrolled_count': result['enrolled_count'],
        'redirect': url_for('inmate.new_intake'),
    })


@inmate_bp.route('/api/enroll-fingerprint', methods=['POST'])
@login_required
@require_permission(Permissions.INMATE_CREATE)
def api_enroll_fingerprint():
    payload = request.get_json(silent=True) or {}
    enrollment_id = payload.get('enrollment_id')
    if not isinstance(enrollment_id, str) or not enrollment_id:
        return jsonify({'ok': False, 'error': 'Reload the form before scanning.'}), 400
    try:
        if _mock_mode():
            seed = (current_app.config.get('SECRET_KEY') or 'x') * 4
            probe = {
                'success': True,
                'template': base64.b64encode((seed.encode() * 4)[:256]).decode('utf-8'),
                'quality': 90,
            }
        else:
            probe = _agent().enroll(
                samples=current_app.config.get('BIOMETRIC_SAMPLES_PER_ENROLL', 3)
            )
    except BiometricAgentError as error:
        pending = session.get('pending_inmate_enrollment') or {}
        if pending.get('enrollment_id') == enrollment_id:
            session.pop('pending_inmate_enrollment', None)
        return jsonify({'ok': False, 'error': str(error)}), 503

    if not probe.get('success') or not probe.get('template'):
        pending = session.get('pending_inmate_enrollment') or {}
        if pending.get('enrollment_id') == enrollment_id:
            session.pop('pending_inmate_enrollment', None)
        return jsonify({
            'ok': False,
            'error': probe.get('error', 'Fingerprint enrollment failed.'),
        }), 400

    try:
        quality = float(probe['quality'])
    except (KeyError, TypeError, ValueError):
        pending = session.get('pending_inmate_enrollment') or {}
        if pending.get('enrollment_id') == enrollment_id:
            session.pop('pending_inmate_enrollment', None)
        return jsonify({
            'ok': False,
            'error': 'The scanner did not report fingerprint quality. Try again.',
        }), 400

    quality_threshold = current_app.config.get('BIOMETRIC_QUALITY_MIN', 60)
    if not 0 <= quality <= 100 or quality < quality_threshold:
        pending = session.get('pending_inmate_enrollment') or {}
        if pending.get('enrollment_id') == enrollment_id:
            session.pop('pending_inmate_enrollment', None)
        return jsonify({
            'ok': False,
            'error': f'Fingerprint quality is too low ({quality:g}%). Try again.',
        }), 400

    session['pending_inmate_enrollment'] = {
        'enrollment_id': enrollment_id,
        'template': probe['template'],
        'quality': quality,
    }
    return jsonify({
        'ok': True,
        'quality': round(quality),
        'samples_captured': probe.get('samples_captured', 1),
        'message': 'Fingerprint captured. Submit the form to save enrollment.',
    })


# ---------- New inmate form ----------
@inmate_bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_permission(Permissions.INMATE_CREATE)
def new_intake():
    if request.method == 'POST':
        data = request.form.to_dict()
        data['prior_medical_summary'] = request.form.get('prior_medical_summary', '')
        document_path, document_name, document_error = MedicalRecordService.save_document(
            request.files.get('prior_medical_document'),
            inmate_id=0,
        )
        if document_error:
            flash(document_error, 'danger')
            return render_template(
                'inmate/form.html', mode='new', data=data,
                has_probe=False,
                enrollment_id=data.get('enrollment_id') or secrets.token_urlsafe(24),
                cell_blocks=InmateService.cell_block_options(),
            )
        photo_data = data.pop('photo_data', '')
        data.pop('photo_path', None)
        enrollment_id = data.get('enrollment_id')
        data.pop('enrollment_id', None)
        enrollment = session.get('pending_inmate_enrollment') or {}
        if enrollment.get('enrollment_id') != enrollment_id:
            enrollment = {}
        template = enrollment.get('template')
        quality = enrollment.get('quality', 0)

        photo_path, photo_error = PersonPhotoService.save_capture(photo_data)
        if photo_error:
            MedicalRecordService.delete_document(document_path)
            flash(photo_error, 'danger')
            return render_template('inmate/form.html',
                                   mode='new', data=data,
                                   has_probe=bool(template),
                                   enrollment_id=enrollment_id,
                                   cell_blocks=InmateService.cell_block_options())
        if photo_path:
            data['photo_path'] = photo_path
        if document_path:
            data['prior_medical_document_path'] = document_path
            data['prior_medical_document_name'] = document_name
        data['photo_data'] = photo_data

        inmate, error = InmateService.create_inmate(
            actor=current_user, data=data,
            fingerprint_template=template,
            fingerprint_quality=quality,
        )
        if error:
            PersonPhotoService.delete_photo(photo_path)
            MedicalRecordService.delete_document(document_path)
            flash(error, 'danger')
            return render_template('inmate/form.html',
                                   mode='new', data=data,
                                   has_probe=bool(template),
                                   enrollment_id=enrollment_id,
                                   cell_blocks=InmateService.cell_block_options())

        if (session.get('pending_inmate_enrollment') or {}).get('enrollment_id') == enrollment_id:
            session.pop('pending_inmate_enrollment', None)
        flash(f'Inmate {inmate.inmate_number} registered successfully.', 'success')
        return redirect(url_for('inmate.detail', inmate_id=inmate.inmate_id))

    return render_template('inmate/form.html',
                           mode='new', data={}, has_probe=False,
                           enrollment_id=secrets.token_urlsafe(24),
                           cell_blocks=InmateService.cell_block_options())


@inmate_bp.route('/api/cell-assignment')
@login_required
@require_permission(Permissions.INMATE_CREATE)
def api_cell_assignment():
    security_classification = request.args.get('security_classification', '').strip()
    if security_classification not in InmateService.SECURITY_CLASSIFICATIONS:
        return jsonify({'error': 'Select a valid security classification.'}), 400

    medical_isolation_required = (
        request.args.get('medical_isolation_required', '').lower() == 'true'
    )
    suggestion = InmateService.suggest_cell_block(
        security_classification,
        medical_isolation_required=medical_isolation_required,
    )
    if not suggestion:
        placement_type = (
            'medical-isolation units' if medical_isolation_required
            else 'cell blocks'
        )
        return jsonify({
            'error': (
                f'No available {placement_type} are configured for '
                f'{security_classification} classification.'
            )
        }), 404
    return jsonify({'cell_block': suggestion})


# ---------- Re-admission form ----------
@inmate_bp.route('/readmit/<int:inmate_id>', methods=['GET', 'POST'])
@login_required
@require_permission(Permissions.INMATE_CREATE)
def readmit(inmate_id):
    inmate = InmateService.get(inmate_id)
    if not inmate:
        flash('Inmate not found.', 'danger')
        return redirect(url_for('inmate.list_inmates'))

    if request.method == 'POST':
        data = request.form.to_dict()
        data['prior_medical_summary'] = request.form.get('prior_medical_summary', '')
        document_path, document_name, document_error = MedicalRecordService.save_document(
            request.files.get('prior_medical_document'),
            inmate_id=inmate_id,
        )
        if document_error:
            flash(document_error, 'danger')
            return render_template('inmate/form.html',
                                   mode='returning', inmate=inmate, data=data,
                                   has_probe=False,
                                   enrollment_id=data.get('enrollment_id') or secrets.token_urlsafe(24),
                                   cell_blocks=InmateService.cell_block_options(
                                       medical_isolation_required=inmate.medical_isolation_required
                                   ))
        photo_data = data.pop('photo_data', '')
        data.pop('photo_path', None)
        enrollment_id = data.get('enrollment_id')
        data.pop('enrollment_id', None)
        enrollment = session.get('pending_inmate_enrollment') or {}
        if enrollment.get('enrollment_id') != enrollment_id:
            enrollment = {}
        template = enrollment.get('template')
        quality = enrollment.get('quality', 0)
        photo_path, photo_error = PersonPhotoService.save_capture(photo_data)
        if photo_error:
            MedicalRecordService.delete_document(document_path)
            flash(photo_error, 'danger')
            return render_template('inmate/form.html',
                                   mode='returning', inmate=inmate, data=data,
                                   has_probe=bool(template),
                                   enrollment_id=enrollment_id,
                                   cell_blocks=InmateService.cell_block_options(
                                       medical_isolation_required=inmate.medical_isolation_required
                                   ))
        if photo_path:
            data['photo_path'] = photo_path
        if document_path:
            data['prior_medical_document_path'] = document_path
            data['prior_medical_document_name'] = document_name
        data['photo_data'] = photo_data

        updated, error = InmateService.readmit_inmate(
            actor=current_user, inmate_id=inmate_id, data=data,
            fingerprint_template=template, fingerprint_quality=quality,
        )
        if error:
            PersonPhotoService.delete_photo(photo_path)
            MedicalRecordService.delete_document(document_path)
            flash(error, 'danger')
            return render_template('inmate/form.html',
                                   mode='returning', inmate=inmate, data=data,
                                   has_probe=bool(template),
                                   enrollment_id=enrollment_id,
                                   cell_blocks=InmateService.cell_block_options(
                                       medical_isolation_required=inmate.medical_isolation_required
                                   ))

        if (session.get('pending_inmate_enrollment') or {}).get('enrollment_id') == enrollment_id:
            session.pop('pending_inmate_enrollment', None)
        flash(f'Inmate {updated.inmate_number} re-admitted '
              f'(admission #{updated.total_admissions}).', 'success')
        return redirect(url_for('inmate.detail', inmate_id=updated.inmate_id))

    return render_template('inmate/form.html',
                           mode='returning', inmate=inmate, data={}, has_probe=False,
                           enrollment_id=secrets.token_urlsafe(24),
                           cell_blocks=InmateService.cell_block_options(
                               medical_isolation_required=inmate.medical_isolation_required
                           ))


@inmate_bp.route('/<int:inmate_id>/photo/<filename>')
@login_required
@require_permission(Permissions.INMATE_VIEW)
def photo(inmate_id, filename):
    inmate = InmateService.get(inmate_id)
    if not inmate or inmate.photo_path != filename:
        abort(404)
    return send_from_directory(
        os.path.join(current_app.instance_path, 'person_photos'),
        filename,
        mimetype='image/jpeg',
    )


# ---------- Detail ----------
@inmate_bp.route('/<int:inmate_id>')
@login_required
@require_permission(Permissions.INMATE_VIEW)
def detail(inmate_id):
    from models.inmate import AdmissionEpisode
    from services.edit_request_service import EditRequestService

    inmate = InmateService.get(inmate_id)
    if not inmate:
        flash('Inmate not found.', 'danger')
        return redirect(url_for('inmate.list_inmates'))

    episodes = inmate.admission_episodes.order_by(
        AdmissionEpisode.admission_date.desc()
    ).all()
    disciplinary_logs = inmate.disciplinary_logs.order_by(
        DisciplinaryLog.incident_date.desc(),
        DisciplinaryLog.incident_time.desc(),
        DisciplinaryLog.log_id.desc(),
    ).all()
    escape_attempt_logs = inmate.escape_attempt_logs.order_by(
        EscapeAttemptLog.incident_date.desc(),
        EscapeAttemptLog.incident_time.desc(),
        EscapeAttemptLog.event_id.desc(),
    ).all()
    work_transfer_logs = inmate.work_transfer_logs.order_by(
        WorkTransferLog.checked_out_at.desc(),
        WorkTransferLog.transfer_id.desc(),
    ).all()
    current_work_transfer = next(
        (transfer for transfer in work_transfer_logs if transfer.is_out),
        None,
    )

    pending_edits = EditRequestService.pending_for_inmate(inmate_id)
    medical_records = MedicalRecord.query.filter(
        MedicalRecord.inmate_id == inmate_id,
        or_(
            MedicalRecord.approval_status == 'Approved',
            MedicalRecord.recorded_by == current_user.user_id,
            MedicalRecord.approval_status == 'Pending',
        ),
    ).order_by(MedicalRecord.record_date.desc(), MedicalRecord.record_id.desc()).all()
    if not has_permission(Permissions.MEDICAL_RECORD_APPROVE):
        medical_records = [
            record for record in medical_records
            if record.approval_status == 'Approved'
            or record.recorded_by == current_user.user_id
        ]

    isolation_cell_blocks = []
    medical_isolation_form = InmateMedicalIsolationForm()
    medical_isolation_form.requires_isolation.data = str(
        inmate.medical_isolation_required
    ).lower()
    if (
        has_permission(Permissions.MEDICAL_RECORD_CREATE)
        and inmate.status == 'Active'
    ):
        isolation_cell_blocks = InmateService.cell_block_options(
            inmate.security_classification,
            medical_isolation_required=True,
            exclude_inmate_id=inmate.inmate_id,
        )

    return render_template('inmate/detail.html',
                           inmate=inmate, episodes=episodes,
                           disciplinary_logs=disciplinary_logs,
                           escape_attempt_logs=escape_attempt_logs,
                           work_transfer_logs=work_transfer_logs,
                           current_work_transfer=current_work_transfer,
                           today=date.today().isoformat(),
                           pending_edits=pending_edits,
                           medical_records=medical_records,
                           isolation_cell_blocks=isolation_cell_blocks,
                           medical_isolation_form=medical_isolation_form)


@inmate_bp.route('/<int:inmate_id>/medical-isolation', methods=['POST'])
@login_required
@require_permission(Permissions.MEDICAL_RECORD_CREATE)
def update_medical_isolation(inmate_id):
    inmate = InmateService.get(inmate_id)
    if not inmate:
        abort(404)

    form = InmateMedicalIsolationForm()
    if not form.validate_on_submit():
        flash('The medical-isolation update could not be validated.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    if form.requires_isolation.data not in {'true', 'false'}:
        flash('Choose whether medical isolation is required.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    requires_isolation = form.requires_isolation.data == 'true'
    if inmate.status != 'Active':
        flash('Medical isolation can only be updated for active inmates.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    old_required = inmate.medical_isolation_required
    old_cell_block = inmate.cell_block
    if requires_isolation:
        open_transfer = WorkTransferLog.query.filter_by(
            inmate_id=inmate.inmate_id,
            checked_in_at=None,
        ).first()
        if open_transfer:
            flash(
                'Check the inmate back in from work before placing them in a medical-isolation unit.',
                'danger',
            )
            return redirect(url_for('inmate.detail', inmate_id=inmate_id))

        reason = (form.medical_isolation_reason.data or '').strip()
        if not reason:
            flash('Enter the clinical reason for requiring medical isolation.', 'danger')
            return redirect(url_for('inmate.detail', inmate_id=inmate_id))

        cell_block_name = (form.cell_block.data or '').strip()
        cell_error = InmateService.validate_cell_assignment(
            cell_block_name,
            inmate.security_classification,
            medical_isolation_required=True,
            exclude_inmate_id=inmate.inmate_id,
        )
        if cell_error:
            flash(cell_error, 'danger')
            return redirect(url_for('inmate.detail', inmate_id=inmate_id))

        isolation_cell = CellBlock.query.filter_by(name=cell_block_name).first()
        if not isolation_cell:
            flash('Select a configured medical-isolation unit.', 'danger')
            return redirect(url_for('inmate.detail', inmate_id=inmate_id))

        inmate.cell_block = isolation_cell.name
        inmate.security_classification = isolation_cell.security_classification
        inmate.cell_number = (form.cell_number.data or '').strip() or None
        inmate.medical_isolation_required = True
        inmate.medical_isolation_reason = reason
    else:
        inmate.medical_isolation_required = False
        inmate.medical_isolation_reason = None

    AuditEvent.log_event(
        event_category='MedicalRecord',
        event_type='Medical isolation status updated',
        event_description=(
            f'Medical isolation was '
            f'{"required" if requires_isolation else "cleared"} for '
            f'inmate {inmate.inmate_number}; cell block changed from '
            f'{old_cell_block or "Unassigned"} to {inmate.cell_block or "Unassigned"}.'
        ),
        entity_type='Inmate',
        entity_id=inmate.inmate_id,
        user_id=current_user.user_id,
        username=current_user.username,
        user_role=current_user.role_name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        old_values={
            'medical_isolation_required': old_required,
            'cell_block': old_cell_block,
        },
        new_values={
            'medical_isolation_required': inmate.medical_isolation_required,
            'cell_block': inmate.cell_block,
        },
    )
    db.session.commit()
    flash(
        'Medical isolation is now required and the inmate was placed in the '
        'selected isolation unit.'
        if requires_isolation
        else 'Medical isolation requirement was cleared.',
        'success',
    )
    return redirect(url_for('inmate.detail', inmate_id=inmate_id))


@inmate_bp.route('/<int:inmate_id>/record-death', methods=['POST'])
@login_required
@require_permission(Permissions.MEDICAL_RECORD_CREATE)
def record_death(inmate_id):
    inmate = InmateService.get(inmate_id)
    if not inmate:
        abort(404)

    def back():
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    if inmate.status != 'Active':
        flash('A death can only be recorded for an inmate who is currently in custody.', 'danger')
        return back()

    try:
        death_date = date.fromisoformat((request.form.get('date_of_death') or '').strip())
    except ValueError:
        flash('Enter a valid date of death.', 'danger')
        return back()

    time_text = (request.form.get('time_of_death') or '').strip()
    try:
        death_time = time.fromisoformat(time_text) if time_text else None
    except ValueError:
        flash('Enter a valid time of death.', 'danger')
        return back()

    episode = inmate.admission_episodes.filter_by(is_current=True).first()
    admitted_on = (
        episode.admission_date if episode else inmate.current_admission_date
    )
    if death_date > date.today():
        flash('The date of death cannot be in the future.', 'danger')
        return back()
    if admitted_on and death_date < admitted_on:
        flash('The date of death cannot be before the admission date.', 'danger')
        return back()

    cause = (request.form.get('cause_of_death') or '').strip()
    if not cause:
        flash('Enter the cause of death.', 'danger')
        return back()
    place = (request.form.get('place_of_death') or '').strip()[:150] or None

    open_transfer = WorkTransferLog.query.filter_by(
        inmate_id=inmate.inmate_id, checked_in_at=None
    ).first()
    if open_transfer:
        open_transfer.checked_in_at = datetime.now()

    old_cell = inmate.cell_block
    inmate.status = 'Deceased'
    inmate.date_of_death = death_date
    inmate.time_of_death = death_time
    inmate.place_of_death = place
    inmate.cause_of_death = cause
    inmate.death_recorded_by = current_user.user_id
    inmate.death_recorded_at = datetime.now()
    inmate.actual_release_date = death_date
    inmate.cell_block = None
    inmate.cell_number = None
    if episode:
        episode.release_date = death_date
        episode.release_type = 'Death'
        episode.release_notes = cause
        episode.releasing_officer_id = current_user.user_id
        episode.is_current = False

    AuditEvent.log_event(
        event_category='Inmate',
        event_type='Death recorded',
        event_description=(
            f'Death recorded for inmate {inmate.inmate_number} ({inmate.full_name}) '
            f'on {death_date.isoformat()}.'
        ),
        entity_type='Inmate',
        entity_id=inmate.inmate_id,
        user_id=current_user.user_id,
        username=current_user.username,
        user_role=current_user.role_name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        old_values={'status': 'Active', 'cell_block': old_cell},
        new_values={
            'status': 'Deceased',
            'date_of_death': death_date.isoformat(),
            'time_of_death': death_time.isoformat() if death_time else None,
            'place_of_death': place,
            'cause_of_death': cause,
        },
    )
    db.session.commit()
    flash(f'Death of {inmate.full_name} recorded for {death_date.strftime("%d %b %Y")}.', 'success')
    return back()


@inmate_bp.route('/<int:inmate_id>/disciplinary', methods=['POST'])
@login_required
@require_permission(Permissions.DISCIPLINARY_CREATE)
def add_disciplinary_log(inmate_id):
    inmate = InmateService.get(inmate_id)
    if not inmate:
        abort(404)

    incident_type = (request.form.get('incident_type') or '').strip()
    description = (request.form.get('description') or '').strip()
    date_value = (request.form.get('incident_date') or '').strip()
    time_value = (request.form.get('incident_time') or '').strip()
    witnesses = (request.form.get('witnesses') or '').strip()
    action_taken = (request.form.get('action_taken') or '').strip()
    injuries_value = (request.form.get('injured_count') or '').strip()
    is_violent = request.form.get('is_violent') == 'on'

    try:
        incident_date = datetime.strptime(date_value, '%Y-%m-%d').date()
    except ValueError:
        flash('Enter a valid incident date.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))
    try:
        incident_time = datetime.strptime(time_value, '%H:%M').time()
    except ValueError:
        flash('Enter a valid incident time.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))
    try:
        injured_count = int(injuries_value) if injuries_value else None
        if injured_count is not None and not 0 <= injured_count <= 2_147_483_647:
            raise ValueError
    except ValueError:
        flash(
            'Number injured must be a whole number between 0 and 2,147,483,647.',
            'danger',
        )
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    if not incident_type or len(incident_type) > 100:
        flash('Enter an incident type of no more than 100 characters.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))
    if not description:
        flash('Describe what happened or what was attempted.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))
    if len(description) > 4000 or len(witnesses) > 2000 or len(action_taken) > 2000:
        flash(
            'Incident description, witnesses, and action fields must be within their length limits.',
            'danger',
        )
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    log = DisciplinaryLog(
        inmate_id=inmate.inmate_id,
        incident_date=incident_date,
        incident_time=incident_time,
        incident_type=incident_type,
        description=description,
        is_violent=is_violent,
        injured_count=injured_count,
        witnesses=witnesses or None,
        action_taken=action_taken or None,
        reported_by=current_user.user_id,
    )
    db.session.add(log)
    if is_violent:
        inmate.violence_history = True
    AuditEvent.log_event(
        event_category='Inmate',
        event_type='Disciplinary Incident',
        event_description=(
            f'Recorded {incident_type} incident for inmate '
            f'{inmate.inmate_number}'
        ),
        entity_type='Inmate',
        entity_id=inmate.inmate_id,
        user_id=current_user.user_id,
        username=current_user.username,
        user_role=current_user.role_name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        new_values={
            'incident_date': incident_date.isoformat(),
            'incident_time': incident_time.strftime('%H:%M'),
            'incident_type': incident_type,
            'description': description,
            'is_violent': is_violent,
            'injured_count': injured_count,
            'action_taken': action_taken or None,
            'witnesses': witnesses or None,
        },
    )
    db.session.commit()
    flash('Disciplinary incident added to the inmate record.', 'success')
    return redirect(url_for('inmate.detail', inmate_id=inmate_id))


@inmate_bp.route('/<int:inmate_id>/escape-history', methods=['POST'])
@login_required
@require_permission(Permissions.DISCIPLINARY_CREATE)
def add_escape_attempt(inmate_id):
    inmate = InmateService.get(inmate_id)
    if not inmate:
        abort(404)

    date_value = (request.form.get('incident_date') or '').strip()
    time_value = (request.form.get('incident_time') or '').strip()
    description = (request.form.get('description') or '').strip()
    outcome = (request.form.get('outcome') or '').strip()
    action_taken = (request.form.get('action_taken') or '').strip()

    try:
        incident_date = datetime.strptime(date_value, '%Y-%m-%d').date()
    except ValueError:
        flash('Enter a valid escape incident date.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))
    try:
        incident_time = datetime.strptime(time_value, '%H:%M').time()
    except ValueError:
        flash('Enter a valid escape incident time.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))
    if not description or len(description) > 4000:
        flash('Describe the escape attempt in 1 to 4,000 characters.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))
    if len(outcome) > 2000 or len(action_taken) > 2000:
        flash('Outcome and action fields must be no more than 2,000 characters.', 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    event = EscapeAttemptLog(
        inmate_id=inmate.inmate_id,
        incident_date=incident_date,
        incident_time=incident_time,
        description=description,
        outcome=outcome or None,
        action_taken=action_taken or None,
        reported_by=current_user.user_id,
    )
    db.session.add(event)
    inmate.escape_attempt_history = True
    AuditEvent.log_event(
        event_category='Inmate',
        event_type='Escape Attempt',
        event_description=f'Recorded escape history for inmate {inmate.inmate_number}',
        entity_type='Inmate',
        entity_id=inmate.inmate_id,
        user_id=current_user.user_id,
        username=current_user.username,
        user_role=current_user.role_name,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
        new_values={
            'incident_date': incident_date.isoformat(),
            'incident_time': incident_time.strftime('%H:%M'),
            'description': description,
            'outcome': outcome or None,
            'action_taken': action_taken or None,
        },
    )
    db.session.commit()
    flash('Escape history added to the inmate record.', 'success')
    return redirect(url_for('inmate.detail', inmate_id=inmate_id))


@inmate_bp.route('/register', methods=['GET', 'POST'])
def register_inmate():
    if request.method == 'POST':
        full_name = request.form.get('full_name')
        offense = request.form.get('offense')
        selected_cell_id = request.form.get('cell_id')  # Form dropdown value

        # AUTO-ASSIGNMENT LOGIC (Equal Population Distribution)
        if not selected_cell_id or selected_cell_id == 'auto':
            # Select the block with lowest occupancy percentage or lowest count
            all_blocks = CellBlock.query.all()
            if all_blocks:
                # Pick cell with lowest current_occupancy
                chosen_cell = min(all_blocks, key=lambda b: (b.current_occupancy / b.capacity) if b.capacity > 0 else 0)
                selected_cell_id = chosen_cell.id
            else:
                selected_cell_id = None

        # Create Inmate Record
        new_inmate = Inmate(
            full_name=full_name,
            crime=offense,
            cell_id=selected_cell_id,
            status='Active'
        )
        db.session.add(new_inmate)

        # Update Cell Occupancy Counter
        if selected_cell_id:
            cell = CellBlock.query.get(selected_cell_id)
            if cell:
                cell.current_occupancy = (cell.current_occupancy or 0) + 1

        db.session.commit()
        flash('Inmate successfully registered and assigned!', 'success')
        return redirect(url_for('inmate.list_inmates'))

    # GET Request: Pass all cell blocks to form dropdown
    cell_blocks = CellBlock.query.all()
    return render_template('inmate_register.html', cell_blocks=cell_blocks)