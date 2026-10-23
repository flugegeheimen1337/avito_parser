from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

UNITS = {
    "секунду": "seconds",
    "секунды": "seconds",
    "секунд": "seconds",
    "минуту": "minutes",
    "минуты": "minutes",
    "минут": "minutes",
    "час": "hours",
    "часа": "hours",
    "часов": "hours",
    "день": "days",
    "дня": "days",
    "дней": "days",
    "неделю": "weeks",
    "недели": "weeks",
    "недель": "weeks",
}

_RELATIVE = re.compile(
    r"(?:(\d+)\s+)?"
    r"(секунду|секунды|секунд|минуту|минуты|минут|час|часа|часов|"
    r"день|дня|дней|неделю|недели|недель)\s+назад"
)
_CLOCK = re.compile(r"(сегодня|вчера)(?:\s+в)?\s+(\d{1,2}):(\d{2})")
_ABSOLUTE = re.compile(
    r"(\d{1,2})\s+([а-яё]+)"
    r"(?:\s+(\d{4}))?"
    r"(?:(?:\s+в)?\s+(\d{1,2}):(\d{2}))?"
)


def parse_avito_date(raw: str | None, now: datetime) -> datetime | None:
    if raw is None:
        return None
    text = " ".join(raw.replace("\xa0", " ").replace(",", " ").split()).casefold()
    if not text:
        return None
    now = _as_utc(now)
    local = now.astimezone(MSK)

    if text in {"только что", "несколько секунд назад"}:
        return now

    relative = _RELATIVE.fullmatch(text)
    if relative:
        amount = int(relative.group(1) or "1")
        return now - timedelta(**{UNITS[relative.group(2)]: amount})

    clock = _CLOCK.fullmatch(text)
    if clock:
        day = local.date()
        if clock.group(1) == "вчера":
            day -= timedelta(days=1)
        return _at(day, int(clock.group(2)), int(clock.group(3)))

    absolute = _ABSOLUTE.fullmatch(text)
    if absolute is None:
        return None
    month = MONTHS.get(absolute.group(2))
    if month is None:
        return None
    year = int(absolute.group(3) or local.year)
    hour = int(absolute.group(4) or 0)
    minute = int(absolute.group(5) or 0)
    try:
        stamped = _at(date(year, month, int(absolute.group(1))), hour, minute)
    except ValueError:
        return None
    if absolute.group(3) is None and stamped > now + timedelta(days=2):
        try:
            stamped = _at(date(year - 1, month, int(absolute.group(1))), hour, minute)
        except ValueError:
            return None
    return stamped


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _at(day: date, hour: int, minute: int) -> datetime:
    if hour > 23 or minute > 59:
        raise ValueError
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK)
    return local.astimezone(timezone.utc)
