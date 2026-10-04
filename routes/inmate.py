# routes/inmate.py
import base64
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, session, current_app, jsonify)
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import DecimalField, HiddenField, SelectField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional
from sqlalchemy import or_

from extensions import csrf, db
from models.cell import CellBlock
from services.rbac import require_permission, Permissions
from services.inmate_service import InmateService
from services.inmate_matcher import InmateMatcher
from services.biometric_agent_client import BiometricAgentClient, BiometricAgentError
from models.inmate import AdmissionEpisode, Inmate
from models.audit import AuditEvent
from models.medical import DisciplinaryLog, MedicalRecord
from models.user import UserAccount
from services.biometric_matcher import compare_templates


inmate_bp = Blueprint('inmate', __name__, url_prefix='/inmate')
csrf.exempt(inmate_bp)

RELEASE_TYPES = (
    'Sentence completed',
    'Court order',
    'Parole',
    'Transfer',
    'Other',
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
        validators=[DataRequired(), NumberRange(min=Decimal('0.00'))],
    )
    release_property_claims = TextAreaField(
        'Property returned or claims',
        validators=[Optional(), Length(max=4000)],
    )
    submit = SubmitField('Record release')


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
            return render_template('inmate/release.html', form=form)

        scan_proof = session.get('release_fingerprint_verified')
        if not _valid_release_scan_proof(scan_proof, inmate.inmate_id):
            flash('Scan and verify this inmate’s fingerprint before recording the release.', 'danger')
            return render_template(
                'inmate/release.html',
                form=form,
                selected_inmate_id=inmate.inmate_id,
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

        discharged_at = datetime.now(ZoneInfo('Africa/Kampala')).replace(tzinfo=None)
        release_date = discharged_at.date()
        release_type = form.release_type.data
        old_cell = inmate.cell_block

        episode.release_date = release_date
        episode.release_type = release_type
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
            'next_of_kin_address': inmate.next_of_kin_address,
            'height_cm': inmate.height_cm,
            'weight_kg': inmate.weight_kg,
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
            'cell_block': inmate.cell_block,
            'cell_number': inmate.cell_number,
            'security_classification': inmate.security_classification,
            'has_medical_condition': inmate.has_medical_condition,
            'medical_alert': inmate.medical_alert,
            'risk_level': inmate.risk_level,
            'violence_history': inmate.violence_history,
            'escape_attempt_history': inmate.escape_attempt_history,
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
            'type': log.incident_type,
            'description': log.description,
            'action': log.action_taken,
            'punishment': log.punishment_assigned,
        } for log in disciplinary_logs],
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


@inmate_bp.route('/release/<int:episode_id>/print')
@login_required
@require_permission(Permissions.INMATE_RELEASE)
def release_print(episode_id):
    episode = AdmissionEpisode.query.filter(
        AdmissionEpisode.episode_id == episode_id,
        AdmissionEpisode.release_date.isnot(None),
    ).first_or_404()
    officer = db.session.get(UserAccount, episode.releasing_officer_id)
    return render_template(
        'inmate/release_print.html',
        episode=episode,
        officer=officer,
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

    session['pending_inmate_probe'] = probe_template
    session['pending_inmate_probe_quality'] = probe.get('quality', 0)

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


# ---------- New inmate form ----------
@inmate_bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_permission(Permissions.INMATE_CREATE)
def new_intake():
    if request.method == 'POST':
        data = request.form.to_dict()
        template = session.get('pending_inmate_probe')
        quality  = session.get('pending_inmate_probe_quality', 0)

        inmate, error = InmateService.create_inmate(
            actor=current_user, data=data,
            fingerprint_template=template,
            fingerprint_quality=quality,
        )
        if error:
            flash(error, 'danger')
            return render_template('inmate/form.html',
                                   mode='new', data=data,
                                   has_probe=bool(template),
                                   cell_blocks=InmateService.cell_block_options())

        session.pop('pending_inmate_probe', None)
        session.pop('pending_inmate_probe_quality', None)
        flash(f'Inmate {inmate.inmate_number} registered successfully.', 'success')
        return redirect(url_for('inmate.detail', inmate_id=inmate.inmate_id))

    has_probe = 'pending_inmate_probe' in session
    return render_template('inmate/form.html',
                           mode='new', data={}, has_probe=has_probe,
                           cell_blocks=InmateService.cell_block_options())


@inmate_bp.route('/api/cell-assignment')
@login_required
@require_permission(Permissions.INMATE_CREATE)
def api_cell_assignment():
    security_classification = request.args.get('security_classification', '').strip()
    if security_classification not in InmateService.SECURITY_CLASSIFICATIONS:
        return jsonify({'error': 'Select a valid security classification.'}), 400

    suggestion = InmateService.suggest_cell_block(security_classification)
    if not suggestion:
        return jsonify({
            'error': (
                f'No available cell blocks are configured for '
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
        updated, error = InmateService.readmit_inmate(
            actor=current_user, inmate_id=inmate_id, data=data
        )
        if error:
            flash(error, 'danger')
            return render_template('inmate/form.html',
                                   mode='returning', inmate=inmate, data=data,
                                   cell_blocks=InmateService.cell_block_options())

        session.pop('pending_inmate_probe', None)
        session.pop('pending_inmate_probe_quality', None)
        flash(f'Inmate {updated.inmate_number} re-admitted '
              f'(admission #{updated.total_admissions}).', 'success')
        return redirect(url_for('inmate.detail', inmate_id=updated.inmate_id))

    return render_template('inmate/form.html',
                           mode='returning', inmate=inmate, data={},
                           cell_blocks=InmateService.cell_block_options())


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

    pending_edits = EditRequestService.pending_for_inmate(inmate_id)

    return render_template('inmate/detail.html',
                           inmate=inmate, episodes=episodes,
                           pending_edits=pending_edits)

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