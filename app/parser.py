from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.dates import parse_avito_date

_ITEM_ID = re.compile(r"_(\d{6,})$")


class ParsedItem:
    def __init__(
        self,
        avito_id: str,
        title: str,
        price: int | None,
        url: str,
        location: str | None,
        published_at: datetime | None,
        image_url: str | None,
        raw_date: str | None,
    ) -> None:
        self.avito_id = avito_id
        self.title = title
        self.price = price
        self.url = url
        self.location = location
        self.published_at = published_at
        self.image_url = image_url
        self.raw_date = raw_date


def parse_search_html(html: str, now: datetime) -> list[ParsedItem]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[ParsedItem] = []
    seen: set[str] = set()
    for node in soup.select('[data-marker="item"]'):
        item = _parse_node(node, now)
        if item is None or item.avito_id in seen:
            continue
        seen.add(item.avito_id)
        items.append(item)
    return items


def page_has_catalog(html: str) -> bool:
    return 'data-marker="item"' in html or 'data-marker="catalog-serp"' in html


def _parse_node(node, now: datetime) -> ParsedItem | None:  # type: ignore[no-untyped-def]
    title_node = node.select_one('[data-marker="item-title"]')
    title = _text(title_node)
    href = title_node.get("href") if title_node is not None else None
    if not title or not href:
        return None
    url = urljoin("https://www.avito.ru", href)
    avito_id = str(node.get("data-item-id") or "") or _id_from_url(url)
    if not avito_id.isdigit():
        return None
    price = _price(node)
    date_node = node.select_one('[data-marker="item-date"]')
    raw_date = _text(date_node) or None
    location_node = node.select_one('[data-marker="item-address"], [data-marker="item-location"]')
    image = node.select_one("img")
    image_url = None
    if image is not None:
        image_url = image.get("src") or image.get("data-src")
        if image_url and image_url.startswith("//"):
            image_url = "https:" + image_url
    return ParsedItem(
        avito_id=avito_id,
        title=title[:1000],
        price=price,
        url=url[:2000],
        location=(_text(location_node) or None),
        published_at=parse_avito_date(raw_date, now),
        image_url=image_url[:2000] if image_url else None,
        raw_date=raw_date[:120] if raw_date else None,
    )


def _price(node) -> int | None:  # type: ignore[no-untyped-def]
    meta = node.select_one('meta[itemprop="price"]')
    if meta is not None and meta.get("content"):
        parsed = parse_price(str(meta.get("content")))
        if parsed is not None:
            return parsed
    price_node = node.select_one('[data-marker="item-price"]')
    if price_node is None:
        return None
    return parse_price(_text(price_node))


def parse_price(raw: str | None) -> int | None:
    if not raw:
        return None
    lowered = raw.casefold()
    if "бесплатно" in lowered or "не указан" in lowered:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    return int(digits)


def _text(node) -> str:  # type: ignore[no-untyped-def]
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).replace("\xa0", " ").split())


def _id_from_url(url: str) -> str:
    path = url.split("?", 1)[0].rstrip("/").split("/")[-1]
    match = _ITEM_ID.search(path)
    return match.group(1) if match else ""
