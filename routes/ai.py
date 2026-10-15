# routes/ai.py
from datetime import datetime
import json
from flask import (Blueprint, current_app, render_template, redirect, url_for,
                   flash, request, send_file)
from flask_login import login_required, current_user

from extensions import csrf, db
from services.rbac import require_permission, Permissions
from models.ai import AIAnalysisLog
from models.visitor import Visitor
from models.inmate import Inmate


ai_bp = Blueprint('ai', __name__, url_prefix='/ai')
csrf.exempt(ai_bp)


# ---------- Dashboard ----------
@ai_bp.route('/')
@login_required
@require_permission(Permissions.AI_VIEW_DASHBOARD)
def dashboard():
    # Aggregate stats
    total_visitors   = Visitor.query.count()
    flagged_visitors = Visitor.query.filter_by(anomaly_flag=True).count()
    high_risk_inmates = Inmate.query.filter(Inmate.risk_level.in_(['High','Critical'])).count()
    current_population = Inmate.query.filter_by(status='Active').count()

    # Latest forecast
    from models.ai import PopulationForecast
    latest_forecast = (PopulationForecast.query
                       .order_by(PopulationForecast.forecast_id.desc())
                       .first())

    # Recent alerts
    alerts = (AIAnalysisLog.query
              .filter(AIAnalysisLog.severity.in_(['High','Critical','Medium']))
              .order_by(AIAnalysisLog.analysis_id.desc())
              .limit(10).all())

    # Risk distribution across inmates
    risk_counts = {'Low': 0, 'Medium': 0, 'High': 0, 'Critical': 0}
    rows = (db.session.query(Inmate.risk_level, db.func.count(Inmate.inmate_id))
            .filter(Inmate.status == 'Active')
            .group_by(Inmate.risk_level).all())
    for lvl, cnt in rows:
        if lvl in risk_counts:
            risk_counts[lvl] = cnt

    return render_template('ai/dashboard.html',
                           total_visitors=total_visitors,
                           flagged_visitors=flagged_visitors,
                           high_risk_inmates=high_risk_inmates,
                           current_population=current_population,
                           facility_capacity=current_app.config.get('FACILITY_CAPACITY', 30000),
                           latest_forecast=latest_forecast,
                           alerts=alerts,
                           risk_counts=risk_counts)


@ai_bp.route('/charts/visitor-frequency.png')
@login_required
@require_permission(Permissions.AI_VIEW_DASHBOARD)
def visitor_frequency_chart():
    from services.ai_visitor import VisitorAnomalyDetector

    chart = VisitorAnomalyDetector.weekly_activity_chart()
    return send_file(
        chart,
        mimetype='image/png',
        download_name='visitor-weekly-frequency.png',
        max_age=0,
    )


# ---------- Alerts list ----------
@ai_bp.route('/alerts')
@login_required
@require_permission(Permissions.AI_VIEW_ALERTS)
def alerts():
    status = request.args.get('status', 'unreviewed')
    page   = request.args.get('page', 1, type=int)

    q = AIAnalysisLog.query
    if status == 'unreviewed':
        q = q.filter_by(is_reviewed=False)
    elif status == 'reviewed':
        q = q.filter_by(is_reviewed=True)

    pagination = q.order_by(AIAnalysisLog.analysis_id.desc()) \
                  .paginate(page=page, per_page=20, error_out=False)

    return render_template('ai/alerts.html',
                           pagination=pagination, alerts=pagination.items,
                           status=status)


# ---------- Alert detail + review ----------
@ai_bp.route('/alerts/<int:alert_id>')
@login_required
@require_permission(Permissions.AI_VIEW_ALERTS)
def alert_detail(alert_id):
    alert = AIAnalysisLog.query.get_or_404(alert_id)
    alert_details = None
    if alert.detailed_result:
        try:
            alert_details = json.loads(alert.detailed_result)
        except json.JSONDecodeError:
            alert_details = None

    target = None
    if alert.target_entity == 'Visitor' and alert.target_id:
        target = Visitor.query.get(alert.target_id)
    elif alert.target_entity == 'Inmate' and alert.target_id:
        target = Inmate.query.get(alert.target_id)

    return render_template(
        'ai/alert_detail.html',
        alert=alert,
        target=target,
        alert_details=alert_details,
    )


@ai_bp.route('/alerts/<int:alert_id>/review', methods=['POST'])
@login_required
@require_permission(Permissions.AI_REVIEW_ALERTS)
def review_alert(alert_id):
    alert = AIAnalysisLog.query.get_or_404(alert_id)
    alert.is_reviewed  = True
    alert.reviewed_by  = current_user.user_id
    alert.reviewed_at  = datetime.utcnow()
    alert.review_notes = (request.form.get('notes') or '').strip() or None
    alert.action_taken = (request.form.get('action') or '').strip() or None
    alert.action_taken_by = current_user.user_id
    alert.action_taken_at = datetime.utcnow()
    db.session.commit()
    flash(f'Alert #{alert_id} reviewed.', 'success')
    return redirect(url_for('ai.alerts'))


# ---------- Manual triggers ----------
@ai_bp.route('/train-model', methods=['POST'])
@login_required
@require_permission(Permissions.AI_VIEW_DASHBOARD)
def train_model():
    from services.ai_visitor import VisitorAnomalyDetector
    r = VisitorAnomalyDetector.train_model()
    if r['success']:
        flash(f'Model trained on {r["samples"]} samples.', 'success')
    else:
        flash(f'Training failed: {r.get("error")}', 'warning')
    return redirect(url_for('ai.dashboard'))


