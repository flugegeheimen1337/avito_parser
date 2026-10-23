from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.dates import parse_avito_date
from app.db import init_db, make_engine
from app.decide import decide
from app.fetch import FetchResult, backoff_seconds, classify_response, fetch_search
from app.parser import ParsedItem, parse_price, parse_search_html
from app.service import Service
from app.urls import normalize_search_url
from app.web import create_app

FIXTURES = Path(__file__).resolve().parents[1] / "app" / "fixtures"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
SEARCH = "https://www.avito.ru/moskva/telefony?q=iphone"


@pytest.fixture
async def service(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db",
        fetch_live=False,
        run_worker=False,
        allow_fixture_poll=True,
        bot_token="",
        request_gap_seconds=0,
    )
    engine = make_engine(settings.database_url)
    await init_db(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    built = Service(factory, settings)
    await built.open()
    try:
        yield built
    finally:
        await built.close()
        await engine.dispose()


def test_relative_and_absolute_dates() -> None:
    assert parse_avito_date("только что", NOW) == NOW
    assert parse_avito_date("5 минут назад", NOW) == NOW - timedelta(minutes=5)
    assert parse_avito_date("час назад", NOW) == NOW - timedelta(hours=1)
    assert parse_avito_date("2 часа назад", NOW) == NOW - timedelta(hours=2)
    assert parse_avito_date("сегодня в 14:05", NOW) == datetime(2026, 10, 23, 11, 5, tzinfo=timezone.utc)
    assert parse_avito_date("вчера в 18:00", NOW) == datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)
    assert parse_avito_date("1 января 2020 в 12:00", NOW) == datetime(2020, 1, 1, 9, 0, tzinfo=timezone.utc)
    assert parse_avito_date("не дата", NOW) is None


def test_normalize_search_url_forces_newest_sort() -> None:
    url = normalize_search_url("http://m.avito.ru/moskva/telefony?q=iphone&utm_source=tg&s=1")
    assert url.startswith("https://www.avito.ru/moskva/telefony?")
    assert "utm_source" not in url
    assert "s=104" in url


def test_normalize_search_url_rejects_item_and_other_hosts() -> None:
    with pytest.raises(ValueError):
        normalize_search_url("https://www.avito.ru/moskva/telefony/iphone_13_128_gb_3456789012")
    with pytest.raises(ValueError):
        normalize_search_url("https://www.avito.ru/3456789012")
    with pytest.raises(ValueError):
        normalize_search_url("https://example.com/moskva/telefony")


def test_parser_reads_public_card_markers() -> None:
    items = parse_search_html(FIXTURES.joinpath("baseline.html").read_text(encoding="utf-8"), NOW)
    assert [item.avito_id for item in items] == ["1001", "1002"]
    assert items[0].price == 45000
    assert items[0].title == "iPhone 13, 128 ГБ"
    assert items[0].location == "Москва, р-н Тверской"
    assert items[0].url.endswith("/iphone_13_128_gb_1001")
    assert parse_price("Бесплатно") is None


def test_decide_keeps_old_bumped_ads_and_excluded_titles() -> None:
    fresh = _item("1", "iPhone 14", 60000, NOW)
    old = _item("2", "iPhone 11", 15000, datetime(2020, 1, 1, tzinfo=timezone.utc))
    parts = _item("3", "iPhone на запчасти", 20000, NOW)
    pricey = _item("4", "iPhone 15 Pro", 150000, NOW)
    outcomes = {
        item.item.avito_id: item.action
        for item in decide(
            [fresh, old, parts, pricey],
            baseline_done=True,
            watch_created_at=NOW,
            seen={},
            include_words=[],
            exclude_words=["запчасти"],
            price_min=10000,
            price_max=100000,
            notify_price_change=True,
        )
    }
    assert outcomes == {"1": "new", "2": "silent", "3": "silent", "4": "silent"}


def test_classify_response_prefers_catalog_over_block_words() -> None:
    assert classify_response(429, "<html>captcha</html>") == "blocked"
    assert classify_response(200, '<div data-marker="catalog-serp">captcha word in script</div>') == "ok"
    assert classify_response(200, "<html>empty</html>") == "broken"
    assert backoff_seconds(1) == 60
    assert backoff_seconds(6) == 1800


