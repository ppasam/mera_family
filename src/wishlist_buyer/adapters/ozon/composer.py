"""Разбор ответов внутреннего API витрины Ozon (`composer-api`).

Витрина отдаёт не HTML, а типизированные блоки: карточка товара — это список
`mainState` из `priceV2`, `textDS`, `labelListV2`. Поэтому модуль не зависит от
вёрстки: перестановка блоков местами или новый CSS-класс ничего не ломают.

Разбор намеренно терпимый: у части предложений нет продавца, у части — бренда,
отзывы приходят то числом, то строкой «5 056 отзывов». Отсутствие поля — это
None, а не исключение: одно кривое предложение не должно ронять всю выдачу.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from ...models import Delivery, Marketplace, Offer, Seller

_BASE = "https://www.ozon.ru"

# Ozon разделяет разряды узким пробелом (U+2009) и неразрывным (U+00A0).
_SPACES = str.maketrans({" ": "", " ": "", " ": ""})

# «Завтра», «Послезавтра», «Сегодня» — как срок подписан на кнопке покупки.
_DELIVERY_WORDS = {"сегодня": 0, "завтра": 1, "послезавтра": 2}


def parse_money(text: str) -> Decimal | None:
    """«2 661 ₽» → Decimal('2661')."""
    if not text:
        return None
    digits = re.sub(r"[^\d.,]", "", text.translate(_SPACES)).replace(",", ".")
    if not digits:
        return None
    try:
        return Decimal(digits)
    except Exception:
        return None


def parse_count(text: str) -> int | None:
    """«50 956» или «5 056 отзывов» → 50956 / 5056."""
    if not text:
        return None
    digits = re.sub(r"\D", "", text.translate(_SPACES))
    return int(digits) if digits else None


def parse_delivery_days(title: str | None) -> tuple[int | None, str | None]:
    """Срок с кнопки покупки: «Завтра» → 1 день."""
    if not title:
        return None, None
    normalized = title.strip().lower()
    for word, days in _DELIVERY_WORDS.items():
        if normalized.startswith(word):
            return days, title
    # «за 3 дня», «5 июня» — число вытащим, если оно есть; иначе оставим текст.
    match = re.search(r"(\d+)\s*дн", normalized)
    return (int(match.group(1)) if match else None), title


def find_grid(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Находит виджет выдачи среди `widgetStates`.

    Ключи виджетов содержат меняющиеся идентификаторы
    (`tileGridDesktop-3669724-default-1`), поэтому ищем по префиксу.
    """
    states = payload.get("widgetStates", {})
    for prefix in ("tileGridDesktop", "tileGrid", "searchResultsV2"):
        for key, raw in states.items():
            if key.startswith(prefix):
                try:
                    widget = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(widget, dict) and widget.get("items"):
                    return widget
    return None


def next_page_path(payload: dict[str, Any]) -> str | None:
    """Ссылка на следующую страницу выдачи из пагинатора."""
    for key, raw in payload.get("widgetStates", {}).items():
        if key.startswith("infiniteVirtualPaginator"):
            try:
                return json.loads(raw).get("nextPage")
            except (TypeError, json.JSONDecodeError):
                return None
    return None


def _texts(label_block: dict[str, Any]) -> list[str]:
    return [
        item["text"]["text"]
        for item in label_block.get("labelListV2", {}).get("items", [])
        if item.get("type") == "text" and item.get("text", {}).get("text")
    ]


def parse_tile(tile: dict[str, Any]) -> Offer | None:
    """Собирает Offer из одной плитки выдачи. Плитка без цены или ссылки пропускается."""
    link = tile.get("action", {}).get("link")
    sku = str(tile.get("sku") or tile.get("id") or "")
    if not link or not sku:
        return None

    title: str | None = None
    price = price_original = None
    is_card_price = False
    labels: list[list[str]] = []

    for block in tile.get("mainState", []):
        kind = block.get("type")
        if kind == "priceV2":
            prices = block["priceV2"].get("price", [])
            for entry in prices:
                value = parse_money(entry.get("text", ""))
                if entry.get("textStyle") == "ORIGINAL_PRICE":
                    price_original = value
                elif price is None:
                    price = value
            is_card_price = block["priceV2"].get("priceStyle", {}).get("styleType") == "CARD_PRICE"
        elif kind == "textDS" and block.get("id") == "name":
            title = block["textDS"].get("text")
        elif kind == "labelListV2":
            labels.append(_texts(block))

    if price is None or not title:
        return None

    # Первый список меток — бренд и знак «Бренд проверен»; второй — рейтинг,
    # число отзывов и продавец. У части предложений бренда нет вовсе.
    brand_labels = labels[0] if labels else []
    stat_labels = labels[1] if len(labels) > 1 else []

    rating = reviews = None
    seller_name = None
    for value in stat_labels:
        as_float = re.fullmatch(r"\d[.,]\d", value.strip())
        if as_float and rating is None:
            rating = float(value.replace(",", "."))
        elif re.search(r"\d", value) and reviews is None:
            reviews = parse_count(value)
        elif not re.search(r"\d", value):
            seller_name = value

    button = tile.get("multiButton", {}).get("ozonButton", {}).get("addToCart", {})
    days, date_text = parse_delivery_days(button.get("actionButton", {}).get("title"))

    # «Бренд проверен» и «продавец — Ozon» — разные утверждения: первое говорит
    # о подлинности товара, второе о том, кто его отгружает.
    brand_verified = any("проверен" in label.lower() for label in brand_labels)
    seller = (
        Seller(
            name=seller_name or "не указан",
            is_official=(seller_name or "").lower() in {"ozon", "ozon fresh"},
            brand_verified=brand_verified,
        )
        if (seller_name or brand_verified)
        else None
    )

    return Offer(
        marketplace=Marketplace.OZON,
        sku=sku,
        title=title,
        url=f"{_BASE}{link.split('?')[0]}",
        price=price,
        # При стиле CARD_PRICE витрина показывает цену по карте Ozon;
        # цена без карты в выдаче не приходит — её добирает enrich().
        price_without_card=None if is_card_price else price,
        price_original=price_original,
        seller=seller,
        delivery=Delivery(days=days, date_text=date_text) if date_text else None,
        rating=rating,
        reviews_count=reviews,
        image_url=tile.get("tileImage", {}).get("items", [{}])[0].get("image", {}).get("link")
        or None,
        raw=tile,
    )


def parse_search(payload: dict[str, Any]) -> list[Offer]:
    """Разбирает страницу выдачи целиком."""
    grid = find_grid(payload)
    if not grid:
        return []
    offers = [parse_tile(tile) for tile in grid.get("items", [])]
    return [offer for offer in offers if offer is not None]
