from datetime import date, timedelta

MAX_CHART_DAYS = 92


def current_week_dates(reference_date=None):
    reference_date = reference_date or date.today()
    week_start = reference_date - timedelta(days=reference_date.weekday())
    return [week_start + timedelta(days=offset) for offset in range(7)]


def format_week_range(week_dates):
    if not week_dates:
        return ''
    first, last = week_dates[0], week_dates[-1]
    return f"{first.strftime('%a %d/%m/%Y')} – {last.strftime('%a %d/%m/%Y')}"


def resolve_chart_dates(from_text, to_text, today):
    """Return (dates, is_current_week, error). Defaults to the current Mon–Sun week."""
    current = current_week_dates(today)
    if not (from_text or to_text):
        return current, True, None

    try:
        start = date.fromisoformat(from_text) if from_text else current[0]
        end = date.fromisoformat(to_text) if to_text else current[-1]
    except ValueError:
        return current, True, 'Enter valid dates; showing the current week.'

    if start > end:
        return current, True, 'The "from" date must not be after the "to" date; showing the current week.'
    if (end - start).days + 1 > MAX_CHART_DAYS:
        return current, True, f'Choose a range of at most {MAX_CHART_DAYS} days; showing the current week.'

    dates = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return dates, dates == current, None


def chart_label(day, span):
    return day.strftime('%a %d/%m') if span <= 7 else day.strftime('%d/%m')
