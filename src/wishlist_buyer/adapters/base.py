"""Интерфейс адаптера маркетплейса.

Ядро модуля не знает ничего про Ozon. Чтобы добавить Wildberries или Яндекс.Маркет,
достаточно новой реализации этого протокола — поиск, ранжирование, подтверждение
и журнал остаются прежними.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..browser import Session
from ..models import Marketplace, Offer, PurchaseAttempt, WishItem


@runtime_checkable
class MarketplaceAdapter(Protocol):
    marketplace: Marketplace

    async def search(self, session: Session, wish: WishItem, *, limit: int = 24) -> list[Offer]:
        """Ищет предложения по желанию клиента. Возвращает сырой список без ранжирования."""
        ...

    async def enrich(self, session: Session, offer: Offer) -> Offer:
        """Дополняет предложение тем, чего нет в выдаче: срок доставки, продавец, цена с картой."""
        ...

    async def add_to_cart(self, session: Session, offer: Offer) -> PurchaseAttempt:
        """Кладёт товар в корзину и доводит заказ до экрана оплаты. Оплату не подтверждает."""
        ...