async def test_fetch_search_marks_block_without_parsing_items() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="<html><body>captcha</body></html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_search(client, SEARCH)
    assert result.kind == "blocked"
    assert result.status == 429


async def test_baseline_then_new_and_price(service: Service) -> None:
    watch, created = await service.add_watch(
        0,
        SEARCH,
        name="Телефоны",
        exclude_words="запчасти, битый",
        price_min=10000,
        price_max=100000,
    )
    assert created is True
    again, created_again = await service.add_watch(0, SEARCH)
    assert created_again is False
    assert again.id == watch.id

    baseline = await service.poll_fixture(watch.id, "baseline")
    assert "Уведомлений нет" in baseline
    stored = await service.get_watch_view(watch.id)
    assert stored is not None and stored.baseline_done and stored.seen_count == 2
    assert await service.notifications() == []

    updated = await service.poll_fixture(watch.id, "update")
    assert updated == "Новых: 1. Смена цены: 1."
    notes = await service.notifications()
    texts = [note.text for note in notes]
    assert any("iPhone 14, 128 ГБ" in text for text in texts)
    assert any("было 45 000 ₽" in text and "стало 42 000 ₽" in text for text in texts)
    assert not any("запчасти" in text for text in texts)
    assert not any("iPhone 11" in text for text in texts)
    assert not any("iPhone 15 Pro" in text for text in texts)

    repeat = await service.poll_fixture(watch.id, "update")
    assert repeat == "Новых: 0. Смена цены: 0."
    assert len(await service.notifications()) == 2


async def test_block_pauses_and_does_not_refetch(service: Service) -> None:
    watch, _created = await service.add_watch(0, SEARCH)
    now = datetime.now(timezone.utc)
    await service.apply_fetch(watch.id, FetchResult("blocked", 429, "<html>captcha</html>", ""), now=now)
    paused = await service.get_watch_view(watch.id)
    assert paused is not None
    assert paused.baseline_done is False
    assert paused.consecutive_failures == 1
    assert paused.paused_until == now + timedelta(seconds=60)
    notes = await service.notifications()
    assert len(notes) == 1 and notes[0].kind == "status"

    await service.apply_fetch(watch.id, FetchResult("blocked", 429, "<html>captcha</html>", ""), now=now)
    assert len(await service.notifications()) == 1
    paused = await service.get_watch_view(watch.id)
    assert paused is not None and paused.consecutive_failures == 2

    service.settings.fetch_live = True

    class Boom:
        async def get(self, url: str) -> httpx.Response:
            raise AssertionError(url)

    service.client = Boom()  # type: ignore[assignment]
    assert await service.poll_due() is False


async def test_web_flow(service: Service) -> None:
    app = create_app(service, service.settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True

        rejected = await client.post("/watches", data={"url": "https://example.com/x"}, follow_redirects=True)
        assert "avito.ru" in rejected.text

        created = await client.post(
            "/watches",
            data={
                "url": SEARCH,
                "name": "Телефоны",
                "exclude_words": "запчасти",
                "price_min": "10000",
                "price_max": "100000",
            },
            follow_redirects=True,
        )
        assert "Слежка «Телефоны» сохранена" in created.text
        assert "ждёт первый снимок" in created.text

        snapshot = await client.post(
            "/watches/1/fixture",
            data={"fixture_name": "baseline"},
            follow_redirects=True,
        )
        assert "Первый снимок сохранён" in snapshot.text

        changed = await client.post(
            "/watches/1/fixture",
            data={"fixture_name": "update"},
            follow_redirects=True,
        )
        feed = changed.text.split('id="feed"', 1)[1]
        assert "iPhone 14, 128 ГБ" in feed
        assert "было 45 000 ₽" in feed
        assert "iPhone 13 на запчасти" not in feed
        assert "iPhone 11, 64 ГБ" not in feed


def _item(avito_id: str, title: str, price: int, published_at: datetime) -> ParsedItem:
    return ParsedItem(
        avito_id=avito_id,
        title=title,
        price=price,
        url=f"https://www.avito.ru/moskva/telefony/item_{avito_id}",
        location="Москва",
        published_at=published_at,
        image_url=None,
        raw_date=None,
    )
