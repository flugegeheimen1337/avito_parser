from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Public catalog query used by Avito search pages for "newest first".
DATE_SORT = "104"
DROP_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "yclid",
    "gclid",
    "context",
}


def normalize_search_url(raw: str) -> str:
    text = raw.strip()
    if not text:
        raise ValueError("Нужна ссылка на поиск avito.ru")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Нужна ссылка на поиск avito.ru")
    host = parsed.netloc.lower()
    if host.startswith("m."):
        host = host[2:]
    if host == "avito.ru":
        host = "www.avito.ru"
    if host != "www.avito.ru":
        raise ValueError("Нужна ссылка на поиск avito.ru")
    path = parsed.path or "/"
    last = path.rstrip("/").split("/")[-1]
    if last.isdigit() or _is_item_slug(last):
        raise ValueError("Это страница объявления. Нужна ссылка на поиск со списком.")
    if path.strip("/") == "":
        raise ValueError("Нужна ссылка на поиск с категорией или запросом, не главная страница.")
    pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in DROP_PARAMS and key != "s"
    ]
    pairs.append(("s", DATE_SORT))
    url = urlunparse(("https", host, path, "", urlencode(pairs), ""))
    if len(url) > 2000:
        raise ValueError("Слишком длинная ссылка")
    return url


def default_watch_name(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[1]} · {parts[0]}"[:200]
    if parts:
        return parts[0][:200]
    return "поиск"


def normalize_words(raw: str) -> str:
    parts: list[str] = []
    for chunk in raw.replace(";", ",").split(","):
        word = " ".join(chunk.split())
        if word:
            parts.append(word)
    return ", ".join(parts)[:1000]


def word_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _is_item_slug(segment: str) -> bool:
    if "_" not in segment:
        return False
    tail = segment.rsplit("_", 1)[-1]
    return tail.isdigit() and len(tail) >= 6
