from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, TypeDecorator, event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator[datetime]):
    """Store UTC datetimes and always return timezone-aware values."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | str | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def make_engine(url: str) -> AsyncEngine:
    kwargs: dict[str, object] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    engine = create_async_engine(url, **kwargs)
    if url.startswith("sqlite"):
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
    return engine


def _sqlite_pragmas(connection: object, _record: object) -> None:
    cursor = connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def ensure_sqlite_parent(url: str) -> None:
    if not url.startswith("sqlite") or ":memory:" in url:
        return
    marker = "///"
    if marker not in url:
        return
    path = url.split(marker, 1)[1]
    if not path or path == ":memory:":
        return
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)


async def init_db(engine: AsyncEngine) -> None:
    from app.models import Base as ModelBase

    async with engine.begin() as connection:
        await connection.run_sync(ModelBase.metadata.create_all)
