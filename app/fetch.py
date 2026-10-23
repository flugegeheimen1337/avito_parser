from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

from app.parser import page_has_catalog

USER_AGENT = "AvitoWatch/0.1 (saved-search monitor; stops on 429)"
BLOCK_STATUSES = {401, 403, 429, 503}
Kind = Literal["ok", "blocked", "missing", "broken", "temporary"]


class HttpGet(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


@dataclass(frozen=True)
class FetchResult:
    kind: Kind
    status: int | None
    html: str
    detail: str = ""


def classify_response(status: int, html: str) -> Kind:
    if page_has_catalog(html):
        return "ok"
    if status in BLOCK_STATUSES:
        return "blocked"
    if status == 404:
        return "missing"
    lowered = html.casefold()
    if any(marker in lowered for marker in ("captcha", "доступ ограничен", "qrator")):
        return "blocked"
    if status == 200:
        return "broken"
    return "temporary"


def backoff_seconds(failures: int) -> int:
    if failures < 1:
        return 60
    return min(1800, 60 * (2 ** (failures - 1)))


def failure_text(result: FetchResult) -> str:
    status = str(result.status) if result.status is not None else (result.detail or "сеть")
    if result.kind == "blocked":
        return (
            f"Авито не отдал выдачу (ответ {status}). "
            "Слежка на паузе и повторит позже. Защиту не обходим."
        )
    if result.kind == "missing":
        return "Ссылка не открывается (404)."
    if result.kind == "broken":
        return "В странице нет списка объявлений. Возможно, изменилась вёрстка."
    detail = result.detail or status
    return f"Не удалось открыть поиск ({detail})."


async def fetch_search(client: HttpGet, url: str) -> FetchResult:
    try:
        response = await client.get(url)
    except httpx.TimeoutException:
        return FetchResult("temporary", None, "", "таймаут")
    except httpx.HTTPError as exc:
        return FetchResult("temporary", None, "", exc.__class__.__name__)
    html = response.text[:2_000_000]
    return FetchResult(classify_response(response.status_code, html), response.status_code, html)
