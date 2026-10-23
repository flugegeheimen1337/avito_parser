from __future__ import annotations

import asyncio
import logging
import re

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app.config import Settings
from app.service import Service

logger = logging.getLogger(__name__)
URL_RE = re.compile(r"https?://(?:www\.|m\.)?avito\.ru/\S+", re.IGNORECASE)

START = (
    "Пришлите ссылку на поиск Авито.\n"
    "Любую категорию можно выбрать в каталоге на пульте или прислать готовую ссылку поиска.\n"
    "Первый ответ запоминается молча. Потом приходят новые объявления и смена цены.\n"
    "\n"
    "/list — слежки\n"
    "/pause 1 — пауза\n"
    "/resume 1 — снова включить\n"
    "/exclude 1 запчасти, битый\n"
    "/price 1 10000 80000\n"
    "/price 1 clear — убрать вилку\n"
    "/name 1 Телефоны Москва\n"
    "/delete 1 — удалить"
)


def build_router(service: Service) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(START)

    @router.message(Command("help"))
    async def help_command(message: Message) -> None:
        await message.answer(START)

    @router.message(Command("list"))
    async def list_watches(message: Message) -> None:
        owner = _owner(message)
        watches = await service.watch_views(owner)
        if not watches:
            await message.answer("Слежек нет. Пришлите ссылку на поиск Авито.")
            return
        lines = []
        for watch in watches:
            state = _state(watch.enabled, watch.baseline_done, watch.last_error)
            lines.append(f"{watch.id}. {watch.name} — {state}\n{watch.source_url}")
        await message.answer("\n\n".join(lines))

    @router.message(Command("pause"))
    async def pause(message: Message) -> None:
        watch_id = _one_id(message)
        if watch_id is None:
            await message.answer("Формат: /pause 1")
            return
        await message.answer(await service.set_enabled(watch_id, _owner(message), False))

    @router.message(Command("resume"))
    async def resume(message: Message) -> None:
        watch_id = _one_id(message)
        if watch_id is None:
            await message.answer("Формат: /resume 1")
            return
        await message.answer(await service.set_enabled(watch_id, _owner(message), True))

    @router.message(Command("delete"))
    async def delete(message: Message) -> None:
        watch_id = _one_id(message)
        if watch_id is None:
            await message.answer("Формат: /delete 1")
            return
        await message.answer(await service.delete_watch(watch_id, _owner(message)))

    @router.message(Command("name"))
    async def rename(message: Message) -> None:
        watch_id, rest = _id_and_rest(message)
        if watch_id is None or not rest:
            await message.answer("Формат: /name 1 Телефоны Москва")
            return
        await message.answer(await service.rename(watch_id, _owner(message), rest))

    @router.message(Command("exclude"))
    async def exclude(message: Message) -> None:
        watch_id, rest = _id_and_rest(message)
        if watch_id is None:
            await message.answer("Формат: /exclude 1 запчасти, битый")
            return
        await message.answer(
            await service.set_words(watch_id, _owner(message), exclude_words=rest or "")
        )

    @router.message(Command("price"))
    async def price(message: Message) -> None:
        parts = (message.text or "").split()
        if len(parts) == 3 and parts[1].isdigit() and parts[2].casefold() == "clear":
            text = await service.set_price(int(parts[1]), _owner(message), None, None)
            await message.answer(text)
            return
        if len(parts) != 4 or not parts[1].isdigit():
            await message.answer("Формат: /price 1 10000 80000")
            return
        try:
            price_min = _money(parts[2])
            price_max = _money(parts[3])
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await message.answer(await service.set_price(int(parts[1]), _owner(message), price_min, price_max))

    @router.message(F.text)
    async def add_from_url(message: Message) -> None:
        match = URL_RE.search(message.text or "")
        if match is None:
            await message.answer("Пришлите ссылку на поиск Авито или /help.")
            return
        try:
            watch, created = await service.add_watch(_owner(message), match.group(0))
        except ValueError as exc:
            await message.answer(str(exc))
            return
        if created:
            await message.answer(
                f"Слежка «{watch.name}» сохранена.\n"
                "В ссылке включена сортировка «сначала новые».\n"
                f"{watch.source_url}\n\n"
                "Первый ответ запомнится молча."
            )
            return
        await message.answer(f"Такая ссылка уже есть: «{watch.name}».")

    return router


async def run_bot(service: Service, settings: Settings) -> None:
    bot = Bot(token=settings.bot_token)
    service.bot = bot
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(service))
    try:
        await dispatcher.start_polling(bot)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("telegram bot stopped")
    finally:
        service.bot = None
        await bot.session.close()


def _owner(message: Message) -> int:
    user = message.from_user
    return int(user.id) if user is not None else 0


def _one_id(message: Message) -> int | None:
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    return int(parts[1])


def _id_and_rest(message: Message) -> tuple[int | None, str]:
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        return None, ""
    return int(parts[1]), parts[2] if len(parts) > 2 else ""


def _money(raw: str) -> int:
    if not raw.isdigit():
        raise ValueError("Цена должна быть целым числом в рублях")
    value = int(raw)
    if value > 1_000_000_000:
        raise ValueError("Слишком большая цена")
    return value


def _state(enabled: bool, baseline_done: bool, last_error: str | None) -> str:
    if not enabled:
        return "выключена"
    if last_error:
        return "пауза"
    if not baseline_done:
        return "ждёт первый снимок"
    return "следит"

