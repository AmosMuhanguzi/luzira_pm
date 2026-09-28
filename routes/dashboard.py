from datetime import date, timedelta
from flask import render_template, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func

from extensions import db
from models.inmate import Inmate
from models.visitor import Visitor
from models.visit import VisitLog
from models.cell import CellBlock  # Adjust model import if named differently (e.g. Cell)

@main_bp.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    role = getattr(current_user, 'role', 'User')

    # 1. Inmates KPI Metrics
    total_inmates_now = Inmate.query.filter_by(status='Active').count() if hasattr(Inmate, 'status') else Inmate.query.count()
    total_inmates_ever = Inmate.query.count()

    # 2. Visitors KPI Metrics
    total_daily_visits = VisitLog.query.filter(
        func.date(getattr(VisitLog, 'check_in_time', getattr(VisitLog, 'created_at', None))) == today
    ).count() if hasattr(VisitLog, 'check_in_time') else 0
    total_visitors_ever = Visitor.query.count()

    # 3. Daily Intakes, Releases, Deaths
    total_daily_intakes = Inmate.query.filter(
        func.date(getattr(Inmate, 'admission_date', getattr(Inmate, 'created_at', None))) == today
    ).count()
    total_daily_releases = Inmate.query.filter(
        func.date(getattr(Inmate, 'release_date', None)) == today
    ).count() if hasattr(Inmate, 'release_date') else 0
    total_inmate_deaths = Inmate.query.filter_by(status='Deceased').count() if hasattr(Inmate, 'status') else 0

    # 4. Cell Blocks & Total Occupancy
    cell_blocks = CellBlock.query.all() if 'CellBlock' in globals() else []
    total_capacity = sum(getattr(b, 'capacity', 0) for b in cell_blocks) or 1000
    total_occupied = total_inmates_now
    overall_capacity_pct = round((total_occupied / total_capacity) * 100, 1) if total_capacity > 0 else 0

    # 5. Weekly Trend Data for Chart.js
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    chart_labels = [d.strftime('%a') for d in days]
    
    chart_intakes = [
        Inmate.query.filter(func.date(getattr(Inmate, 'admission_date', getattr(Inmate, 'created_at', None))) == d).count()
        for d in days
    ]
    chart_releases = [
        Inmate.query.filter(func.date(getattr(Inmate, 'release_date', None)) == d).count() if hasattr(Inmate, 'release_date') else 0
        for d in days
    ]
    chart_visitors = [
        VisitLog.query.filter(func.date(getattr(VisitLog, 'check_in_time', getattr(VisitLog, 'created_at', None))) == d).count()
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
        chart_labels=chart_labels,
        chart_intakes=chart_intakes,
        chart_releases=chart_releases,
        chart_visitors=chart_visitors
    )

# Modal JSON API endpoint for cell block inmates
@main_bp.route('/api/cells/<int:cell_id>/inmates')
@login_required
def get_cell_inmates(cell_id):
    cell = CellBlock.query.get_or_404(cell_id)
    inmates = Inmate.query.filter_by(cell_id=cell_id, status='Active').all() if hasattr(Inmate, 'cell_id') else []
    
    occupancy = len(inmates)
    capacity = getattr(cell, 'capacity', 1)
    pct = round((occupancy / capacity) * 100, 1) if capacity > 0 else 0

    return jsonify({
        'cell_name': getattr(cell, 'name', f'Block {cell_id}'),
        'occupancy': occupancy,
        'capacity': capacity,
        'percentage': pct,
        'inmates': [
            {
                'inmate_number': getattr(i, 'inmate_number', f'LZR-{i.inmate_id}'),
                'full_name': getattr(i, 'full_name', f'{i.first_name} {i.last_name}'),
                'crime': getattr(i, 'crime', getattr(i, 'offense', 'N/A')),
                'intake_date': getattr(i, 'admission_date', getattr(i, 'created_at', date.today())).strftime('%Y-%m-%d')
            }
            for i in inmates
        ]
    })