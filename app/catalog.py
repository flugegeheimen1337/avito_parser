from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode, urlunparse

from app.urls import normalize_search_url

GROUPS: tuple[tuple[str, str], ...] = (
    ("transport", "Транспорт"),
    ("realty", "Недвижимость"),
    ("electronics", "Электроника"),
    ("home", "Для дома"),
    ("personal", "Личные вещи"),
    ("hobby", "Хобби и отдых"),
    ("animals", "Животные"),
    ("work", "Работа и услуги"),
    ("business", "Бизнес"),
)


@dataclass(frozen=True)
class City:
    slug: str
    title: str


@dataclass(frozen=True)
class Category:
    slug: str
    title: str
    group: str


CITIES: tuple[City, ...] = (
    City("moskva", "Москва"),
    City("sankt-peterburg", "Санкт-Петербург"),
    City("novosibirsk", "Новосибирск"),
    City("ekaterinburg", "Екатеринбург"),
    City("kazan", "Казань"),
    City("nizhniy_novgorod", "Нижний Новгород"),
    City("chelyabinsk", "Челябинск"),
    City("samara", "Самара"),
    City("omsk", "Омск"),
    City("rostov-na-donu", "Ростов-на-Дону"),
    City("ufa", "Уфа"),
    City("krasnoyarsk", "Красноярск"),
    City("perm", "Пермь"),
    City("voronezh", "Воронеж"),
    City("volgograd", "Волгоград"),
    City("krasnodar", "Краснодар"),
    City("saratov", "Саратов"),
    City("tyumen", "Тюмень"),
    City("sochi", "Сочи"),
    City("kaliningrad", "Калининград"),
    City("vladivostok", "Владивосток"),
    City("habarovsk", "Хабаровск"),
    City("irkutsk", "Иркутск"),
    City("barnaul", "Барнаул"),
    City("yaroslavl", "Ярославль"),
    City("tomsk", "Томск"),
    City("kemerovo", "Кемерово"),
    City("ryazan", "Рязань"),
    City("tula", "Тула"),
    City("izhevsk", "Ижевск"),
)

CATEGORIES: tuple[Category, ...] = (
    Category("avtomobili", "Автомобили", "transport"),
    Category("mototsikly_i_mototehnika", "Мотоциклы", "transport"),
    Category("gruzoviki_i_spetstehnika", "Грузовики и спецтехника", "transport"),
    Category("vodnyy_transport", "Водный транспорт", "transport"),
    Category("zapchasti_i_aksessuary", "Запчасти и аксессуары", "transport"),
    Category("kvartiry", "Квартиры", "realty"),
    Category("komnaty", "Комнаты", "realty"),
    Category("doma_dachi_kottedzhi", "Дома и дачи", "realty"),
    Category("zemelnye_uchastki", "Земельные участки", "realty"),
    Category("garazhi_i_mashinomesta", "Гаражи", "realty"),
    Category("kommercheskaya_nedvizhimost", "Коммерческая недвижимость", "realty"),
    Category("nedvizhimost_za_rubezhom", "Недвижимость за рубежом", "realty"),
    Category("bytovaya_elektronika", "Вся электроника", "electronics"),
    Category("telefony", "Телефоны", "electronics"),
    Category("noutbuki", "Ноутбуки", "electronics"),
    Category("audio_i_video", "Аудио и видео", "electronics"),
    Category("tovary_dlya_kompyutera", "Товары для компьютера", "electronics"),
    Category("igry_pristavki_i_programmy", "Игры и приставки", "electronics"),
    Category("orgtehnika_i_rashodniki", "Оргтехника", "electronics"),
    Category("fototehnika", "Фототехника", "electronics"),
    Category("mebel_i_interer", "Мебель и интерьер", "home"),
    Category("bytovaya_tehnika", "Бытовая техника", "home"),
    Category("posuda_i_tovary_dlya_kuhni", "Посуда и кухня", "home"),
    Category("remont_i_stroitelstvo", "Ремонт и стройка", "home"),
    Category("produkty_pitaniya", "Продукты питания", "home"),
    Category("rasteniya", "Растения", "home"),
    Category("odezhda_obuv_aksessuary", "Одежда и обувь", "personal"),
    Category("chasy_i_ukrasheniya", "Часы и украшения", "personal"),
    Category("krasota_i_zdorove", "Красота и здоровье", "personal"),
    Category("detskaya_odezhda_i_obuv", "Детская одежда", "personal"),
    Category("tovary_dlya_detey_i_igrushki", "Детские товары", "personal"),
    Category("sport_i_otdyh", "Спорт и отдых", "hobby"),
    Category("velosipedy", "Велосипеды", "hobby"),
    Category("knigi_i_zhurnaly", "Книги и журналы", "hobby"),
    Category("kollektsionirovanie", "Коллекционирование", "hobby"),
    Category("muzykalnye_instrumenty", "Музыкальные инструменты", "hobby"),
    Category("bilety_i_puteshestviya", "Билеты и путешествия", "hobby"),
    Category("ohota_i_rybalka", "Охота и рыбалка", "hobby"),
    Category("sobaki", "Собаки", "animals"),
    Category("koshki", "Кошки", "animals"),
    Category("ptitsy", "Птицы", "animals"),
    Category("akvarium", "Аквариум", "animals"),
    Category("drugie_zhivotnye", "Другие животные", "animals"),
    Category("tovary_dlya_zhivotnyh", "Товары для животных", "animals"),
    Category("vakansii", "Вакансии", "work"),
    Category("rezume", "Резюме", "work"),
    Category("predlozheniya_uslug", "Услуги", "work"),
    Category("oborudovanie_dlya_biznesa", "Оборудование для бизнеса", "business"),
    Category("gotoviy_biznes", "Готовый бизнес", "business"),
)

_CITIES = {city.slug: city for city in CITIES}
_CATEGORIES = {category.slug: category for category in CATEGORIES}


def city_by_slug(slug: str | None) -> City | None:
    if not slug:
        return None
    return _CITIES.get(slug)


def resolve_city(slug: str | None) -> City:
    return city_by_slug(slug) or CITIES[0]


def category_by_slug(slug: str | None) -> Category | None:
    if not slug:
        return None
    return _CATEGORIES.get(slug)


def grouped_categories() -> list[tuple[str, str, list[Category]]]:
    buckets: dict[str, list[Category]] = {key: [] for key, _title in GROUPS}
    for category in CATEGORIES:
        buckets[category.group].append(category)
    return [(key, title, buckets[key]) for key, title in GROUPS]


def category_search_url(city_slug: str, category_slug: str, query: str = "") -> str:
    city = city_by_slug(city_slug)
    category = category_by_slug(category_slug)
    if city is None or category is None:
        raise ValueError("Выберите город и категорию из списка")
    text = " ".join(query.split())[:120]
    pairs = [("q", text)] if text else []
    raw = urlunparse(("https", "www.avito.ru", f"/{city.slug}/{category.slug}", "", urlencode(pairs), ""))
    return normalize_search_url(raw)


def category_watch_name(city_slug: str, category_slug: str, query: str = "") -> str:
    city = city_by_slug(city_slug)
    category = category_by_slug(category_slug)
    if city is None or category is None:
        raise ValueError("Выберите город и категорию из списка")
    text = " ".join(query.split())
    if text:
        return f"{category.title}: {text} · {city.title}"[:200]
    return f"{category.title} · {city.title}"
