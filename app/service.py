from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.decide import decide
from app.fetch import USER_AGENT, FetchResult, backoff_seconds, failure_text, fetch_search
from app.models import Notification, SeenItem, User, Watch, utcnow
from app.parser import parse_search_html
from app.text import message_new, message_price, message_status
from app.urls import default_watch_name, normalize_search_url, normalize_words, word_list

logger = logging.getLogger(__name__)
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_NAMES = {"baseline": "baseline.html", "update": "update.html"}


@dataclass
class WatchView:
    id: int
    name: str
    source_url: str
    enabled: bool
    baseline_done: bool
    last_error: str | None
    last_http_status: int | None
    paused_until: datetime | None
    next_poll_at: datetime | None
    last_success_at: datetime | None
    consecutive_failures: int
    exclude_words: str
    include_words: str
    price_min: int | None
    price_max: int | None
    seen_count: int
    interval_seconds: int


@dataclass
class NoteView:
    id: int
    watch_id: int
    kind: str
    text: str
    created_at: datetime
    sent_at: datetime | None
    lag_seconds: int | None


@dataclass
class ApplyReport:
    baseline: bool
    new_ids: list[str]
    price_ids: list[str]
    stored: int


class Service:
    def __init__(self, factory: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.factory = factory
        self.settings = settings
        self.client: httpx.AsyncClient | None = None
        self.bot: object | None = None
        self._lock = asyncio.Lock()
        self._last_fetch = 0.0

    async def open(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.request_timeout_seconds),
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ru-RU,ru;q=0.9",
                "Accept": "text/html",
            },
        )

    async def close(self) -> None:
        client = self.client
        self.client = None
        close = getattr(client, "aclose", None)
        if close is not None:
            await close()

    async def add_watch(
        self,
        telegram_id: int,
        raw_url: str,
        name: str = "",
        include_words: str = "",
        exclude_words: str = "",
        price_min: int | None = None,
        price_max: int | None = None,
    ) -> tuple[WatchView, bool]:
        url = normalize_search_url(raw_url)
        if price_min is not None and price_max is not None and price_min > price_max:
            raise ValueError("Минимальная цена больше максимальной")
        clean_name = " ".join(name.split())[:200] or default_watch_name(url)
        include = normalize_words(include_words)
        exclude = normalize_words(exclude_words)
        async with self.factory() as session:
            async with session.begin():
                user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
                if user is None:
                    user = User(telegram_id=telegram_id)
                    session.add(user)
                    await session.flush()
                existing = await session.scalar(
                    select(Watch).where(Watch.user_id == user.id, Watch.source_url == url)
                )
                if existing is not None:
                    view = await self._view(session, existing)
                    return view, False
                now = utcnow()
                watch = Watch(
                    user_id=user.id,
                    name=clean_name,
                    source_url=url,
                    interval_seconds=max(45, self.settings.min_interval_seconds),
                    include_words=include,
                    exclude_words=exclude,
                    price_min=price_min,
                    price_max=price_max,
                    created_at=now,
                    next_poll_at=now,
                )
                session.add(watch)
                await session.flush()
                view = await self._view(session, watch)
                return view, True

    async def watch_views(self, telegram_id: int | None = None) -> list[WatchView]:
        async with self.factory() as session:
            stmt = select(Watch).order_by(Watch.id)
            if telegram_id is not None:
                stmt = stmt.join(User, User.id == Watch.user_id).where(User.telegram_id == telegram_id)
            watches = (await session.scalars(stmt)).all()
            return [await self._view(session, watch) for watch in watches]

    async def notifications(self, limit: int = 40) -> list[NoteView]:
        async with self.factory() as session:
            rows = (
                await session.scalars(select(Notification).order_by(Notification.id.desc()).limit(limit))
            ).all()
            return [_note_view(row) for row in rows]

    async def get_watch_view(self, watch_id: int) -> WatchView | None:
        async with self.factory() as session:
            watch = await session.get(Watch, watch_id)
            if watch is None:
                return None
            return await self._view(session, watch)

    async def set_enabled(self, watch_id: int, telegram_id: int | None, enabled: bool) -> str:
        async with self.factory() as session:
            async with session.begin():
                watch = await self._owned(session, watch_id, telegram_id)
                if watch is None:
                    return "Нет такой слежки"
                watch.enabled = enabled
                if enabled:
                    watch.paused_until = None
                    watch.next_poll_at = utcnow()
                    return f"Слежка «{watch.name}» снова включена"
                return f"Слежка «{watch.name}» на паузе"

    async def delete_watch(self, watch_id: int, telegram_id: int | None) -> str:
        async with self.factory() as session:
            async with session.begin():
                watch = await self._owned(session, watch_id, telegram_id)
                if watch is None:
                    return "Нет такой слежки"
                name = watch.name
                await session.execute(delete(Notification).where(Notification.watch_id == watch.id))
                await session.execute(delete(SeenItem).where(SeenItem.watch_id == watch.id))
                await session.delete(watch)
                return f"Слежка «{name}» удалена"

    async def rename(self, watch_id: int, telegram_id: int | None, name: str) -> str:
        clean = " ".join(name.split())[:200]
        if not clean:
            return "Нужно имя"
        async with self.factory() as session:
            async with session.begin():
                watch = await self._owned(session, watch_id, telegram_id)
                if watch is None:
                    return "Нет такой слежки"
                watch.name = clean
                return f"Слежка переименована в «{clean}»"

    async def set_words(
        self,
        watch_id: int,
        telegram_id: int | None,
        *,
        include_words: str | None = None,
        exclude_words: str | None = None,
    ) -> str:
        async with self.factory() as session:
            async with session.begin():
                watch = await self._owned(session, watch_id, telegram_id)
                if watch is None:
                    return "Нет такой слежки"
                if include_words is not None:
                    watch.include_words = normalize_words(include_words)
                if exclude_words is not None:
                    watch.exclude_words = normalize_words(exclude_words)
                return (
                    f"Слова обновлены. Должны быть: {watch.include_words or '—'}. "
                    f"Исключить: {watch.exclude_words or '—'}."
                )

    async def set_price(
        self,
        watch_id: int,
        telegram_id: int | None,
        price_min: int | None,
        price_max: int | None,
    ) -> str:
        if price_min is not None and price_max is not None and price_min > price_max:
            return "Минимальная цена больше максимальной"
        async with self.factory() as session:
            async with session.begin():
                watch = await self._owned(session, watch_id, telegram_id)
                if watch is None:
                    return "Нет такой слежки"
                watch.price_min = price_min
                watch.price_max = price_max
                return f"Цена: {_price_span(price_min, price_max)}"

    async def apply_html(
        self,
        watch_id: int,
        html: str,
        *,
        now: datetime | None = None,
        from_live: bool = False,
    ) -> ApplyReport:
        now = now or utcnow()
        items = parse_search_html(html, now)
        async with self.factory() as session:
            async with session.begin():
                watch = await session.get(Watch, watch_id)
                if watch is None:
                    raise LookupError(watch_id)
                rows = (
                    await session.scalars(select(SeenItem).where(SeenItem.watch_id == watch.id))
                ).all()
                seen = {row.avito_id: row.price for row in rows}
                by_id = {row.avito_id: row for row in rows}
                was_baseline = watch.baseline_done
                outcomes = decide(
                    items,
                    baseline_done=was_baseline,
                    watch_created_at=watch.created_at,
                    seen=seen,
                    include_words=word_list(watch.include_words),
                    exclude_words=word_list(watch.exclude_words),
                    price_min=watch.price_min,
                    price_max=watch.price_max,
                    notify_price_change=watch.notify_price_change,
                )
                new_ids: list[str] = []
                price_ids: list[str] = []
                for outcome in outcomes:
                    item = outcome.item
                    row = by_id.get(item.avito_id)
                    if row is None:
                        row = SeenItem(
                            watch_id=watch.id,
                            avito_id=item.avito_id,
                            title=item.title,
                            price=item.price,
                            url=item.url,
                            location=item.location[:300] if item.location else None,
                            published_at=item.published_at,
                            image_url=item.image_url,
                            raw_date=item.raw_date,
                            first_seen_at=now,
                            last_seen_at=now,
                        )
                        session.add(row)
                        by_id[item.avito_id] = row
                    else:
                        row.title = item.title
                        row.price = item.price
                        row.url = item.url
                        row.location = item.location[:300] if item.location else None
                        row.published_at = item.published_at
                        row.image_url = item.image_url
                        row.raw_date = item.raw_date
                        row.last_seen_at = now
                    if outcome.action == "new":
                        text, lag = message_new(item, watch.name, now)
                        session.add(
                            Notification(
                                watch_id=watch.id,
                                avito_id=item.avito_id,
                                kind="new",
                                text=text,
                                created_at=now,
                                lag_seconds=lag,
                            )
                        )
                        new_ids.append(item.avito_id)
                    elif outcome.action == "price" and outcome.old_price is not None:
                        session.add(
                            Notification(
                                watch_id=watch.id,
                                avito_id=item.avito_id,
                                kind="price",
                                text=message_price(item, watch.name, outcome.old_price),
                                created_at=now,
                            )
                        )
                        price_ids.append(item.avito_id)
                watch.baseline_done = True
                if from_live:
                    recovered = watch.last_error is not None
                    watch.last_polled_at = now
                    watch.last_success_at = now
                    watch.last_http_status = 200
                    watch.last_error = None
                    watch.consecutive_failures = 0
                    watch.paused_until = None
                    jitter = random.randint(0, 5)
                    watch.next_poll_at = now + timedelta(seconds=watch.interval_seconds + jitter)
                    if recovered:
                        session.add(
                            Notification(
                                watch_id=watch.id,
                                kind="status",
                                text=message_status(watch.name, "Поиск снова открывается."),
                                created_at=now,
                            )
                        )
                return ApplyReport(
                    baseline=not was_baseline,
                    new_ids=new_ids,
                    price_ids=price_ids,
                    stored=len(outcomes),
                )

    async def apply_fetch(
        self,
        watch_id: int,
        result: FetchResult,
        now: datetime | None = None,
    ) -> ApplyReport | None:
        now = now or utcnow()
        if result.kind == "ok":
            return await self.apply_html(watch_id, result.html, now=now, from_live=True)
        await self._record_failure(watch_id, result, now)
        return None

    async def poll_fixture(self, watch_id: int, name: str) -> str:
        if not self.settings.allow_fixture_poll:
            return "Проверка на сохранённой выдаче выключена"
        filename = FIXTURE_NAMES.get(name)
        if filename is None:
            return "Неизвестный пример"
        html = (FIXTURE_DIR / filename).read_text(encoding="utf-8")
        try:
            report = await self.apply_html(watch_id, html, from_live=False)
        except LookupError:
            return "Нет такой слежки"
        return _report_text(report)

    async def poll_watch(self, watch_id: int) -> str:
        view = await self.get_watch_view(watch_id)
        if view is None:
            return "Нет такой слежки"
        if not view.enabled:
            return "Слежка выключена"
        if self.client is None:
            return "Клиент ещё не запущен"
        await self._gap()
        result = await fetch_search(self.client, view.source_url)
        try:
            report = await self.apply_fetch(watch_id, result)
        except LookupError:
            return "Нет такой слежки"
        if result.kind != "ok" or report is None:
            return failure_text(result)
        return _report_text(report)

    async def poll_due(self) -> bool:
        if not self.settings.fetch_live or self.client is None:
            return False
        async with self.factory() as session:
            now = utcnow()
            watch = await session.scalar(
                select(Watch)
                .where(
                    Watch.enabled.is_(True),
                    Watch.next_poll_at <= now,
                    or_(Watch.paused_until.is_(None), Watch.paused_until <= now),
                )
                .order_by(Watch.next_poll_at)
                .limit(1)
            )
            if watch is None:
                return False
            watch_id = watch.id
            url = watch.source_url
        await self._gap()
        result = await fetch_search(self.client, url)
        await self.apply_fetch(watch_id, result)
        logger.info("polled watch %s -> %s %s", watch_id, result.kind, result.status)
        return True

    async def deliver_once(self) -> int:
        bot = self.bot
        if bot is None:
            return 0
        sent = 0
        async with self.factory() as session:
            async with session.begin():
                rows = (
                    await session.execute(
                        select(Notification, User.telegram_id)
                        .join(Watch, Watch.id == Notification.watch_id)
                        .join(User, User.id == Watch.user_id)
                        .where(
                            Notification.sent_at.is_(None),
                            Notification.attempts < 5,
                            User.telegram_id != 0,
                        )
                        .order_by(Notification.id)
                        .limit(20)
                    )
                ).all()
                for note, telegram_id in rows:
                    try:
                        await bot.send_message(telegram_id, note.text)  # type: ignore[attr-defined]
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # Telegram and network errors stay in the row.
                        logger.warning("telegram send failed: %s", exc)
                        note.attempts += 1
                        if note.attempts >= 5:
                            note.sent_at = utcnow()
                            note.delivery_error = "не удалось отправить в Telegram"
                        continue
                    note.sent_at = utcnow()
                    sent += 1
        return sent

    async def _record_failure(self, watch_id: int, result: FetchResult, now: datetime) -> None:
        text = failure_text(result)
        async with self.factory() as session:
            async with session.begin():
                watch = await session.get(Watch, watch_id)
                if watch is None:
                    return
                watch.consecutive_failures += 1
                watch.last_error = text[:500]
                watch.last_http_status = result.status
                watch.last_polled_at = now
                delay = backoff_seconds(watch.consecutive_failures)
                watch.paused_until = now + timedelta(seconds=delay)
                watch.next_poll_at = watch.paused_until
                if watch.consecutive_failures == 1:
                    session.add(
                        Notification(
                            watch_id=watch.id,
                            kind="status",
                            text=message_status(watch.name, text),
                            created_at=now,
                        )
                    )

    async def _gap(self) -> None:
        gap = self.settings.request_gap_seconds
        async with self._lock:
            loop = asyncio.get_running_loop()
            wait = self._last_fetch + gap - loop.time()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_fetch = loop.time()

    async def _owned(self, session: AsyncSession, watch_id: int, telegram_id: int | None) -> Watch | None:
        watch = await session.get(Watch, watch_id)
        if watch is None:
            return None
        if telegram_id is None:
            return watch
        user = await session.get(User, watch.user_id)
        if user is None or user.telegram_id != telegram_id:
            return None
        return watch

    async def _view(self, session: AsyncSession, watch: Watch) -> WatchView:
        seen_count = await session.scalar(
            select(func.count()).select_from(SeenItem).where(SeenItem.watch_id == watch.id)
        )
        return WatchView(
            id=watch.id,
            name=watch.name,
            source_url=watch.source_url,
            enabled=watch.enabled,
            baseline_done=watch.baseline_done,
            last_error=watch.last_error,
            last_http_status=watch.last_http_status,
            paused_until=watch.paused_until,
            next_poll_at=watch.next_poll_at,
            last_success_at=watch.last_success_at,
            consecutive_failures=watch.consecutive_failures,
            exclude_words=watch.exclude_words,
            include_words=watch.include_words,
            price_min=watch.price_min,
            price_max=watch.price_max,
            seen_count=int(seen_count or 0),
            interval_seconds=watch.interval_seconds,
        )


def _note_view(row: Notification) -> NoteView:
    return NoteView(
        id=row.id,
        watch_id=row.watch_id,
        kind=row.kind,
        text=row.text,
        created_at=row.created_at,
        sent_at=row.sent_at,
        lag_seconds=row.lag_seconds,
    )


def _price_span(price_min: int | None, price_max: int | None) -> str:
    if price_min is None and price_max is None:
        return "без ограничений"
    left = "…" if price_min is None else str(price_min)
    right = "…" if price_max is None else str(price_max)
    return f"{left}–{right} ₽"


def _report_text(report: ApplyReport) -> str:
    if report.baseline:
        return f"Первый снимок сохранён: {report.stored} объявлений. Уведомлений нет."
    return f"Новых: {len(report.new_ids)}. Смена цены: {len(report.price_ids)}."
