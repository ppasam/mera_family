"""Журнал действий модуля.

Всё, что модуль делает от имени клиента, должно быть восстановимо постфактум:
что искали, что показали, что выбрал клиент, чем закончилось оформление.
Журнал — строки JSON, по файлу на день: их удобно и читать глазами, и разбирать.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import PurchaseAttempt, ScoredOffer, WishItem


class Audit:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    @property
    def _today_file(self) -> Path:
        return self.directory / f"{date.today().isoformat()}.jsonl"

    def _write(self, event: str, payload: dict[str, Any]) -> None:
        record = {"at": datetime.now().isoformat(timespec="seconds"), "event": event, **payload}
        with self._today_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def searched(self, wish: WishItem, found: int) -> None:
        self._write("search", {"query": wish.query, "found": found})

    def offered(self, wish: WishItem, scored: list[ScoredOffer]) -> None:
        self._write(
            "offered",
            {
                "query": wish.query,
                "offers": [
                    {
                        "sku": s.offer.sku,
                        "title": s.offer.title,
                        "price": s.offer.price,
                        "score": s.score,
                    }
                    for s in scored
                ],
            },
        )

    def chosen(self, wish: WishItem, scored: ScoredOffer | None) -> None:
        self._write(
            "chosen",
            {
                "query": wish.query,
                "sku": scored.offer.sku if scored else None,
                "declined": scored is None,
            },
        )

    def picked_in_ui(self, query: str, sku: str, title: str, price: int) -> None:
        """Выбор, сделанный на странице подбора, а не в терминале."""
        self._write("picked", {"query": query, "sku": sku, "title": title, "price": price})

    def purchase(self, attempt: PurchaseAttempt) -> None:
        self._write(
            "purchase",
            {
                "query": attempt.wish_query,
                "sku": attempt.offer.sku,
                "stage": attempt.stage,
                "error": attempt.error,
            },
        )
