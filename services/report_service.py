import calendar
import json
from datetime import date, datetime, time, timedelta

from sqlalchemy import case, distinct, func

from extensions import db
from models.audit import AuditEvent
from models.inmate import AdmissionEpisode, Inmate
from models.medical import DisciplinaryLog, EscapeAttemptLog, MedicalRecord, WorkTransferLog
from models.visit import VisitLog
from models.visitor import VisitorBlacklistEvent


def period_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def month_segments(year, month):
    month_start, month_end = period_bounds(year, month)
    segments = []
    cursor = month_start
    while cursor <= month_end:
        week_start = max(month_start, cursor - timedelta(days=cursor.weekday()))
        week_end = min(month_end, cursor + timedelta(days=6 - cursor.weekday()))
        segments.append((week_start, week_end))
        cursor = week_end + timedelta(days=1)
    return segments


def _date_count(model, column, start, end, *filters):
    return (
        db.session.query(func.count())
        .select_from(model)
        .filter(column >= start, column <= end, *filters)
        .scalar()
        or 0
    )


def _timestamp_bounds(start, end):
    return datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)


def _timestamp_count(model, column, start, end, *filters):
    start_at, end_at = _timestamp_bounds(start, end)
    return (
        db.session.query(func.count())
        .select_from(model)
        .filter(column >= start_at, column < end_at, *filters)
        .scalar()
        or 0
    )


def _recorded_deaths(start, end):
    dated_ids = {
        row[0]
        for row in db.session.query(Inmate.inmate_id).filter(
            Inmate.date_of_death.isnot(None)
        )
    }
    deaths = {
        row[0]
        for row in db.session.query(Inmate.inmate_id).filter(
            Inmate.date_of_death >= start, Inmate.date_of_death <= end
        )
    }

    start_at, end_at = _timestamp_bounds(start, end)
    events = AuditEvent.query.with_entities(
        AuditEvent.entity_id,
        AuditEvent.event_type,
        AuditEvent.event_description,
        AuditEvent.new_values,
    ).filter(
        AuditEvent.event_timestamp >= start_at,
        AuditEvent.event_timestamp < end_at,
        AuditEvent.entity_type == 'Inmate',
    ).all()

    unmatched_death_events = 0
    for entity_id, event_type, description, new_values in events:
        try:
            values = json.loads(new_values) if new_values else {}
        except (TypeError, json.JSONDecodeError):
            values = {}
        status = values.get('status', '') if isinstance(values, dict) else ''
        searchable_text = f'{event_type or ""} {description or ""}'.lower()
        if str(status).lower() == 'deceased' or any(
            marker in searchable_text for marker in ('death', 'deceased')
        ):
            if entity_id is None:
                unmatched_death_events += 1
            elif entity_id not in dated_ids:
                deaths.add(entity_id)
    return len(deaths) + unmatched_death_events


def undated_death_count():
    return (
        db.session.query(func.count())
        .select_from(Inmate)
        .filter(Inmate.status == 'Deceased', Inmate.date_of_death.is_(None))
        .scalar()
        or 0
    )


def _activity_breakdown(start, end):
    start_at, end_at = _timestamp_bounds(start, end)
    rows = (
        db.session.query(
            AuditEvent.event_category,
            AuditEvent.event_type,
            func.count(AuditEvent.event_id),
        )
        .filter(
            AuditEvent.event_timestamp >= start_at,
            AuditEvent.event_timestamp < end_at,
        )
        .group_by(AuditEvent.event_category, AuditEvent.event_type)
        .order_by(AuditEvent.event_category, AuditEvent.event_type)
        .all()
    )
    return [
        {
            'category': category or 'Uncategorized',
            'activity': activity or 'Unspecified',
            'count': count,
        }
        for category, activity, count in rows
    ]


def summarize_period(start, end):
    start_at, end_at = _timestamp_bounds(start, end)
    visits = VisitLog.query.with_entities(
        func.count(VisitLog.visit_id),
        func.count(distinct(VisitLog.visitor_id)),
        func.count(distinct(VisitLog.inmate_id)),
        func.coalesce(
            func.sum(case((VisitLog.anomaly_flag.is_(True), 1), else_=0)),
            0,
        ),
    ).filter(
        VisitLog.check_in_time >= start_at,
        VisitLog.check_in_time < end_at,
    ).one()

    metrics = [
        ('Inmate intakes', _date_count(
            AdmissionEpisode, AdmissionEpisode.admission_date, start, end
        )),
        ('Inmate deaths recorded', _recorded_deaths(start, end)),
        ('Visits', visits[0] or 0),
        ('Unique visitors', visits[1] or 0),
        ('Inmates visited', visits[2] or 0),
        ('Flagged visits', visits[3] or 0),
        ('Blocked visitors', _timestamp_count(
            VisitorBlacklistEvent,
            VisitorBlacklistEvent.event_at,
            start,
            end,
            VisitorBlacklistEvent.action == 'Blocked',
        )),
        ('Total inmate transfers', _date_count(
            AdmissionEpisode,
            AdmissionEpisode.release_date,
            start,
            end,
            AdmissionEpisode.release_type == 'Transfer',
        )),
        ('Other inmate releases', _date_count(
            AdmissionEpisode,
            AdmissionEpisode.release_date,
            start,
            end,
            AdmissionEpisode.release_type.notin_(('Transfer', 'Death')),
        )),
        ('Medical records', _date_count(
            MedicalRecord, MedicalRecord.record_date, start, end
        )),
        ('Disciplinary incidents', _date_count(
            DisciplinaryLog, DisciplinaryLog.incident_date, start, end
        )),
        ('Escape attempts', _date_count(
            EscapeAttemptLog, EscapeAttemptLog.incident_date, start, end
        )),
        ('Temporary work movements', _timestamp_count(
            WorkTransferLog, WorkTransferLog.checked_out_at, start, end
        )),
    ]
    activities = _activity_breakdown(start, end)
    return {
        'metrics': [{'label': label, 'value': value} for label, value in metrics],
        'activities': activities,
        'total_audit_events': sum(row['count'] for row in activities),
    }


def build_report(report_type, start, end, segments):
    labels = {
        'weekly': 'Weekly Report',
        'monthly': 'Monthly Report',
        'quarterly': 'Quarterly Report',
        'yearly': 'Yearly Report',
    }
    breakdown = []
    for index, (segment_start, segment_end) in enumerate(segments, start=1):
        label = f'Week {index}' if report_type == 'monthly' else segment_start.strftime('%B')
        breakdown.append({
            'label': label,
            'start': segment_start,
            'end': segment_end,
            **summarize_period(segment_start, segment_end),
        })

    undated = undated_death_count()
    death_note = (
        'Deaths are counted by the recorded date of death on each inmate record.'
    )
    if undated:
        death_note += (
            f' {undated} legacy deceased record(s) have no date of death and are '
            'not assigned to any reporting period until a date is recorded.'
        )

    return {
        'title': labels[report_type],
        'start': start,
        'end': end,
        **summarize_period(start, end),
        'breakdown': breakdown,
        'death_data_note': death_note,
    }