from __future__ import annotations

import asyncio
import logging

import uvicorn
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings, get_settings
from app.db import ensure_sqlite_parent, init_db, make_engine
from app.service import Service
from app.web import create_app
from app.worker import delivery_loop, worker_loop

logger = logging.getLogger(__name__)


async def run(settings: Settings | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = settings or get_settings()
    ensure_sqlite_parent(settings.database_url)
    engine = make_engine(settings.database_url)
    await init_db(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = Service(factory, settings)
    await service.open()
    app = create_app(service, settings)
    server = uvicorn.Server(
        uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info")
    )
    tasks: list[asyncio.Task[None]] = [asyncio.create_task(delivery_loop(service), name="delivery")]
    if settings.run_worker and settings.fetch_live:
        tasks.append(asyncio.create_task(worker_loop(service), name="worker"))
    if settings.telegram_enabled:
        from app.bot import run_bot

        tasks.append(asyncio.create_task(run_bot(service, settings), name="bot"))
    logger.info("local control http://%s:%s", settings.host, settings.port)
    try:
        await server.serve()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.close()
        await engine.dispose()
