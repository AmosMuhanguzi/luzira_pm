# routes/visitor.py
import base64
import os
import secrets
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, session, current_app, jsonify, abort,
                   send_from_directory)
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from sqlalchemy import or_
from wtforms import TextAreaField
from wtforms.validators import DataRequired, Length
from extensions import csrf, db
from services.rbac import require_permission, Permissions
from services.visitor_service import VisitorService
from services.visitor_matcher import VisitorMatcher
from services.biometric_agent_client import BiometricAgentClient, BiometricAgentError
from services.person_photo_service import PersonPhotoService
from models.visitor import Visitor, VisitorBlacklistEvent, VisitLog
from models.inmate import Inmate


visitor_bp = Blueprint('visitor', __name__, url_prefix='/visitor')
csrf.exempt(visitor_bp)


class VisitorBlacklistForm(FlaskForm):
    reason = TextAreaField(
        validators=[DataRequired(), Length(max=2000)],
    )


def _mock_mode():
    return current_app.config.get('BIOMETRIC_MOCK_MODE', False)


def _mock_template():
    seed = (current_app.config.get('SECRET_KEY') or 'x') * 4
    return base64.b64encode((seed.encode() * 4)[:256]).decode('utf-8')


# ---------- List ----------
@visitor_bp.route('/')
@login_required
@require_permission(Permissions.VISITOR_VIEW)
def list_visitors():
    search = request.args.get('q', '').strip()
    page   = request.args.get('page', 1, type=int)
    pagination = VisitorService.list_visitors(
        search=search, page=page, per_page=15
    )
    visitor_ids = [visitor.visitor_id for visitor in pagination.items]
    blacklist_counts = dict(
        db.session.query(
            VisitorBlacklistEvent.visitor_id,
            db.func.count(VisitorBlacklistEvent.event_id),
        )
        .filter(
            VisitorBlacklistEvent.visitor_id.in_(visitor_ids),
            VisitorBlacklistEvent.action == 'Blocked',
        )
        .group_by(VisitorBlacklistEvent.visitor_id)
        .all()
    ) if visitor_ids else {}
    return render_template('visitor/list.html',
                           pagination=pagination, visitors=pagination.items,
                           search=search,
                           blacklist_counts=blacklist_counts,
                           permanent_blacklist_threshold=(
                               VisitorService.PERMANENT_BLACKLIST_THRESHOLD
                           ))


# ---------- Scan page ----------
@visitor_bp.route('/scan')
@login_required
@require_permission(Permissions.VISITOR_BIOMETRIC_VERIFY)
def scan():
    return render_template(
        'visitor/scan.html',
        mock_mode=_mock_mode(),
        blacklist_form=VisitorBlacklistForm(),
    )


# ---------- API: scan + 1:N identify ----------
@visitor_bp.route('/api/scan-identify', methods=['POST'])
@login_required
@require_permission(Permissions.VISITOR_BIOMETRIC_VERIFY)
def api_scan_identify():
    try:
        if _mock_mode():
            probe = {'success': True, 'template': _mock_template(), 'quality': 90}
        else:
            probe = BiometricAgentClient(
                base_url=current_app.config['BIOMETRIC_AGENT_URL'], timeout=25
            ).scan()
    except BiometricAgentError as e:
        return jsonify({'ok': False, 'error': str(e)}), 503

    if not probe.get('success'):
        return jsonify({'ok': False, 'error': probe.get('error', 'Scan failed')}), 400

    threshold = current_app.config.get('BIOMETRIC_MATCH_THRESHOLD', 75)
    result = VisitorMatcher.identify(probe['template'], threshold=threshold)

    if result['match']:
        v = result['visitor']
        blacklist_incident_count = VisitorService.blacklist_incident_count(
            v.visitor_id
        )
        return jsonify({
            'ok': True, 'match': True,
            'score': round(result['score'], 1),
            'enrolled_count': result['enrolled_count'],
            'visitor': {
                'visitor_id': v.visitor_id,
                'visitor_number': v.visitor_number,
                'full_name': v.full_name,
                'phone_number': v.phone_number,
                'relationship_to_inmate': v.relationship_to_inmate,
                'total_visits': v.total_visits,
                'is_blacklisted': v.is_blacklisted,
                'blacklist_reason': v.blacklist_reason,
                'blacklist_incident_count': blacklist_incident_count,
                'permanently_blacklisted': (
                    blacklist_incident_count
                    >= VisitorService.PERMANENT_BLACKLIST_THRESHOLD
                ),
                'blacklist_threshold': VisitorService.PERMANENT_BLACKLIST_THRESHOLD,
                'anomaly_flag': v.anomaly_flag,
            },
            'redirect': url_for('visitor.check_in', visitor_id=v.visitor_id),
            'block_url': url_for('visitor.blacklist', visitor_id=v.visitor_id),
        })

    return jsonify({
        'ok': True, 'match': False,
        'score': round(result['score'], 1),
        'enrolled_count': result['enrolled_count'],
        'redirect': url_for('visitor.register'),
    })


