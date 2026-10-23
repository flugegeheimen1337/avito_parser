from __future__ import annotations

from html import escape
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings
from app.service import NoteView, Service, WatchView
from app.text import fmt_msk


def create_app(service: Service, settings: Settings) -> FastAPI:
    app = FastAPI(title="Avito watch")
    app.state.service = service
    app.state.settings = settings

    @app.get("/health")
    async def health() -> dict[str, object]:
        watches = await service.watch_views()
        return {
            "ok": True,
            "fetch_live": settings.fetch_live,
            "bot": settings.telegram_enabled,
            "watches": len(watches),
        }

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        watches = await service.watch_views()
        notes = await service.notifications()
        page = render_index(
            watches,
            notes,
            request.query_params.get("msg", ""),
            settings,
        )
        return HTMLResponse(page)

    @app.post("/watches")
    async def create_watch(
        url: str = Form(""),
        name: str = Form(""),
        include_words: str = Form(""),
        exclude_words: str = Form(""),
        price_min: str = Form(""),
        price_max: str = Form(""),
    ) -> RedirectResponse:
        try:
            low = _optional_price(price_min)
            high = _optional_price(price_max)
            watch, created = await service.add_watch(
                0,
                url,
                name=name,
                include_words=include_words,
                exclude_words=exclude_words,
                price_min=low,
                price_max=high,
            )
        except ValueError as exc:
            return _redirect(str(exc))
        if created:
            return _redirect(f"Слежка «{watch.name}» сохранена. Первый ответ запомнится молча.")
        return _redirect(f"Такая ссылка уже есть: «{watch.name}».")

    @app.post("/watches/{watch_id}/pause")
    async def pause(watch_id: int) -> RedirectResponse:
        return _redirect(await service.set_enabled(watch_id, None, False))

    @app.post("/watches/{watch_id}/resume")
    async def resume(watch_id: int) -> RedirectResponse:
        return _redirect(await service.set_enabled(watch_id, None, True))

    @app.post("/watches/{watch_id}/delete")
    async def remove(watch_id: int) -> RedirectResponse:
        return _redirect(await service.delete_watch(watch_id, None))

    @app.post("/watches/{watch_id}/fixture")
    async def fixture(watch_id: int, fixture_name: str = Form("")) -> RedirectResponse:
        return _redirect(await service.poll_fixture(watch_id, fixture_name))

    @app.post("/watches/{watch_id}/live")
    async def live(watch_id: int) -> RedirectResponse:
        return _redirect(await service.poll_watch(watch_id))

    return app


