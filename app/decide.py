from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from app.parser import ParsedItem
from app.urls import word_list

# Cards older than the watch (plus a short grace) are bumped ads, not new posts.
FRESH_GRACE = timedelta(minutes=10)

Action = Literal["baseline", "new", "price", "silent"]


@dataclass(frozen=True)
class Outcome:
    item: ParsedItem
    action: Action
    old_price: int | None = None


def decide(
    items: list[ParsedItem],
    *,
    baseline_done: bool,
    watch_created_at: datetime,
    seen: dict[str, int | None],
    include_words: list[str],
    exclude_words: list[str],
    price_min: int | None,
    price_max: int | None,
    notify_price_change: bool,
) -> list[Outcome]:
    outcomes: list[Outcome] = []
    page_ids: set[str] = set()
    for item in items:
        if item.avito_id in page_ids:
            continue
        page_ids.add(item.avito_id)
        if not baseline_done:
            outcomes.append(Outcome(item, "baseline"))
            continue
        if item.avito_id not in seen:
            action: Action = "new" if _passes(item, include_words, exclude_words, price_min, price_max) and _is_fresh(item, watch_created_at) else "silent"
            outcomes.append(Outcome(item, action))
            continue
        old_price = seen[item.avito_id]
        price_changed = (
            notify_price_change
            and old_price is not None
            and item.price is not None
            and old_price != item.price
            and _passes(item, include_words, exclude_words, price_min, price_max)
        )
        outcomes.append(Outcome(item, "price" if price_changed else "silent", old_price if price_changed else None))
    return outcomes


def parse_word_field(raw: str) -> list[str]:
    return word_list(raw)


def _passes(
    item: ParsedItem,
    include_words: list[str],
    exclude_words: list[str],
    price_min: int | None,
    price_max: int | None,
) -> bool:
    title = item.title.casefold()
    if any(word.casefold() in title for word in exclude_words):
        return False
    if include_words and not all(word.casefold() in title for word in include_words):
        return False
    if item.price is None:
        return price_min is None and price_max is None
    if price_min is not None and item.price < price_min:
        return False
    if price_max is not None and item.price > price_max:
        return False
    return True


def _is_fresh(item: ParsedItem, watch_created_at: datetime) -> bool:
    if item.published_at is None:
        return True
    created = watch_created_at
    if created.tzinfo is None:
        from datetime import timezone

        created = created.replace(tzinfo=timezone.utc)
    published = item.published_at
    if published.tzinfo is None:
        from datetime import timezone

        published = published.replace(tzinfo=timezone.utc)
    return published >= created - FRESH_GRACE
