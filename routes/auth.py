# routes/auth.py
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, session, current_app, jsonify)
from flask_login import login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo

from services.auth_service import AuthService
from extensions import csrf


auth_bp = Blueprint('auth', __name__)

# All auth routes use a pending-session token for state; exempt from CSRF
csrf.exempt(auth_bp)


# ---------- Forms ----------
class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(3, 80)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember me')  # kept so template doesn't break
    submit   = SubmitField('Continue')


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current password', validators=[DataRequired()])
    new_password     = PasswordField('New password',
                                     validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField('Confirm new password',
                                     validators=[DataRequired(),
                                                 EqualTo('new_password',
                                                         message='Passwords must match')])
    submit = SubmitField('Update password')


# ---------- Public root ----------
@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('auth.dashboard'))
    return redirect(url_for('auth.login'))


# ---------- Step 1: credentials ----------
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        user, error = AuthService.authenticate(
            username=form.username.data,
            password=form.password.data,
            ip=request.remote_addr,
            user_agent=request.headers.get('User-Agent'),
        )

        if not user:
            flash(error, 'danger')
            return render_template('auth/login.html', form=form)

        # Password OK. Require fingerprint as step 2.
        timeout = current_app.config.get('LOGIN_PENDING_TIMEOUT_SECONDS', 180)
        AuthService.set_pending_login(session, user, timeout)

        if not user.has_biometric():
            return redirect(url_for('auth.login_enroll'))
        return redirect(url_for('auth.login_fingerprint'))

    return render_template('auth/login.html', form=form)


# ---------- Step 2a: verify fingerprint ----------
@auth_bp.route('/login/fingerprint')
def login_fingerprint():
    user = AuthService.get_pending_user(session)
    if not user:
        flash('Session expired. Please sign in again.', 'warning')
        return redirect(url_for('auth.login'))

    return render_template(
        'auth/login_fingerprint.html',
        user=user,
        agent_url=current_app.config['BIOMETRIC_AGENT_URL'],
        mock_mode=current_app.config['BIOMETRIC_MOCK_MODE'],
        token=session['pending_login']['token'],
    )


# ---------- Step 2b: first-time enrolment ----------
@auth_bp.route('/login/enroll')
def login_enroll():
    user = AuthService.get_pending_user(session)
    if not user:
        flash('Session expired. Please sign in again.', 'warning')
        return redirect(url_for('auth.login'))

    return render_template(
        'auth/login_enroll.html',
        user=user,
        agent_url=current_app.config['BIOMETRIC_AGENT_URL'],
        mock_mode=current_app.config['BIOMETRIC_MOCK_MODE'],
        samples=current_app.config['BIOMETRIC_SAMPLES_PER_ENROLL'],
        token=session['pending_login']['token'],
    )


# ---------- API: verify fingerprint (step 2a) ----------
@auth_bp.route('/api/login/verify-fingerprint', methods=['POST'])
def api_verify_fingerprint():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    template = data.get('template')

    user = AuthService.get_pending_user(session, token=token)
    if not user:
        return jsonify({'ok': False, 'error': 'Session expired.'}), 401

    ok, error, score = AuthService.verify_staff_fingerprint(
        user=user,
        probe_template=template,
        ip=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
    )

    if not ok:
        return jsonify({'ok': False, 'error': error, 'score': score}), 401

    AuthService.clear_pending_login(session)
    login_user(user, remember=False)
    session.permanent = True
    return jsonify({'ok': True, 'redirect': url_for('auth.dashboard')})


# ---------- API: enrol fingerprint (step 2b) ----------
@auth_bp.route('/api/login/enroll-fingerprint', methods=['POST'])
def api_enroll_fingerprint():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    template = data.get('template')
    quality = data.get('quality')

    user = AuthService.get_pending_user(session, token=token)
    if not user:
        return jsonify({'ok': False, 'error': 'Session expired.'}), 401

    ok, error = AuthService.enroll_staff_fingerprint(
        user=user, template=template, quality=quality,
        ip=request.remote_addr,
        user_agent=request.headers.get('User-Agent'),
    )
    if not ok:
        return jsonify({'ok': False, 'error': error}), 400

    AuthService.clear_pending_login(session)
    login_user(user, remember=False)
    session.permanent = True
    return jsonify({'ok': True, 'redirect': url_for('auth.dashboard')})


# ---------- MOCK endpoints (development only) ----------
@auth_bp.route('/api/mock-scan', methods=['POST'])
def api_mock_scan():
    """Dev-only: return a synthetic fingerprint template (no hardware needed)."""
    if not current_app.config.get('BIOMETRIC_MOCK_MODE'):
        return jsonify({'success': False, 'error': 'Mock mode disabled'}), 403

    import base64
    seed = (current_app.config.get('SECRET_KEY') or 'x') * 4
    template = (seed.encode() * 4)[:256]
    return jsonify({
        'success': True,
        'template': base64.b64encode(template).decode('utf-8'),
        'quality': 90,
        'mock': True,
    })


