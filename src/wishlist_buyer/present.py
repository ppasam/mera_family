"""Показ подборки клиенту и получение подтверждения.

Клиент выбирает не из таблицы с двадцатью колонками, а из двух-трёх карточек,
где видно главное: сколько стоит, когда приедет и чем этот вариант лучше
остальных. Предупреждения показываются рядом с ценой, а не мелким шрифтом внизу.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt
from rich.table import Table
from rich.text import Text

from .models import ScoredOffer, WishItem

console = Console()


def _money(value) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def show_offers(wish: WishItem, scored: list[ScoredOffer]) -> None:
    console.print()
    console.rule(f"[bold]{wish.query}[/bold] — {len(scored)} варианта на выбор")

    for index, item in enumerate(scored, 1):
        offer = item.offer
        body = Table.grid(padding=(0, 2))
        body.add_column(justify="right", style="dim", width=12)
        body.add_column()

        price_line = Text(_money(offer.price), style="bold green")
        if offer.price_original:
            price_line.append(f"  было {_money(offer.price_original)}", style="dim strike")
            price_line.append(f"  −{offer.discount_percent}%", style="yellow")
        body.add_row("Цена", price_line)

        if offer.delivery:
            body.add_row("Доставка", offer.delivery.date_text or "срок не указан")
        if offer.rating:
            reviews = f"{offer.reviews_count:,}".replace(",", " ") if offer.reviews_count else "—"
            body.add_row("Оценка", f"★ {offer.rating}  ({reviews} отзывов)")
        if offer.seller:
            mark = " ✓" if offer.seller.is_official else ""
            body.add_row("Продавец", f"{offer.seller.name}{mark}")

        if item.reasons:
            body.add_row("Почему", Text("· " + "\n· ".join(item.reasons), style="cyan"))
        if item.warnings:
            body.add_row("Внимание", Text("· " + "\n· ".join(item.warnings), style="yellow"))
        body.add_row("Ссылка", Text(str(offer.url), style="dim underline"))

        console.print(
            Panel(
                body,
                title=f"[bold]{index}. {offer.title}",
                title_align="left",
                border_style="blue",
            )
        )


def ask_choice(scored: list[ScoredOffer]) -> ScoredOffer | None:
    """Спрашивает клиента, какой вариант покупать. 0 — отказ от покупки."""
    console.print("[dim]0 — ничего не покупать[/dim]")
    choice = IntPrompt.ask(
        "Какой вариант покупаем?",
        choices=[str(i) for i in range(len(scored) + 1)],
        default=1,
    )
    return None if choice == 0 else scored[choice - 1]
