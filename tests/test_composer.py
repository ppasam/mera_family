"""Тесты разбора ответов витрины на зафиксированной выдаче.

Фикстура снята с живого Ozon скриптом scripts/probe_composer.py. Тесты не ходят
в сеть: адаптер должен разбирать сохранённый ответ так же, как свежий.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from wishlist_buyer.adapters.ozon.adapter import matches
from wishlist_buyer.adapters.ozon.composer import (
    next_page_path,
    parse_count,
    parse_delivery_days,
    parse_money,
    parse_search,
)
from wishlist_buyer.models import Marketplace, WishItem
from wishlist_buyer.rank import rank

FIXTURE = Path(__file__).parent / "fixtures" / "ozon-composer-search.json"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def offers(payload):
    return parse_search(payload)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1 566 ₽", Decimal("1566")),  # узкий пробел как разделитель разрядов
        ("984 ₽", Decimal("984")),
        ("5 056 отзывов", Decimal("5056")),  # неразрывный пробел
        ("", None),
        ("бесплатно", None),
    ],
)
def test_parse_money(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize(
    ("title", "days"),
    [("Завтра", 1), ("Сегодня", 0), ("Послезавтра", 2), ("за 3 дня", 3), (None, None)],
)
def test_parse_delivery_days(title, days):
    assert parse_delivery_days(title)[0] == days


def test_parse_count_handles_review_suffix():
    assert parse_count("5 056 отзывов") == 5056


def test_search_parsed(offers):
    assert len(offers) == 8
    assert all(o.marketplace is Marketplace.OZON for o in offers)
    assert all(o.price > 0 for o in offers)
    assert all(str(o.url).startswith("https://www.ozon.ru/product/") for o in offers)


def test_prices_and_discount(offers):
    cheapest = min(offers, key=lambda o: o.price)
    assert cheapest.price == Decimal("984")
    assert cheapest.price_original == Decimal("1590")
    assert cheapest.discount_percent == 38


def test_brand_verified_is_not_seller_official(offers):
    """«Бренд проверен» не должен превращать безымянного продавца в официального."""
    nameless = [o for o in offers if o.seller and o.seller.name == "не указан"]
    assert nameless, "в фикстуре есть предложения без продавца"
    assert all(o.seller.brand_verified for o in nameless)
    assert all(not o.seller.is_official for o in nameless)


def test_pagination_link_present(payload):
    assert next_page_path(payload)


def test_must_include_filters_cyrillic_brand(offers):
    """must_include работает по написанию: латинский «solgar» отсекает «Солгар»."""
    wish = WishItem(query="омега 3 solgar", must_include=["solgar"])
    kept = [o for o in offers if matches(o, wish)]
    assert len(kept) == 6
    assert all("solgar" in o.title.lower() for o in kept)


def test_max_price_filter(offers):
    wish = WishItem(query="омега 3 solgar", max_price=Decimal("1600"))
    kept = [o for o in offers if matches(o, wish)]
    assert kept and all(o.price <= 1600 for o in kept)


def test_must_exclude_filter(offers):
    wish = WishItem(query="омега 3", must_exclude=["омега 3-6-9", "комплекс"])
    kept = [o for o in offers if matches(o, wish)]
    assert not any("комплекс" in o.title.lower() for o in kept)


def test_rank_returns_top_three_sorted(offers):
    scored = rank(offers, top=3)
    assert len(scored) == 3
    assert scored == sorted(scored, key=lambda s: s.score, reverse=True)
    assert scored[0].offer.price == Decimal("984")


def test_rank_does_not_praise_equal_delivery(offers):
    """У всех предложений срок «Завтра» — хвалить за скорость нечего."""
    scored = rank(offers, top=3)
    assert not any("быстрая доставка" in r for s in scored for r in s.reasons)


def test_rank_warns_about_nameless_seller(offers):
    scored = rank(offers, top=8)
    nameless = [s for s in scored if s.offer.seller and s.offer.seller.name == "не указан"]
    assert nameless
    assert all(any("продавец не указан" in w for w in s.warnings) for s in nameless)


def test_every_recommended_offer_explains_itself(offers):
    """Карточка без единого «почему» выглядит так, будто попала в подборку случайно."""
    for scored in rank(offers, top=3):
        assert scored.reasons, f"{scored.offer.title} попал в подборку без обоснования"
