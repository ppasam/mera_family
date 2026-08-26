"""Адаптер маркетплейса Ozon.

Запросы к внутреннему API идут не со стороны, а изнутри уже открытой страницы
ozon.ru: `fetch` выполняется в контексте самой витрины, поэтому уходит
same-origin — с настоящими куками, заголовками и TLS-отпечатком браузера
клиента. Для площадки это обычная работа её же SPA.
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

from ...browser import Session
from ...models import Marketplace, Offer, PurchaseAttempt, PurchaseStage, WishItem
from . import composer

_HOME = "https://www.ozon.ru/"

# Запрос выполняется внутри страницы витрины — see docstring модуля.
_FETCH_JSON = """
async (path) => {
  const r = await fetch('/api/composer-api.bx/page/json/v2?url=' + encodeURIComponent(path),
                        {headers: {'Accept': 'application/json'}, credentials: 'include'});
  if (r.status !== 200) return {error: r.status};
  return {data: await r.text()};
}
"""


class OzonAdapter:
    marketplace = Marketplace.OZON

    async def _composer(self, session: Session, path: str) -> dict:
        """Тянет страницу витрины в виде JSON."""
        if not session.page.url.startswith(_HOME):
            await session.goto(_HOME)
        await session.pause()
        result = await session.page.evaluate(_FETCH_JSON, path)
        if "error" in result:
            raise RuntimeError(f"composer-api ответил {result['error']} на {path}")
        return json.loads(result["data"])

    async def search(self, session: Session, wish: WishItem, *, limit: int = 24) -> list[Offer]:
        """Ищет предложения, при необходимости добирая следующие страницы выдачи."""
        path = f"/search/?text={quote(wish.query)}&from_global=true"
        offers: list[Offer] = []
        seen: set[str] = set()

        while path and len(offers) < limit:
            payload = await self._composer(session, path)
            page_offers = composer.parse_search(payload)
            if not page_offers:
                break
            for offer in page_offers:
                if offer.sku not in seen:
                    seen.add(offer.sku)
                    offers.append(offer)
            path = composer.next_page_path(payload)
            if path:
                # Пауза между страницами: листать выдачу очередями — машинное поведение.
                await asyncio.sleep(session.settings.pace.between_queries)

        return [o for o in offers if matches(o, wish)][:limit]

    async def enrich(self, session: Session, offer: Offer) -> Offer:
        """Добирает то, чего нет в выдаче: цену без карты и точный срок доставки.

        Карточка товара — та же витрина, тот же composer-api.
        """
        path = offer.url.path if hasattr(offer.url, "path") else str(offer.url)
        payload = await self._composer(session, path)

        for key, raw in payload.get("widgetStates", {}).items():
            if key.startswith("webPrice"):
                try:
                    price_widget = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                without_card = composer.parse_money(price_widget.get("price", ""))
                if without_card:
                    offer.price_without_card = without_card
            elif key.startswith("webDeliveryDetails") and offer.delivery:
                try:
                    delivery_widget = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                offer.delivery.date_text = (
                    delivery_widget.get("deliveryDate") or offer.delivery.date_text
                )
        return offer

    async def add_to_cart(self, session: Session, offer: Offer) -> PurchaseAttempt:
        """Кладёт товар в корзину действиями на странице — как это делает человек.

        Оплата не подтверждается: модуль доводит заказ до экрана оплаты и
        останавливается. Кнопку «Оплатить» нажимает клиент.
        """
        attempt = PurchaseAttempt(wish_query=offer.title, offer=offer, stage=PurchaseStage.SELECTED)
        try:
            await session.goto(str(offer.url))
            await session.human_scroll()

            add_button = session.page.locator(
                "[data-widget='webAddToCart'] button, button:has-text('Добавить в корзину')"
            ).first
            await add_button.click(timeout=15000)
            await session.pause()
            attempt.stage = PurchaseStage.IN_CART

            await session.goto("https://www.ozon.ru/cart")
            attempt.stage = PurchaseStage.CHECKOUT_READY
        except Exception as exc:
            attempt.stage = PurchaseStage.FAILED
            attempt.error = str(exc)
        return attempt


def matches(offer: Offer, wish: WishItem) -> bool:
    """Отсев по уточнениям клиента: обязательные слова, стоп-слова, потолок цены."""
    title = offer.title.lower()

    if any(word.lower() not in title for word in wish.must_include):
        return False
    if any(word.lower() in title for word in wish.must_exclude):
        return False
    if wish.max_price is not None and offer.price > wish.max_price:
        return False
    return offer.in_stock
