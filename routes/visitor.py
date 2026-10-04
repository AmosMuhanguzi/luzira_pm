# routes/visitor.py
import base64
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, session, current_app, jsonify)
from flask_login import login_required, current_user
from sqlalchemy import or_
from models import Visitor, VisitLog

from extensions import csrf
from services.rbac import require_permission, Permissions
from services.visitor_service import VisitorService
from services.visitor_matcher import VisitorMatcher
from services.biometric_agent_client import BiometricAgentClient, BiometricAgentError
from models.visitor import Visitor, VisitLog
from models.inmate import Inmate


visitor_bp = Blueprint('visitor', __name__, url_prefix='/visitor')
csrf.exempt(visitor_bp)


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
    return render_template('visitor/list.html',
                           pagination=pagination, visitors=pagination.items,
                           search=search)


# ---------- Scan page ----------
@visitor_bp.route('/scan')
@login_required
@require_permission(Permissions.VISITOR_BIOMETRIC_VERIFY)
def scan():
    return render_template('visitor/scan.html', mock_mode=_mock_mode())


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

    session['pending_visitor_probe'] = probe['template']
    session['pending_visitor_probe_quality'] = probe.get('quality', 0)

    if result['match']:
        v = result['visitor']
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
                'anomaly_flag': v.anomaly_flag,
            },
            'redirect': url_for('visitor.check_in', visitor_id=v.visitor_id),
        })

    return jsonify({
        'ok': True, 'match': False,
        'score': round(result['score'], 1),
        'enrolled_count': result['enrolled_count'],
        'redirect': url_for('visitor.register'),
    })


# ---------- Register new visitor ----------
@visitor_bp.route('/register', methods=['GET', 'POST'])
@login_required
@require_permission(Permissions.VISITOR_CREATE)
def register():
    if request.method == 'POST':
        data = request.form.to_dict()
        template = session.get('pending_visitor_probe')
        quality  = session.get('pending_visitor_probe_quality', 0)

        visitor, error = VisitorService.register_visitor(
            actor=current_user, data=data,
            fingerprint_template=template, fingerprint_quality=quality,
        )
        if error:
            flash(error, 'danger')
            return render_template('visitor/register.html', data=data,
                                   has_probe=bool(template))

        session.pop('pending_visitor_probe', None)
        session.pop('pending_visitor_probe_quality', None)
        flash(f'Visitor {visitor.visitor_number} registered.', 'success')
        # Continue straight into check-in
        return redirect(url_for('visitor.check_in', visitor_id=visitor.visitor_id))

    has_probe = 'pending_visitor_probe' in session
    return render_template('visitor/register.html', data={}, has_probe=has_probe)


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

    return render_template('visitor/detail.html', visitor=visitor, visits=visits)

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