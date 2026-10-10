from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from services.report_service import build_report, month_segments, period_bounds
from services.rbac import require_role


reports_bp = Blueprint('reports', __name__, url_prefix='/admin/reports')

REPORT_TYPES = {'weekly', 'monthly', 'quarterly', 'yearly'}


@reports_bp.route('/')
@login_required
@require_role('System Administrator')
def index():
    today = date.today()
    report_type = request.args.get('type', 'weekly')
    if report_type not in REPORT_TYPES:
        abort(400, description='Choose a valid report period.')

    try:
        year = int(request.args.get('year', today.year))
        if not 1 <= year <= 9998:
            raise ValueError
        month = int(request.args.get('month', today.month))
        if not 1 <= month <= 12:
            raise ValueError

        if report_type == 'weekly':
            default_start = today - timedelta(days=today.weekday())
            start = date.fromisoformat(request.args.get('from_date', default_start.isoformat()))
            end = date.fromisoformat(request.args.get('to_date', (default_start + timedelta(days=6)).isoformat()))
            if end < start:
                raise ValueError
            quarter = None
        elif report_type == 'monthly':
            start, end = period_bounds(year, month)
            quarter = None
        elif report_type == 'quarterly':
            quarter = int(request.args.get('quarter', ((today.month - 1) // 3) + 1))
            if not 1 <= quarter <= 4:
                raise ValueError
            first_month = (quarter - 1) * 3 + 1
            start, _ = period_bounds(year, first_month)
            _, end = period_bounds(year, first_month + 2)
        else:
            quarter = None
            start, end = date(year, 1, 1), date(year, 12, 31)
    except (ValueError, OverflowError):
        flash('Enter a valid report period and date range.', 'danger')
        return redirect(url_for('reports.index', type=report_type))

    if report_type == 'monthly':
        segments = month_segments(start.year, start.month)
    elif report_type in {'quarterly', 'yearly'}:
        first_month = 1 if report_type == 'yearly' else (quarter - 1) * 3 + 1
        month_count = 12 if report_type == 'yearly' else 3
        segments = [
            period_bounds(year, segment_month)
            for segment_month in range(first_month, first_month + month_count)
        ]
    else:
        segments = []

    report = build_report(report_type, start, end, segments)
    if report_type == 'quarterly':
        report['title'] = f'Quarter {quarter} Report'
    return render_template(
        'admin/reports.html',
        report=report,
        report_type=report_type,
        year=year,
        month=month,
        quarter=quarter,
        month_names=[
            (month_number, date(year, month_number, 1).strftime('%B'))
            for month_number in range(1, 13)
        ],
        current_date=today,
    )
