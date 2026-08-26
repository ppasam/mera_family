"""Тесты приведения предложений к формату страницы подбора.

Живой сервер и сборщик демо отдают странице одну и ту же структуру — иначе
страница показывала бы одно в демонстрации и другое в работе.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from wishlist_buyer.adapters.ozon.composer import parse_search
from wishlist_buyer.rank import rank
from wishlist_buyer.server import _as_json

FIXTURE = Path(__file__).parent / "fixtures" / "ozon-composer-search.json"


@pytest.fixture(scope="module")
def offers():
    return parse_search(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_recommended_offer_carries_rank_and_reasons(offers):
    scored = rank(offers, top=3)
    best = scored[0]
    item = _as_json(best.offer, (1, best))

    assert item["recommended"] is True
    assert item["rank"] == 1
    assert item["reasons"], "у рекомендованного варианта должно быть обоснование"
    assert item["price"] == int(best.offer.price)


def test_plain_offer_has_no_rank(offers):
    item = _as_json(offers[-1], None)
    assert item["recommended"] is False
    assert item["rank"] is None
    assert item["reasons"] == []


def test_payload_is_json_serialisable(offers):
    """Decimal и HttpUrl сами не сериализуются — иначе страница получила бы 500."""
    items = [_as_json(offer, None) for offer in offers]
    text = json.dumps(items, ensure_ascii=False)
    assert "Decimal" not in text
    assert json.loads(text)[0]["url"].startswith("https://www.ozon.ru/")


def test_keys_match_demo_builder(offers):
    """Набор полей совпадает с тем, что вшивает в страницу сборщик демо."""
    expected = {
        "sku",
        "title",
        "url",
        "price",
        "priceOriginal",
        "discount",
        "rating",
        "reviews",
        "seller",
        "delivery",
        "image",
        "recommended",
        "rank",
        "score",
        "reasons",
        "warnings",
    }
    assert set(_as_json(offers[0], None)) == expected


def test_price_is_whole_rubles(offers):
    item = _as_json(offers[0], None)
    assert isinstance(item["price"], int)
    assert Decimal(item["price"]) == offers[0].price


def test_search_does_not_touch_wishlist():
    """Поиск через строку — разовый: список желаний он не меняет.

    Иначе в списке оседали бы опечатки и разовые запросы, и обход командой `run`
    искал бы по ним каждый раз.
    """
    import inspect

    from wishlist_buyer import server

    source = inspect.getsource(server.BrowserWorker._search)
    assert "append_wish" not in source, "поиск не должен дописывать желания"
    assert "load_wishlist" in source, "но описание уже существующего желания брать обязан"


def test_wish_can_be_added_and_removed(tmp_path):
    """Список ведётся отдельно от поиска — руками или командами."""
    from wishlist_buyer.config import append_wish, load_wishlist, remove_wish

    path = tmp_path / "wishlist.yaml"
    assert append_wish(path, "шахматы кинешма") is True
    assert append_wish(path, "магний глицинат") is True
    assert append_wish(path, "Шахматы Кинешма ") is False, "дубль не должен добавляться"

    assert remove_wish(path, "шахматы кинешма") is True
    assert remove_wish(path, "шахматы кинешма") is False, "повторное удаление ничего не меняет"
    assert [item.query for item in load_wishlist(path)] == ["магний глицинат"]


def test_removing_keeps_detailed_entries(tmp_path):
    """Развёрнутые записи соседей не должны схлопываться при удалении."""
    from wishlist_buyer.config import load_wishlist, remove_wish

    path = tmp_path / "wishlist.yaml"
    path.write_text(
        "items:\n  - query: омега 3 solgar\n    brand: Solgar\n    max_price: 6000\n  - лишнее\n",
        encoding="utf-8",
    )
    assert remove_wish(path, "лишнее") is True

    kept = load_wishlist(path)
    assert len(kept) == 1
    assert kept[0].brand == "Solgar"
    assert kept[0].max_price == 6000
