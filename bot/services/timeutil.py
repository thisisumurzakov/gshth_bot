from datetime import date, datetime, timedelta, timezone

# В Узбекистане нет перехода на летнее время, поэтому хватает фиксированного смещения
# (и не нужен пакет tzdata в образе).
TASHKENT = timezone(timedelta(hours=5), "Asia/Tashkent")

DATETIME_FORMAT = "%d.%m.%Y %H:%M"
DATE_FORMAT = "%d.%m.%Y"


def parse_local_datetime(text: str) -> datetime | None:
    """'30.09.2026 18:00' (время Ташкента) → aware UTC datetime."""
    try:
        local = datetime.strptime(text.strip(), DATETIME_FORMAT)
    except ValueError:
        return None
    return local.replace(tzinfo=TASHKENT).astimezone(timezone.utc)


def format_local_datetime(value: datetime) -> str:
    return value.astimezone(TASHKENT).strftime(DATETIME_FORMAT)


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def parse_birth_date(text: str, today: date) -> date | None:
    """ДД.ММ.ГГГГ (допускаются разделители . / -), возраст от 10 до 100 лет."""
    cleaned = text.strip().replace("/", ".").replace("-", ".")
    try:
        value = datetime.strptime(cleaned, DATE_FORMAT).date()
    except ValueError:
        return None
    age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    return value if 10 <= age <= 100 else None