@visitor_bp.route('/api/enroll-fingerprint', methods=['POST'])
@login_required
@require_permission(Permissions.VISITOR_CREATE)
def api_enroll_fingerprint():
    payload = request.get_json(silent=True) or {}
    enrollment_id = payload.get('enrollment_id')
    if not isinstance(enrollment_id, str) or not enrollment_id:
        return jsonify({'ok': False, 'error': 'Reload the form before scanning.'}), 400
    try:
        if _mock_mode():
            probe = {
                'success': True,
                'template': _mock_template(),
                'quality': 90,
                'samples_captured': 1,
            }
        else:
            probe = BiometricAgentClient(
                base_url=current_app.config['BIOMETRIC_AGENT_URL'], timeout=25
            ).enroll(
                samples=current_app.config.get('BIOMETRIC_SAMPLES_PER_ENROLL', 3)
            )
    except BiometricAgentError as error:
        pending = session.get('pending_visitor_enrollment') or {}
        if pending.get('enrollment_id') == enrollment_id:
            session.pop('pending_visitor_enrollment', None)
        return jsonify({'ok': False, 'error': str(error)}), 503

    if not probe.get('success') or not probe.get('template'):
        pending = session.get('pending_visitor_enrollment') or {}
        if pending.get('enrollment_id') == enrollment_id:
            session.pop('pending_visitor_enrollment', None)
        return jsonify({
            'ok': False,
            'error': probe.get('error', 'Fingerprint enrollment failed.'),
        }), 400

    try:
        quality = float(probe['quality'])
    except (KeyError, TypeError, ValueError):
        pending = session.get('pending_visitor_enrollment') or {}
        if pending.get('enrollment_id') == enrollment_id:
            session.pop('pending_visitor_enrollment', None)
        return jsonify({
            'ok': False,
            'error': 'The scanner did not report fingerprint quality. Try again.',
        }), 400

    quality_threshold = current_app.config.get('BIOMETRIC_QUALITY_MIN', 60)
    if not 0 <= quality <= 100 or quality < quality_threshold:
        pending = session.get('pending_visitor_enrollment') or {}
        if pending.get('enrollment_id') == enrollment_id:
            session.pop('pending_visitor_enrollment', None)
        return jsonify({
            'ok': False,
            'error': f'Fingerprint quality is too low ({quality:g}%). Try again.',
        }), 400

    session['pending_visitor_enrollment'] = {
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


# ---------- Register new visitor ----------
@visitor_bp.route('/register', methods=['GET', 'POST'])
@login_required
@require_permission(Permissions.VISITOR_CREATE)
def register():
    if request.method == 'POST':
        data = request.form.to_dict()
        photo_data = data.pop('photo_data', '')
        data.pop('photo_path', None)
        enrollment_id = data.get('enrollment_id')
        data.pop('enrollment_id', None)
        enrollment = session.get('pending_visitor_enrollment') or {}
        if enrollment.get('enrollment_id') != enrollment_id:
            enrollment = {}
        template = enrollment.get('template')
        quality = enrollment.get('quality', 0)

        photo_path, photo_error = PersonPhotoService.save_capture(photo_data)
        if photo_error:
            flash(photo_error, 'danger')
            return render_template('visitor/register.html', data=data,
                                   has_probe=bool(template),
                                   enrollment_id=enrollment_id)
        if photo_path:
            data['photo_path'] = photo_path
        data['photo_data'] = photo_data

        visitor, error = VisitorService.register_visitor(
            actor=current_user, data=data,
            fingerprint_template=template, fingerprint_quality=quality,
        )
        if error:
            PersonPhotoService.delete_photo(photo_path)
            flash(error, 'danger')
            return render_template('visitor/register.html', data=data,
                                   has_probe=bool(template),
                                   enrollment_id=enrollment_id)

        if (session.get('pending_visitor_enrollment') or {}).get('enrollment_id') == enrollment_id:
            session.pop('pending_visitor_enrollment', None)
        flash(f'Visitor {visitor.visitor_number} registered.', 'success')
        # Continue straight into check-in
        return redirect(url_for('visitor.check_in', visitor_id=visitor.visitor_id))

    return render_template(
        'visitor/register.html', data={}, has_probe=False,
        enrollment_id=secrets.token_urlsafe(24),
    )


@visitor_bp.route('/<int:visitor_id>/photo/<filename>')
@login_required
@require_permission(Permissions.VISITOR_VIEW)
def photo(visitor_id, filename):
    visitor = VisitorService.get(visitor_id)
    if not visitor or visitor.photo_path != filename:
        abort(404)
    return send_from_directory(
        os.path.join(current_app.instance_path, 'person_photos'),
        filename,
        mimetype='image/jpeg',
    )


# ---------- Visitor detail ----------
@visitor_bp.route('/<int:visitor_id>')
@login_required
@require_permission(Permissions.VISITOR_VIEW)
def detail(visitor_id):
    visitor = VisitorService.get(visitor_id)
    if not visitor:
        flash('Visitor not found.', 'danger')
        return redirect(url_for('visitor.list_visitors'))

    # Determine sorting column dynamically based on VisitLog attributes
    order_col = getattr(VisitLog, 'check_in_time', getattr(VisitLog, 'created_at', VisitLog.visit_id))

    visits = visitor.visit_logs.order_by(
        order_col.desc(), VisitLog.visit_id.desc()
    ).limit(30).all()
    blacklist_events = visitor.blacklist_events.order_by(
        VisitorBlacklistEvent.event_at.desc(),
        VisitorBlacklistEvent.event_id.desc(),
    ).all()
    blacklist_incident_count = sum(
        event.action == 'Blocked' for event in blacklist_events
    )

    return render_template(
        'visitor/detail.html',
        visitor=visitor,
        visits=visits,
        blacklist_events=blacklist_events,
        blacklist_incident_count=blacklist_incident_count,
        permanent_blacklist_threshold=VisitorService.PERMANENT_BLACKLIST_THRESHOLD,
        blacklist_form=VisitorBlacklistForm(),
        clear_blacklist_form=VisitorBlacklistForm(),
    )


@visitor_bp.route('/<int:visitor_id>/blacklist', methods=['POST'])
@login_required
@require_permission(Permissions.VISITOR_BLACKLIST)
def blacklist(visitor_id):
    form = VisitorBlacklistForm()
    if not form.validate_on_submit():
        flash('Enter a valid reason for blocking the visitor (maximum 2,000 characters).', 'danger')
        return redirect(url_for('visitor.detail', visitor_id=visitor_id))

    result, error = VisitorService.blacklist_visitor(
        actor=current_user,
        visitor_id=visitor_id,
        reason=form.reason.data,
    )
    if error:
        flash(error, 'danger')
    elif result['permanent']:
        flash(
            f'Visitor blacklisted for incident {result["incident_count"]}. '
            'The blacklist is now permanent and cannot be cleared.',
            'danger',
        )
    else:
        flash(
            f'Visitor blocked. This is incident {result["incident_count"]} '
            f'of {VisitorService.PERMANENT_BLACKLIST_THRESHOLD}; only an administrator '
            'can clear the blacklist.',
            'success',
        )
    return redirect(url_for('visitor.detail', visitor_id=visitor_id))


@visitor_bp.route('/<int:visitor_id>/blacklist/clear', methods=['POST'])
@login_required
@require_permission(Permissions.VISITOR_BLACKLIST_CLEAR)
def clear_blacklist(visitor_id):
    form = VisitorBlacklistForm()
    if not form.validate_on_submit():
        flash('Enter a valid reason for clearing the blacklist.', 'danger')
        return redirect(url_for('visitor.detail', visitor_id=visitor_id))

    result, error = VisitorService.clear_blacklist(
        actor=current_user,
        visitor_id=visitor_id,
        reason=form.reason.data,
    )
    if error:
        flash(error, 'danger')
    else:
        flash(
            f'Blacklist cleared. This visitor has {result["incident_count"]} '
            'blocking incident(s) recorded.',
            'success',
        )
    return redirect(url_for('visitor.detail', visitor_id=visitor_id))

# ---------- Check-in ----------
@visitor_bp.route('/<int:visitor_id>/check-in', methods=['GET', 'POST'])
@login_required
@require_permission(Permissions.VISIT_CREATE)
def check_in(visitor_id):
    visitor = VisitorService.get(visitor_id)
    if not visitor:
        flash('Visitor not found.', 'danger')
        return redirect(url_for('visitor.list_visitors'))

    if visitor.is_blacklisted:
        flash(f'Visitor is blacklisted: {visitor.blacklist_reason or "no reason given"}',
              'danger')
        return redirect(url_for('visitor.detail', visitor_id=visitor_id))

    if request.method == 'POST':
        inmate_id = request.form.get('inmate_id', type=int)
        if not inmate_id:
            flash('Please search for and select an inmate to visit.', 'warning')
        else:
            visit, error = VisitorService.check_in(
                actor=current_user,
                visitor_id=visitor_id,
                inmate_id=inmate_id,
                data=request.form.to_dict(),
            )
            if error:
                flash(error, 'danger')
            else:
                return redirect(url_for('visitor.visit_success', visit_id=visit.visit_id))

    return render_template('visitor/select_inmate.html',
                           visitor=visitor)


@visitor_bp.route('/api/inmate-search')
@login_required
@require_permission(Permissions.VISIT_CREATE)
def api_inmate_search():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify({'results': []})

    pattern = f'%{query}%'
    matches = Inmate.query.filter(
        Inmate.status == 'Active',
        or_(
            Inmate.full_name.ilike(pattern),
            Inmate.inmate_number.ilike(pattern),
            Inmate.national_id_number.ilike(pattern),
            Inmate.passport_number.ilike(pattern),
            Inmate.court_case_number.ilike(pattern),
            Inmate.alias_names.ilike(pattern),
        ),
    ).order_by(Inmate.full_name.asc()).limit(20).all()

    return jsonify({
        'results': [{
            'inmate_id': inmate.inmate_id,
            'inmate_number': inmate.inmate_number,
            'full_name': inmate.full_name,
            'national_id_number': inmate.national_id_number,
            'cell_block': inmate.cell_block,
        } for inmate in matches],
    })


# ---------- Visit success ----------
@visitor_bp.route('/visit/<int:visit_id>/success')
@login_required
@require_permission(Permissions.VISIT_VIEW)
def visit_success(visit_id):
    visit = VisitLog.query.get(visit_id)
    if not visit:
        flash('Visit not found.', 'danger')
        return redirect(url_for('visitor.list_visitors'))
    return render_template('visitor/visit_success.html', visit=visit)


# ---------- Check-out ----------
@visitor_bp.route('/visit/<int:visit_id>/check-out', methods=['POST'])
@login_required
@require_permission(Permissions.VISIT_CREATE)
def check_out(visit_id):
    ok, err = VisitorService.check_out(current_user, visit_id)
    if ok:
        flash('Visitor checked out.', 'success')
    else:
        flash(err, 'danger')
    visit = VisitLog.query.get(visit_id)
    if visit:
        return redirect(url_for('visitor.detail', visitor_id=visit.visitor_id))
    return redirect(url_for('visitor.list_visitors'))