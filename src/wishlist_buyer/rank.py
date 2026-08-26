"""Отбор 1–3 вариантов из выдачи.

Клиенту не нужен список из сорока предложений — нужен короткий выбор с
объяснением, почему именно эти. Скоринг нормализует разнородные показатели
(рубли, дни, звёзды) в доли и складывает с весами.

Отдельная забота — предупреждения. Самая низкая цена на маркетплейсе часто
означает продавца без имени и десяток отзывов; такой вариант не выбрасывается,
но клиент видит, на что смотрит.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Offer, ScoredOffer


@dataclass(slots=True, frozen=True)
class Weights:
    price: float = 0.45
    delivery: float = 0.25
    rating: float = 0.15
    popularity: float = 0.10
    trust: float = 0.05


def _normalize_low_is_good(value: float, low: float, high: float) -> float:
    """Чем меньше значение, тем ближе к 1. При одинаковых значениях — 1."""
    if high <= low:
        return 1.0
    return max(0.0, min(1.0, (high - value) / (high - low)))


DEFAULT_WEIGHTS = Weights()


def rank(
    offers: list[Offer], *, top: int = 3, weights: Weights = DEFAULT_WEIGHTS
) -> list[ScoredOffer]:
    """Возвращает лучшие предложения с обоснованием и предупреждениями."""
    if not offers:
        return []

    prices = [float(o.price) for o in offers]
    days = [o.delivery.days for o in offers if o.delivery and o.delivery.days is not None]
    reviews = [o.reviews_count or 0 for o in offers]

    min_price, max_price = min(prices), max(prices)
    min_days, max_days = (min(days), max(days)) if days else (0, 0)
    max_reviews = max(reviews) if reviews else 0

    cheapest = min(offers, key=lambda o: o.price)
    fastest = min(
        (o for o in offers if o.delivery and o.delivery.days is not None),
        key=lambda o: o.delivery.days,
        default=None,
    )

    scored: list[ScoredOffer] = []
    for offer in offers:
        price_score = _normalize_low_is_good(float(offer.price), min_price, max_price)

        if offer.delivery and offer.delivery.days is not None:
            delivery_score = _normalize_low_is_good(offer.delivery.days, min_days, max_days)
        else:
            delivery_score = 0.5  # срок неизвестен — не наказываем и не поощряем

        rating_score = (offer.rating / 5.0) if offer.rating else 0.5
        popularity_score = (
            min(1.0, (offer.reviews_count or 0) / max_reviews) if max_reviews else 0.5
        )
        if offer.seller and offer.seller.is_official:
            trust_score = 1.0
        elif offer.seller and offer.seller.brand_verified:
            trust_score = 0.7
        else:
            trust_score = 0.4

        score = (
            weights.price * price_score
            + weights.delivery * delivery_score
            + weights.rating * rating_score
            + weights.popularity * popularity_score
            + weights.trust * trust_score
        )

        reasons: list[str] = []
        if offer is cheapest:
            reasons.append("самая низкая цена в подборке")
        # Отмечаем скорость только когда она действительно выделяет вариант:
        # если у всех «Завтра», это не преимущество.
        if fastest is not None and offer is fastest and offer.delivery and min_days < max_days:
            reasons.append(f"самая быстрая доставка — {offer.delivery.date_text}")
        if offer.discount_percent and offer.discount_percent >= 40:
            reasons.append(f"скидка {offer.discount_percent}%")
        if offer.seller and offer.seller.is_official:
            reasons.append(f"продаёт сам {offer.seller.name}")
        if offer.seller and offer.seller.brand_verified:
            reasons.append("бренд проверен маркетплейсом")
        if (offer.reviews_count or 0) >= 10_000:
            reasons.append(f"{offer.reviews_count:,}".replace(",", " ") + " отзывов")

        warnings: list[str] = []
        if not offer.seller or offer.seller.name == "не указан":
            warnings.append("продавец не указан на витрине")
        if (offer.reviews_count or 0) < 100:
            warnings.append("мало отзывов — товар новый или редкий")
        if offer.rating is not None and offer.rating < 4.5:
            warnings.append(f"рейтинг ниже обычного для категории: {offer.rating}")
        if offer.price_without_card and offer.price_without_card > offer.price:
            diff = offer.price_without_card - offer.price
            warnings.append(f"цена указана с картой Ozon; без неё дороже на {diff:.0f} ₽")

        # Вариант попал в подборку, но ничем не выделился на фоне соседей —
        # объясняем, за что его выбрал ранжировщик. Карточка без единого «почему»
        # выглядит так, будто он там случайно.
        if not reasons:
            contributions = {
                "цена ниже большинства найденных": weights.price * price_score,
                "привезут быстрее большинства": weights.delivery * delivery_score,
                "высокая оценка покупателей": weights.rating * rating_score,
                "берут чаще остальных": weights.popularity * popularity_score,
                "продавец надёжнее прочих": weights.trust * trust_score,
            }
            reasons.append(max(contributions, key=contributions.get))

        scored.append(
            ScoredOffer(offer=offer, score=round(score, 4), reasons=reasons, warnings=warnings)
        )

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top]