@auth_bp.route('/api/mock-enroll', methods=['POST'])
def api_mock_enroll():
    """Dev-only: return a synthetic enrolment template."""
    if not current_app.config.get('BIOMETRIC_MOCK_MODE'):
        return jsonify({'success': False, 'error': 'Mock mode disabled'}), 403

    import base64
    seed = (current_app.config.get('SECRET_KEY') or 'x') * 4
    template = (seed.encode() * 4)[:256]
    return jsonify({
        'success': True,
        'template': base64.b64encode(template).decode('utf-8'),
        'quality': 90,
        'samples_captured': current_app.config.get('BIOMETRIC_SAMPLES_PER_ENROLL', 3),
        'mock': True,
    })


# ---------- Logout / change password / dashboard ----------
@auth_bp.route('/logout')
@login_required
def logout():
    username = current_user.username
    logout_user()
    flash(f'You have been signed out, {username}.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        ok, error = AuthService.change_password(
            user=current_user,
            current_password=form.current_password.data,
            new_password=form.new_password.data,
        )
        if ok:
            flash('Password updated successfully.', 'success')
            return redirect(url_for('auth.dashboard'))
        flash(error, 'danger')
    return render_template('auth/change_password.html', form=form)


from datetime import datetime, time, timedelta, timezone
from flask import render_template
from flask_login import login_required, current_user
from sqlalchemy import func
from zoneinfo import ZoneInfo

# Import your database extensions and models here
from extensions import db
from models.inmate import Inmate
from models.visitor import Visitor
from models.visit import VisitLog
from models.cell import CellBlock  # Adjust model import if named differently

FACILITY_TIMEZONE = ZoneInfo('Africa/Kampala')


def _utc_bounds_for_facility_date(day):
    local_start = datetime.combine(day, time.min, tzinfo=FACILITY_TIMEZONE)
    local_end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=FACILITY_TIMEZONE)
    return (
        local_start.astimezone(timezone.utc).replace(tzinfo=None),
        local_end.astimezone(timezone.utc).replace(tzinfo=None),
    )


