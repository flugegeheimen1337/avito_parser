from __future__ import annotations

import asyncio
import logging

from app.service import Service

logger = logging.getLogger(__name__)


async def worker_loop(service: Service) -> None:
    while True:
        did = False
        try:
            did = await service.poll_due()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("poll failed")
        await asyncio.sleep(1 if did else 2)


async def delivery_loop(service: Service) -> None:
    while True:
        try:
            await service.deliver_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("delivery failed")
        await asyncio.sleep(2)
