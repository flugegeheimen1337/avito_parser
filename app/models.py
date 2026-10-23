from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Watch(Base):
    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(2000))
    interval_seconds: Mapped[int] = mapped_column(Integer, default=45)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    exclude_words: Mapped[str] = mapped_column(String(1000), default="")
    include_words: Mapped[str] = mapped_column(String(1000), default="")
    price_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notify_price_change: Mapped[bool] = mapped_column(Boolean, default=True)
    baseline_done: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_polled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    next_poll_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    paused_until: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SeenItem(Base):
    __tablename__ = "seen_items"
    __table_args__ = (UniqueConstraint("watch_id", "avito_id", name="uq_seen_watch_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), index=True)
    avito_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(1000))
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(String(2000))
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    raw_date: Mapped[str | None] = mapped_column(String(120), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), index=True)
    avito_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    lag_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    delivery_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
