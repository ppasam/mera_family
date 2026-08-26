"""Модели предметной области: желание клиента, предложение продавца, решение о покупке.

Модели маркетплейс-независимые: адаптер конкретной площадки обязан привести
свои данные к этим типам. Всё, что специфично для площадки, живёт в `raw`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class Marketplace(StrEnum):
    OZON = "ozon"


class WishItem(BaseModel):
    """Строка списка желаний клиента."""

    query: str = Field(description="Как клиент назвал товар: «омега 3 solgar»")
    brand: str | None = Field(default=None, description="Ожидаемый бренд, если известен")
    synonyms: list[str] = Field(default_factory=list, description="Альтернативные написания")
    must_include: list[str] = Field(
        default_factory=list, description="Слова, обязательные в названии предложения"
    )
    must_exclude: list[str] = Field(
        default_factory=list, description="Слова-отсекатели: «для детей», «жевательные»"
    )
    quantity: int = Field(default=1, ge=1)
    max_price: Decimal | None = Field(default=None, description="Потолок цены за единицу, ₽")
    marketplaces: list[Marketplace] = Field(default_factory=lambda: [Marketplace.OZON])
    note: str | None = None


class Seller(BaseModel):
    name: str
    id: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    orders_count: int | None = None
    is_official: bool = Field(
        default=False, description="Сам маркетплейс или официальный магазин бренда"
    )
    brand_verified: bool = Field(
        default=False,
        description="Витрина показала знак «Бренд проверен» — это про бренд, не про продавца",
    )


class Delivery(BaseModel):
    days: int | None = Field(default=None, description="Срок в днях до пункта выдачи клиента")
    date_text: str | None = Field(default=None, description="Как срок показан на витрине")
    price: Decimal | None = None
    pickup_point: str | None = None


class Offer(BaseModel):
    """Предложение конкретного продавца по конкретному товару."""

    marketplace: Marketplace
    sku: str
    title: str
    url: HttpUrl

    price: Decimal = Field(description="Цена, которую заплатит клиент, ₽")
    price_without_card: Decimal | None = Field(
        default=None, description="Цена без карты маркетплейса, ₽"
    )
    price_original: Decimal | None = Field(default=None, description="Цена до скидки, ₽")

    seller: Seller | None = None
    delivery: Delivery | None = None

    rating: float | None = Field(default=None, ge=0, le=5)
    reviews_count: int | None = None
    in_stock: bool = True

    image_url: HttpUrl | None = None
    collected_at: datetime = Field(default_factory=datetime.now)
    raw: dict[str, Any] = Field(
        default_factory=dict, exclude=True, description="Сырой ответ площадки для отладки"
    )

    @property
    def discount_percent(self) -> int | None:
        if not self.price_original or self.price_original <= 0:
            return None
        return int((1 - self.price / self.price_original) * 100)


class ScoredOffer(BaseModel):
    """Предложение с оценкой ранжировщика и человекочитаемым обоснованием."""

    offer: Offer
    score: float
    reasons: list[str] = Field(
        default_factory=list, description="Почему вариант попал в подборку: «самая низкая цена»"
    )
    warnings: list[str] = Field(
        default_factory=list, description="На что клиенту стоит посмотреть перед покупкой"
    )


class PurchaseStage(StrEnum):
    """Докуда доведён заказ. Оплата — всегда за человеком."""

    SELECTED = "selected"
    IN_CART = "in_cart"
    CHECKOUT_READY = "checkout_ready"
    AWAITING_PAYMENT = "awaiting_payment"
    FAILED = "failed"


class PurchaseAttempt(BaseModel):
    wish_query: str
    offer: Offer
    stage: PurchaseStage
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None
    screenshots: list[str] = Field(default_factory=list)
    error: str | None = None
    on_date: date = Field(default_factory=date.today)
