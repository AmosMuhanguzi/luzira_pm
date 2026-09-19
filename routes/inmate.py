# routes/inmate.py
import base64
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, session, current_app, jsonify)
from flask_login import login_required, current_user

from extensions import csrf
from services.rbac import require_permission, Permissions
from services.inmate_service import InmateService
from services.inmate_matcher import InmateMatcher
from services.biometric_agent_client import BiometricAgentClient, BiometricAgentError
from models.inmate import AdmissionEpisode


inmate_bp = Blueprint('inmate', __name__, url_prefix='/inmate')
csrf.exempt(inmate_bp)


def _agent():
    return BiometricAgentClient(
        base_url=current_app.config['BIOMETRIC_AGENT_URL'],
        timeout=25,
    )


def _mock_mode():
    return current_app.config.get('BIOMETRIC_MOCK_MODE', False)


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
                                   has_probe=bool(template))

        session.pop('pending_inmate_probe', None)
        session.pop('pending_inmate_probe_quality', None)
        flash(f'Inmate {inmate.inmate_number} registered successfully.', 'success')
        return redirect(url_for('inmate.detail', inmate_id=inmate.inmate_id))

    has_probe = 'pending_inmate_probe' in session
    return render_template('inmate/form.html',
                           mode='new', data={}, has_probe=has_probe)


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
                                   mode='returning', inmate=inmate, data=data)

        session.pop('pending_inmate_probe', None)
        session.pop('pending_inmate_probe_quality', None)
        flash(f'Inmate {updated.inmate_number} re-admitted '
              f'(admission #{updated.total_admissions}).', 'success')
        return redirect(url_for('inmate.detail', inmate_id=updated.inmate_id))

    return render_template('inmate/form.html',
                           mode='returning', inmate=inmate, data={})


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
