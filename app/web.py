from __future__ import annotations

from html import escape
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.catalog import (
    CITIES,
    category_search_url,
    category_watch_name,
    grouped_categories,
    resolve_city,
)
from app.config import Settings
from app.service import ItemView, NoteView, Service, WatchView
from app.text import fmt_msk, format_price


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
        page = render_index(watches, notes, request.query_params.get("msg", ""), settings)
        return HTMLResponse(page)

    @app.get("/catalog", response_class=HTMLResponse)
    async def catalog(request: Request) -> HTMLResponse:
        city = resolve_city(request.query_params.get("city"))
        query = request.query_params.get("q", "")
        exclude = request.query_params.get("exclude", "")
        price_min = request.query_params.get("price_min", "")
        price_max = request.query_params.get("price_max", "")
        watches = await service.watch_views()
        page = render_catalog(
            city_slug=city.slug,
            query=query,
            exclude=exclude,
            price_min=price_min,
            price_max=price_max,
            watches=watches,
            message=request.query_params.get("msg", ""),
            settings=settings,
        )
        return HTMLResponse(page)

    @app.post("/catalog/watch")
    async def catalog_watch(
        city: str = Form(""),
        category: str = Form(""),
        q: str = Form(""),
        exclude_words: str = Form(""),
        price_min: str = Form(""),
        price_max: str = Form(""),
    ) -> RedirectResponse:
        try:
            url = category_search_url(city, category, q)
            name = category_watch_name(city, category, q)
            low = _optional_price(price_min)
            high = _optional_price(price_max)
            watch, created = await service.add_watch(
                0,
                url,
                name=name,
                exclude_words=exclude_words,
                price_min=low,
                price_max=high,
            )
        except ValueError as exc:
            back = f"/catalog?city={quote(city)}&q={quote(q)}"
            return _redirect_path(back, str(exc))
        if created:
            return _redirect_path(f"/watches/{watch.id}", f"Слежка «{watch.name}» сохранена.")
        return _redirect_path(f"/watches/{watch.id}", f"Такая категория уже есть: «{watch.name}».")

    @app.get("/watches/{watch_id}", response_class=HTMLResponse)
    async def watch_page(watch_id: int, request: Request) -> HTMLResponse:
        watch = await service.get_watch_view(watch_id)
        if watch is None:
            return HTMLResponse(_document("home", "<p>Нет такой слежки.</p>", "", settings), status_code=404)
        items = await service.listings(watch_id) or []
        notes = await service.notifications(watch_id=watch_id)
        page = render_watch(watch, items, notes, request.query_params.get("msg", ""), settings)
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
    async def pause(watch_id: int, return_to: str = Form("")) -> RedirectResponse:
        return _redirect_path(_safe_return(return_to), await service.set_enabled(watch_id, None, False))

    @app.post("/watches/{watch_id}/resume")
    async def resume(watch_id: int, return_to: str = Form("")) -> RedirectResponse:
        return _redirect_path(_safe_return(return_to), await service.set_enabled(watch_id, None, True))

    @app.post("/watches/{watch_id}/delete")
    async def remove(watch_id: int, return_to: str = Form("")) -> RedirectResponse:
        message = await service.delete_watch(watch_id, None)
        target = "/" if return_to.startswith("/watches/") else _safe_return(return_to)
        return _redirect_path(target, message)

    @app.post("/watches/{watch_id}/fixture")
    async def fixture(watch_id: int, fixture_name: str = Form(""), return_to: str = Form("")) -> RedirectResponse:
        return _redirect_path(_safe_return(return_to), await service.poll_fixture(watch_id, fixture_name))

    @app.post("/watches/{watch_id}/live")
    async def live(watch_id: int, return_to: str = Form("")) -> RedirectResponse:
        return _redirect_path(_safe_return(return_to), await service.poll_watch(watch_id))

    return app


