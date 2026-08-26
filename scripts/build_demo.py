#!/usr/bin/env python3
"""Сборка данных для демонстрационной страницы.

Демо показывает клиенту, как выглядит результат работы модуля, и работает на
настоящих данных: фикстура ответа витрины проходит через тот же парсер и тот же
ранжировщик, что и живой поиск. Ничего не выдумывается и не подставляется
вручную — поменяется логика отбора, поменяется и демо.

Картинки товаров вшиваются в страницу как data URI: демо должно открываться
одним файлом, без сети и без обращений к серверам маркетплейса.

Запуск:
    python scripts/build_demo.py
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wishlist_buyer.adapters.ozon.composer import parse_search
from wishlist_buyer.rank import rank

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ozon-composer-search.json"
OUT = ROOT / "demo" / "offers.json"
TEMPLATE = ROOT / "demo" / "template.html"
PAGE = ROOT / "demo" / "index.html"

QUERY = "омега 3 solgar"
THUMB_WIDTH = "wc250"


def thumbnail(url: str) -> str | None:
    """Скачивает миниатюру товара и возвращает её как data URI."""
    if not url:
        return None
    # Ozon отдаёт уменьшенную копию, если вставить размер в путь.
    parts = url.rsplit("/", 1)
    small = f"{parts[0]}/{THUMB_WIDTH}/{parts[1]}"
    try:
        request = urllib.request.Request(small, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(request, timeout=20).read()
    except Exception as exc:
        print(f"  не удалось скачать {small}: {exc}")
        return None
    # Витрина отдаёт WebP независимо от расширения в ссылке.
    mime = "image/webp" if raw[:4] == b"RIFF" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def main() -> int:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    offers = parse_search(payload)
    if not offers:
        print("фикстура не разобралась — нечего показывать")
        return 1

    # Тот же ранжировщик, что и в живом сценарии: топ-3 попадут в подборку.
    top = rank(offers, top=3)
    recommended = {scored.offer.sku: scored for scored in top}

    print(f"предложений: {len(offers)}, в подборке: {len(top)}")

    items = []
    for offer in offers:
        scored = recommended.get(offer.sku)
        print(f"  {offer.sku} {offer.title[:45]}")
        items.append(
            {
                "sku": offer.sku,
                "title": offer.title,
                "url": str(offer.url),
                "price": int(offer.price),
                "priceOriginal": int(offer.price_original) if offer.price_original else None,
                "discount": offer.discount_percent,
                "rating": offer.rating,
                "reviews": offer.reviews_count,
                "seller": (
                    {
                        "name": offer.seller.name,
                        "official": offer.seller.is_official,
                        "brandVerified": offer.seller.brand_verified,
                    }
                    if offer.seller
                    else None
                ),
                "delivery": offer.delivery.date_text if offer.delivery else None,
                "image": thumbnail(str(offer.image_url) if offer.image_url else ""),
                "recommended": scored is not None,
                "rank": next((i for i, s in enumerate(top, 1) if s.offer.sku == offer.sku), None),
                "score": scored.score if scored else None,
                "reasons": scored.reasons if scored else [],
                "warnings": scored.warnings if scored else [],
            }
        )

    # Рекомендованные — первыми и в порядке ранжирования.
    items.sort(key=lambda item: (item["rank"] or 99, item["price"]))

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps({"query": QUERY, "marketplace": "ozon", "items": items}, ensure_ascii=False),
        encoding="utf-8",
    )
    size = OUT.stat().st_size / 1024
    print(f"\nданные для демо: {OUT.relative_to(ROOT)} ({size:.0f} КиБ)")

    # Страница собирается самодостаточной: данные вшиваются внутрь, чтобы
    # index.html открывался двойным кликом и без сети.
    template = TEMPLATE.read_text(encoding="utf-8")
    if "/*OFFERS*/" not in template:
        print("в шаблоне нет метки /*OFFERS*/ — некуда вставлять данные")
        return 1
    PAGE.write_text(
        template.replace("/*OFFERS*/", OUT.read_text(encoding="utf-8")), encoding="utf-8"
    )
    print(f"страница демо:  {PAGE.relative_to(ROOT)} ({PAGE.stat().st_size / 1024:.0f} КиБ)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
