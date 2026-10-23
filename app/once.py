from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

import httpx

from app.fetch import USER_AGENT, fetch_search
from app.parser import parse_search_html
from app.urls import normalize_search_url


async def _main(raw_url: str) -> int:
    url = normalize_search_url(raw_url)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9", "Accept": "text/html"},
    ) as client:
        result = await fetch_search(client, url)
    print(url)
    print(f"kind={result.kind} status={result.status} {result.detail}")
    if result.kind == "ok":
        items = parse_search_html(result.html, datetime.now(timezone.utc))
        print(f"items={len(items)}")
        for item in items[:10]:
            print(f"{item.avito_id}\t{item.price}\t{item.raw_date or ''}\t{item.title}")
    return 0 if result.kind == "ok" else 1


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m app.once <avito search url>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_main(sys.argv[1])))


if __name__ == "__main__":
    main()