def render_index(
    watches: list[WatchView],
    notes: list[NoteView],
    message: str,
    settings: Settings,
) -> str:
    cards = "\n".join(_watch_card(watch, settings, "") for watch in watches) or "<p class='empty'>Слежек пока нет.</p>"
    feed = "\n".join(_note_card(note) for note in notes) or "<p class='empty'>Уведомлений пока нет.</p>"
    body = f"""
  <p class="lead">Один и тот же механизм для любой категории: автомобили, квартиры, телефоны, мебель, работа. Выберите раздел в каталоге или вставьте готовую ссылку поиска. Первый успешный ответ запоминается молча, дальше в ленту попадают новые объявления и смена цены.</p>
  <p><a href="/catalog">Открыть каталог категорий</a></p>
  <form class="card" method="post" action="/watches">
    <label>Ссылка поиска<input name="url" required placeholder="https://www.avito.ru/moskva/avtomobili"></label>
    <label>Имя<input name="name" placeholder="Автомобили, Москва"></label>
    <div class="grid">
      <label>Должны быть в названии<input name="include_words" placeholder="toyota"></label>
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
"""
    return _document("home", body, message, settings)


def render_catalog(
    *,
    city_slug: str,
    query: str,
    exclude: str,
    price_min: str,
    price_max: str,
    watches: list[WatchView],
    message: str,
    settings: Settings,
) -> str:
    by_url = {watch.source_url: watch for watch in watches}
    groups = []
    for key, title, categories in grouped_categories():
        buttons = []
        for category in categories:
            url = category_search_url(city_slug, category.slug, query)
            existing = by_url.get(url)
            if existing is not None:
                buttons.append(
                    f'<a class="pill on" href="/watches/{existing.id}">{escape(category.title)} · смотреть</a>'
                )
                continue
            buttons.append(
                f"""<form method="post" action="/catalog/watch">
                  <input type="hidden" name="city" value="{escape(city_slug)}">
                  <input type="hidden" name="category" value="{escape(category.slug)}">
                  <input type="hidden" name="q" value="{escape(query)}">
                  <input type="hidden" name="exclude_words" value="{escape(exclude)}">
                  <input type="hidden" name="price_min" value="{escape(price_min)}">
                  <input type="hidden" name="price_max" value="{escape(price_max)}">
                  <button class="quiet pill" type="submit">{escape(category.title)}</button>
                </form>"""
            )
        groups.append(
            f'<section id="{escape(key)}"><h2>{escape(title)}</h2><div class="cats">{"".join(buttons)}</div></section>'
        )
    options = []
    for city in CITIES:
        selected = " selected" if city.slug == city_slug else ""
        options.append(f'<option value="{escape(city.slug)}"{selected}>{escape(city.title)}</option>')
    body = f"""
  <p class="lead">Город и слово общие для всего списка. Нажмите категорию, чтобы начать слежку и открыть её объявления. Уже добавленные разделы подсвечены.</p>
  <form class="card" method="get" action="/catalog">
    <div class="grid">
      <label>Город<select name="city">{"".join(options)}</select></label>
      <label>Слово в названии<input name="q" value="{escape(query)}" placeholder="можно оставить пустым"></label>
      <label>Исключить<input name="exclude" value="{escape(exclude)}" placeholder="запчасти, битый"></label>
      <label>Цена от, ₽<input name="price_min" value="{escape(price_min)}" inputmode="numeric"></label>
      <label>Цена до, ₽<input name="price_max" value="{escape(price_max)}" inputmode="numeric"></label>
    </div>
    <button class="quiet" type="submit">Применить ко всем категориям</button>
  </form>
  {"".join(groups)}
"""
    return _document("catalog", body, message, settings)


def render_watch(
    watch: WatchView,
    items: list[ItemView],
    notes: list[NoteView],
    message: str,
    settings: Settings,
) -> str:
    cards = "\n".join(_item_card(item) for item in items) or (
        "<p class='empty'>Сохранённых объявлений пока нет. Они появятся после первого ответа Авито.</p>"
    )
    feed = "\n".join(_note_card(note) for note in notes) or "<p class='empty'>Уведомлений по этой слежке нет.</p>"
    body = f"""
  <p><a href="/catalog">Все категории</a></p>
  {_watch_card(watch, settings, f"/watches/{watch.id}")}
  <h2>Объявления</h2>
  <section id="listings">{cards}</section>
  <h2>Уведомления этой слежки</h2>
  <section id="feed">{feed}</section>
"""
    return _document("catalog", body, message, settings)


