from datetime import timedelta

DAYS_PER_UNIT = {'month': 30, 'year': 360}


def parse_sentence(value, unit):
    """Return (number, unit) or None when the inputs are missing or invalid."""
    unit = (unit or '').strip().lower().rstrip('s')
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if unit not in DAYS_PER_UNIT or number <= 0:
        return None
    return number, unit


def sentence_label(number, unit):
    text = f'{number:g}'
    return f"{text} {unit}{'' if number == 1 else 's'}"


def expected_release(start_date, number, unit):
    """Sentence in days (1 month = 30, 1 year = 360) minus one tenth remission."""
    total_days = number * DAYS_PER_UNIT[unit]
    served_days = round(total_days) - round(total_days / 10)
    return {
        'total_days': round(total_days),
        'served_days': served_days,
        'served_months': round(served_days / 30, 1),
        'release_date': start_date + timedelta(days=served_days),
    }