def render_index(
    watches: list[WatchView],
    notes: list[NoteView],
    message: str,
    settings: Settings,
) -> str:
    bot = "токен задан" if settings.telegram_enabled else "токена нет, лента только на этой странице"
    live = "включён" if settings.fetch_live else "выключен"
    flash = f"<p class='flash'>{escape(message)}</p>" if message else ""
    cards = "\n".join(_watch_card(watch, settings) for watch in watches) or "<p class='empty'>Слежек пока нет.</p>"
    feed = "\n".join(_note_card(note) for note in notes) or "<p class='empty'>Уведомлений пока нет.</p>"
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Слежка Авито</title>
  <style>
    body {{ margin: 0; background: #f4f1ea; color: #1d1b18; font: 16px/1.45 "Segoe UI", sans-serif; }}
    main {{ max-width: 880px; margin: 0 auto; padding: 32px 20px 72px; }}
    h1 {{ font-size: 28px; margin: 0 0 8px; }}
    h2 {{ font-size: 18px; margin: 28px 0 12px; }}
    .lead, .meta {{ color: #5c564c; }}
    .flash {{ background: #fff7d6; border: 1px solid #ead98a; padding: 10px 12px; border-radius: 10px; }}
    form.card, article {{ background: #fff; border: 1px solid #e3ddd2; border-radius: 14px; padding: 16px; margin: 12px 0; }}
    label {{ display: block; margin-top: 12px; font-size: 13px; color: #5c564c; }}
    input {{ width: 100%; box-sizing: border-box; margin-top: 4px; padding: 8px 10px; border: 1px solid #d5cfc4; border-radius: 8px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    button {{ margin: 12px 8px 0 0; padding: 8px 12px; border-radius: 8px; border: 1px solid #1d1b18; background: #1d1b18; color: #fff; cursor: pointer; }}
    button.quiet {{ background: #fff; color: #1d1b18; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
    .actions form {{ margin: 0; }}
    .actions button {{ margin: 8px 0 0; }}
    .chip {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #eeeae3; font-size: 12px; }}
    .ok {{ background: #e4f3e6; }}
    .bad {{ background: #fde2e0; }}
    .wait {{ background: #fff1d6; }}
    pre {{ white-space: pre-wrap; font: inherit; margin: 8px 0 0; }}
    a {{ color: #1d4e89; }}
    .empty {{ color: #5c564c; }}
    @media (max-width: 700px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <h1>Слежка Авито</h1>
  <p class="lead">Ссылка поиска становится слежкой. Первый успешный ответ запоминается и не присылается. Дальше в ленту попадают новые объявления и смена цены. Если Авито отвечает отказом или капчей, слежка встаёт на паузу.</p>
  <p class="meta">Опрос Авито: {live}. Telegram: {bot}.</p>
  {flash}
  <form class="card" method="post" action="/watches">
    <label>Ссылка поиска<input name="url" required placeholder="https://www.avito.ru/moskva/telefony?q=iphone"></label>
    <label>Имя<input name="name" placeholder="Телефоны, Москва"></label>
    <div class="grid">
      <label>Должны быть в названии<input name="include_words" placeholder="iphone, 128"></label>
      <label>Исключить<input name="exclude_words" placeholder="запчасти, битый"></label>
      <label>Цена от, ₽<input name="price_min" inputmode="numeric"></label>
      <label>Цена до, ₽<input name="price_max" inputmode="numeric"></label>
    </div>
    <button type="submit">Сохранить слежку</button>
  </form>
  <h2>Слежки</h2>
  {cards}
  <h2>Уведомления</h2>
  <section id="feed">{feed}</section>
</main>
</body>
</html>"""


def _watch_card(watch: WatchView, settings: Settings) -> str:
    chip, css = _chip(watch)
    error = f"<p>{escape(watch.last_error)}</p>" if watch.last_error else ""
    fixtures = ""
    if settings.allow_fixture_poll:
        fixtures = f"""
        <form method="post" action="/watches/{watch.id}/fixture">
          <input type="hidden" name="fixture_name" value="baseline">
          <button class="quiet" type="submit">Снимок примера</button>
        </form>
        <form method="post" action="/watches/{watch.id}/fixture">
          <input type="hidden" name="fixture_name" value="update">
          <button class="quiet" type="submit">Новые в примере</button>
        </form>"""
    toggle = "pause" if watch.enabled else "resume"
    toggle_label = "Пауза" if watch.enabled else "Включить"
    span = _span(watch.price_min, watch.price_max)
    return f"""
    <article id="watch-{watch.id}">
      <span class="chip {css}">{chip}</span>
      <h3>{escape(watch.name)}</h3>
      <p><a href="{escape(watch.source_url)}">{escape(watch.source_url)}</a></p>
      <p class="meta">В выдаче запомнено: {watch.seen_count}. Интервал: {watch.interval_seconds} с.
      Следующий опрос: {escape(fmt_msk(watch.next_poll_at))}.
      Пауза до: {escape(fmt_msk(watch.paused_until))}.
      Цена: {escape(span)}. Исключить: {escape(watch.exclude_words or "—")}.</p>
      {error}
      <div class="actions">
      <form method="post" action="/watches/{watch.id}/{toggle}"><button class="quiet" type="submit">{toggle_label}</button></form>
      <form method="post" action="/watches/{watch.id}/live"><button class="quiet" type="submit">Проверить Авито один раз</button></form>
      {fixtures}
      <form method="post" action="/watches/{watch.id}/delete"><button class="quiet" type="submit">Удалить</button></form>
      </div>
    </article>"""


def _note_card(note: NoteView) -> str:
    label = {"new": "Новое", "price": "Цена", "status": "Статус"}.get(note.kind, note.kind)
    return f"""
    <article>
      <span class="chip">{escape(label)}</span>
      <span class="meta">{escape(fmt_msk(note.created_at))}</span>
      <pre>{escape(note.text)}</pre>
    </article>"""


def _chip(watch: WatchView) -> tuple[str, str]:
    if not watch.enabled:
        return "выключена", ""
    if watch.last_error:
        return "пауза", "bad"
    if not watch.baseline_done:
        return "ждёт первый снимок", "wait"
    return "следит", "ok"


def _span(price_min: int | None, price_max: int | None) -> str:
    if price_min is None and price_max is None:
        return "без ограничений"
    left = "…" if price_min is None else str(price_min)
    right = "…" if price_max is None else str(price_max)
    return f"{left}–{right} ₽"


def _optional_price(raw: str) -> int | None:
    text = raw.strip().replace(" ", "")
    if not text:
        return None
    if not text.isdigit():
        raise ValueError("Цена должна быть целым числом в рублях")
    value = int(text)
    if value > 1_000_000_000:
        raise ValueError("Слишком большая цена")
    return value


def _redirect(message: str) -> RedirectResponse:
    return RedirectResponse("/?msg=" + quote(message), status_code=303)