def _document(active: str, body: str, message: str, settings: Settings) -> str:
    bot = "токен задан" if settings.telegram_enabled else "токена нет, лента только на этой странице"
    live = "включён" if settings.fetch_live else "выключен"
    flash = f"<p class='flash'>{escape(message)}</p>" if message else ""
    home = "active" if active == "home" else ""
    catalog = "active" if active == "catalog" else ""
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
    .nav {{ display: flex; gap: 16px; margin: 0 0 16px; }}
    .nav a {{ color: #1d1b18; text-decoration: none; }}
    .nav a.active {{ border-bottom: 2px solid #1d1b18; }}
    .flash {{ background: #fff7d6; border: 1px solid #ead98a; padding: 10px 12px; border-radius: 10px; }}
    form.card, article {{ background: #fff; border: 1px solid #e3ddd2; border-radius: 14px; padding: 16px; margin: 12px 0; }}
    label {{ display: block; margin-top: 12px; font-size: 13px; color: #5c564c; }}
    input, select {{ width: 100%; box-sizing: border-box; margin-top: 4px; padding: 8px 10px; border: 1px solid #d5cfc4; border-radius: 8px; background: #fff; }}
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
    .cats {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .cats form {{ margin: 0; }}
    .pill {{ margin: 0; border-radius: 999px; }}
    a.pill {{ display: inline-block; padding: 8px 12px; border: 1px solid #1d1b18; text-decoration: none; color: #1d1b18; }}
    a.pill.on {{ background: #e4f3e6; }}
    pre {{ white-space: pre-wrap; font: inherit; margin: 8px 0 0; }}
    a {{ color: #1d4e89; }}
    .empty {{ color: #5c564c; }}
    @media (max-width: 700px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
<main>
  <nav class="nav">
    <a class="{home}" href="/">Лента</a>
    <a class="{catalog}" href="/catalog">Категории</a>
  </nav>
  <h1>Слежка Авито</h1>
  <p class="meta">Опрос Авито: {live}. Telegram: {bot}.</p>
  {flash}
  {body}
</main>
</body>
</html>"""


def _watch_card(watch: WatchView, settings: Settings, return_to: str) -> str:
    chip, css = _chip(watch)
    error = f"<p>{escape(watch.last_error)}</p>" if watch.last_error else ""
    back = f'<input type="hidden" name="return_to" value="{escape(return_to)}">' if return_to else ""
    fixtures = ""
    if settings.allow_fixture_poll:
        fixtures = f"""
        <form method="post" action="/watches/{watch.id}/fixture">
          {back}
          <input type="hidden" name="fixture_name" value="baseline">
          <button class="quiet" type="submit">Снимок примера</button>
        </form>
        <form method="post" action="/watches/{watch.id}/fixture">
          {back}
          <input type="hidden" name="fixture_name" value="update">
          <button class="quiet" type="submit">Новые в примере</button>
        </form>"""
    toggle = "pause" if watch.enabled else "resume"
    toggle_label = "Пауза" if watch.enabled else "Включить"
    span = _span(watch.price_min, watch.price_max)
    browse = "" if return_to else f'<a class="pill" href="/watches/{watch.id}">Смотреть объявления</a>'
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
      {browse}
      <form method="post" action="/watches/{watch.id}/{toggle}">{back}<button class="quiet" type="submit">{toggle_label}</button></form>
      <form method="post" action="/watches/{watch.id}/live">{back}<button class="quiet" type="submit">Проверить Авито один раз</button></form>
      {fixtures}
      <form method="post" action="/watches/{watch.id}/delete">{back}<button class="quiet" type="submit">Удалить</button></form>
      </div>
    </article>"""


def _item_card(item: ItemView) -> str:
    place = escape(item.location) if item.location else "город не указан"
    when = escape(item.raw_date) if item.raw_date else "дата не указана"
    return f"""
    <article>
      <h3><a href="{escape(item.url)}">{escape(item.title)}</a></h3>
      <p>{escape(format_price(item.price))} · {place} · {when}</p>
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
    return _redirect_path("/", message)


def _redirect_path(path: str, message: str) -> RedirectResponse:
    separator = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{separator}msg={quote(message)}", status_code=303)


def _safe_return(raw: str) -> str:
    if raw == "/" or raw.startswith("/watches/") or raw.startswith("/catalog"):
        parsed = urlparse(raw)
        if parsed.scheme or parsed.netloc:
            return "/"
        return raw
    return "/"