@ai_bp.route('/run/visitor-analysis', methods=['POST'])
@login_required
@require_permission(Permissions.AI_VIEW_DASHBOARD)
def run_visitor_analysis():
    from services.ai_visitor import VisitorAnomalyDetector
    r = VisitorAnomalyDetector.analyze_all()
    if r.get('success'):
        flash(f"Analyzed {r['analyzed']} visitors · {r['flagged']} flagged.",
              'info')
    else:
        flash(f"Failed: {r.get('error')}", 'warning')
    return redirect(url_for('ai.dashboard'))


@ai_bp.route('/run/population-forecast', methods=['POST'])
@login_required
@require_permission(Permissions.AI_VIEW_DASHBOARD)
def run_population_forecast():
    from services.ai_population import PopulationForecaster
    r = PopulationForecaster.forecast(horizon_days=30)
    if r.get('success'):
        flash(f"Forecast: {r['predicted_population']} inmates "
              f"({r['utilization_percent']}% capacity) · risk {r['overcrowding_risk']}.",
              'info')
    else:
        flash('Forecast failed.', 'warning')
    return redirect(url_for('ai.dashboard'))


@ai_bp.route('/run/inmate-risk', methods=['POST'])
@login_required
@require_permission(Permissions.AI_VIEW_DASHBOARD)
def run_inmate_risk():
    from services.ai_inmate_risk import InmateRiskScorer
    r = InmateRiskScorer.score_all()
    flash(f"Risk-scored {r.get('scored', 0)} inmates.", 'info')
    return redirect(url_for('ai.dashboard'))


# ---------- Reports (print-friendly) ----------
@ai_bp.route('/reports/weekly')
@login_required
@require_permission(Permissions.AI_VIEW_DASHBOARD)
def weekly_report():
    from collections import Counter
    from datetime import date, timedelta
    from models.ai import PopulationForecast
    from models.inmate import Inmate
    from models.visitor import Visitor, VisitLog

    today = date.today()
    default_start = today - timedelta(days=today.weekday())
    default_end = default_start + timedelta(days=6)
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')

    try:
        report_start = date.fromisoformat(from_date) if from_date else default_start
        report_end = date.fromisoformat(to_date) if to_date else default_end
        if report_end < report_start:
            raise ValueError
    except ValueError:
        flash('Choose a valid report date range where the end date is not before the start date.', 'danger')
        return redirect(url_for('ai.weekly_report'))

    period_start = datetime.combine(report_start, datetime.min.time())
    period_end = datetime.combine(
        report_end + timedelta(days=1),
        datetime.min.time(),
    )

    inmates = Inmate.query.filter(
        Inmate.created_at >= period_start,
        Inmate.created_at < period_end,
    ).all()
    visitors = Visitor.query.filter(
        Visitor.created_at >= period_start,
        Visitor.created_at < period_end,
    ).all()
    visits = VisitLog.query.filter(
        VisitLog.check_in_time >= period_start,
        VisitLog.check_in_time < period_end,
    ).all()
    alerts = AIAnalysisLog.query.filter(
        AIAnalysisLog.analysis_timestamp >= period_start,
        AIAnalysisLog.analysis_timestamp < period_end,
    ).all()

    risk_levels = ('Low', 'Medium', 'High', 'Critical')
    risk_counts = {
        level: Inmate.query.filter(
            Inmate.status == 'Active',
            Inmate.risk_level == level,
        ).count()
        for level in risk_levels
    }
    visitor_risk_counts = {
        level: Visitor.query.filter(Visitor.risk_rating == level).count()
        for level in risk_levels
    }

    visit_type_counts = Counter(
        (visit.visit_type or 'Unspecified') for visit in visits
    )
    alert_severity_counts = Counter(
        (alert.severity or 'Info') for alert in alerts
    )
    alert_type_counts = Counter(
        (alert.analysis_type or 'Other') for alert in alerts
    )
    daily_visits = [
        sum(1 for visit in visits if visit.check_in_time.date() == day)
        for day in (
            report_start + timedelta(days=i)
            for i in range((report_end - report_start).days + 1)
        )
    ]
    flagged_visits = sum(1 for visit in visits if visit.anomaly_flag)
    reviewed_alerts = sum(1 for alert in alerts if alert.is_reviewed)
    high_risk_alerts = sum(
        1 for alert in alerts if alert.severity in ('High', 'Critical')
    )
    active_population = Inmate.query.filter_by(status='Active').count()
    latest_forecast = (
        PopulationForecast.query
        .order_by(PopulationForecast.forecast_id.desc())
        .first()
    )

    metrics = [
        {'label': 'New inmates admitted', 'value': len(inmates)},
        {'label': 'New visitors registered', 'value': len(visitors)},
        {'label': 'Visits logged', 'value': len(visits)},
        {'label': 'AI alerts generated', 'value': len(alerts)},
        {'label': 'High/Critical alerts', 'value': high_risk_alerts},
        {'label': 'Active population', 'value': active_population},
    ]

    return render_template(
        'ai/reports_weekly.html',
        report_start=report_start,
        report_end=report_end,
        today=today,
        metrics=metrics,
        risk_counts=risk_counts,
        visitor_risk_counts=visitor_risk_counts,
        visit_type_counts=dict(
            sorted(visit_type_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        alert_severity_counts={
            severity: alert_severity_counts.get(severity, 0)
            for severity in ('Critical', 'High', 'Medium', 'Low', 'Info')
        },
        alert_type_counts=dict(
            sorted(alert_type_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        daily_labels=[
            (report_start + timedelta(days=i)).strftime('%d %b')
            for i in range((report_end - report_start).days + 1)
        ],
        daily_visits=daily_visits,
        flagged_visits=flagged_visits,
        reviewed_alerts=reviewed_alerts,
        unreviewed_alerts=len(alerts) - reviewed_alerts,
        active_population=active_population,
        latest_forecast=latest_forecast,
    )