@auth_bp.route('/dashboard')
@login_required
def dashboard():
    from models.inmate import AdmissionEpisode
    from models.medical import MedicalRecord, WorkTransferLog
    from models.visitor import VisitorBlacklistEvent
    from services.rbac import has_permission, Permissions
    from services.visitor_service import VisitorService
    from sqlalchemy import or_

    today = datetime.now(FACILITY_TIMEZONE).date()
    role = getattr(current_user, 'role_name', 'User')
    recent_medical_records = []
    medical_record_count = 0
    pending_medical_submission_count = 0
    recent_blacklist_events = []
    blacklist_incident_counts = {}
    blacklisted_visitor_count = 0
    recent_work_transfers = []
    recent_prison_transfers = []
    total_work_transfers = 0
    total_prison_transfers = 0

    if has_permission(Permissions.INMATE_VIEW):
        total_work_transfers = WorkTransferLog.query.count()
        recent_work_transfers = WorkTransferLog.query.order_by(
            WorkTransferLog.checked_out_at.desc(),
            WorkTransferLog.transfer_id.desc(),
        ).limit(5).all()

        prison_transfers = AdmissionEpisode.query.filter(
            AdmissionEpisode.release_type == 'Transfer',
            AdmissionEpisode.release_date.isnot(None),
        )
        total_prison_transfers = prison_transfers.count()
        recent_prison_transfers = prison_transfers.order_by(
            AdmissionEpisode.release_date.desc(),
            AdmissionEpisode.episode_id.desc(),
        ).limit(5).all()

    if has_permission(Permissions.VISITOR_VIEW):
        recent_blacklist_events = VisitorBlacklistEvent.query.order_by(
            VisitorBlacklistEvent.event_at.desc(),
            VisitorBlacklistEvent.event_id.desc(),
        ).limit(8).all()
        event_visitor_ids = {
            event.visitor_id for event in recent_blacklist_events
        }
        if event_visitor_ids:
            blacklist_incident_counts = dict(
                db.session.query(
                    VisitorBlacklistEvent.visitor_id,
                    func.count(VisitorBlacklistEvent.event_id),
                )
                .filter(
                    VisitorBlacklistEvent.visitor_id.in_(event_visitor_ids),
                    VisitorBlacklistEvent.action == 'Blocked',
                )
                .group_by(VisitorBlacklistEvent.visitor_id)
                .all()
            )
        blacklisted_visitor_count = Visitor.query.filter_by(
            is_flagged=True
        ).count()

    if role == 'Medical Officer':
        visible_medical_records = MedicalRecord.query.filter(
            or_(
                MedicalRecord.approval_status == 'Approved',
                MedicalRecord.recorded_by == current_user.user_id,
            )
        )
        medical_record_count = visible_medical_records.count()
        pending_medical_submission_count = MedicalRecord.query.filter_by(
            recorded_by=current_user.user_id,
            approval_status='Pending',
        ).count()
        recent_medical_records = visible_medical_records.order_by(
            MedicalRecord.updated_at.desc(),
            MedicalRecord.created_at.desc(),
            MedicalRecord.record_id.desc(),
        ).limit(8).all()

    # 1. Inmate Metrics
    total_inmates_now = Inmate.query.filter_by(status='Active').count() if hasattr(Inmate, 'status') else Inmate.query.count()
    total_inmates_ever = Inmate.query.count()

    # 2. Visitor Metrics
    today_visit_start, tomorrow_visit_start = _utc_bounds_for_facility_date(today)
    total_daily_visits = VisitLog.query.filter(
        VisitLog.check_in_time >= today_visit_start,
        VisitLog.check_in_time < tomorrow_visit_start,
    ).count()
    total_visitors_ever = Visitor.query.count()

    # 3. Daily Movement Metrics
    total_daily_intakes = Inmate.query.filter(
        func.date(getattr(Inmate, 'admission_date', getattr(Inmate, 'created_at', None))) == today
    ).count()
    total_daily_releases = AdmissionEpisode.query.filter_by(
        release_date=today
    ).count()
    total_inmate_deaths = Inmate.query.filter_by(status='Deceased').count() if hasattr(Inmate, 'status') else 0

    # 4. Cell Blocks & Occupancy Calculations
    cell_blocks = CellBlock.query.all() if 'CellBlock' in globals() else []
    cell_occupancy_by_name = dict(
        db.session.query(Inmate.cell_block, func.count(Inmate.inmate_id))
        .filter(Inmate.status == 'Active', Inmate.cell_block.isnot(None))
        .group_by(Inmate.cell_block)
        .all()
    )
    total_capacity = sum(getattr(b, 'capacity', 0) for b in cell_blocks) or 1000
    total_occupied = total_inmates_now
    overall_capacity_pct = round((total_occupied / total_capacity) * 100, 1) if total_capacity > 0 else 0

    # 5. Weekly Trend Calculations for Chart.js
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    chart_labels = [d.strftime('%a') for d in days]
    
    chart_intakes = [
        Inmate.query.filter(func.date(getattr(Inmate, 'admission_date', getattr(Inmate, 'created_at', None))) == d).count()
        for d in days
    ]
    chart_releases = [
        AdmissionEpisode.query.filter_by(release_date=d).count()
        for d in days
    ]
    chart_visitors = [
        VisitLog.query.filter(
            VisitLog.check_in_time >= _utc_bounds_for_facility_date(d)[0],
            VisitLog.check_in_time < _utc_bounds_for_facility_date(d)[1],
        ).count()
        for d in days
    ]

    return render_template(
        'dashboard.html',
        role=role,
        total_inmates_now=total_inmates_now,
        total_inmates_ever=total_inmates_ever,
        total_daily_visits=total_daily_visits,
        total_visitors_ever=total_visitors_ever,
        total_daily_intakes=total_daily_intakes,
        total_daily_releases=total_daily_releases,
        total_inmate_deaths=total_inmate_deaths,
        total_occupied=total_occupied,
        total_capacity=total_capacity,
        overall_capacity_pct=overall_capacity_pct,
        cell_blocks=cell_blocks,
        cell_occupancy_by_name=cell_occupancy_by_name,
        chart_labels=chart_labels,
        chart_intakes=chart_intakes,
        chart_releases=chart_releases,
        chart_visitors=chart_visitors,
        recent_medical_records=recent_medical_records,
        medical_record_count=medical_record_count,
        pending_medical_submission_count=pending_medical_submission_count,
        recent_blacklist_events=recent_blacklist_events,
        blacklist_incident_counts=blacklist_incident_counts,
        blacklisted_visitor_count=blacklisted_visitor_count,
        permanent_blacklist_threshold=VisitorService.PERMANENT_BLACKLIST_THRESHOLD,
        can_view_visitor_blacklist=has_permission(Permissions.VISITOR_VIEW),
        can_view_inmate_transfers=has_permission(Permissions.INMATE_VIEW),
        recent_work_transfers=recent_work_transfers,
        total_work_transfers=total_work_transfers,
        recent_prison_transfers=recent_prison_transfers,
        total_prison_transfers=total_prison_transfers,
    )