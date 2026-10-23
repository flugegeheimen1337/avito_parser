from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.parser import ParsedItem

MSK = ZoneInfo("Europe/Moscow")


def format_price(price: int | None) -> str:
    if price is None:
        return "цена не указана"
    return f"{price:,}".replace(",", " ") + " ₽"


def format_lag(published_at: datetime | None, now: datetime) -> tuple[str, int | None]:
    if published_at is None:
        return "время на карточке не указано", None
    seconds = int((now - published_at).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        human = "меньше минуты"
    elif seconds < 3600:
        human = f"{seconds // 60} мин"
    elif seconds < 86400:
        human = f"{seconds // 3600} ч"
    else:
        human = f"{seconds // 86400} д"
    return human, seconds


def message_new(item: ParsedItem, watch_name: str, now: datetime) -> tuple[str, int | None]:
    lag_human, lag_seconds = format_lag(item.published_at, now)
    lines = ["Новое объявление", item.title, format_price(item.price)]
    if item.location:
        lines.append(item.location)
    if item.raw_date:
        lines.append(item.raw_date)
    lines.append(f"Слежка: {watch_name}")
    lines.append(f"От времени на карточке: {lag_human}")
    lines.append(item.url)
    return "\n".join(lines), lag_seconds


def message_price(item: ParsedItem, watch_name: str, old_price: int) -> str:
    lines = [
        "Цена изменилась",
        item.title,
        f"было {format_price(old_price)}",
        f"стало {format_price(item.price)}",
        item.url,
        f"Слежка: {watch_name}",
    ]
    return "\n".join(lines)


def message_status(watch_name: str, text: str) -> str:
    return f"{watch_name}\n{text}"


def fmt_msk(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MSK).strftime("%d.%m %H:%M") + " МСК"
