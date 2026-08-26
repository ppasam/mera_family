"""Командный интерфейс модуля.

Сценарий целиком:
    wishlist login                      — разовый вход клиента в его аккаунт
    wishlist search "омега 3 solgar"    — поиск и подборка без покупки
    wishlist buy "омега 3 solgar"       — подборка, выбор клиента, корзина
    wishlist run                        — то же по всему списку желаний
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from .adapters.ozon import OzonAdapter
from .audit import Audit
from .browser import ChallengeDetected, NotAuthenticated, open_session
from .config import Settings, load_wishlist
from .models import PurchaseStage, WishItem
from .present import ask_choice, console, show_offers
from .rank import rank

app = typer.Typer(help="Поиск и закупка товаров из списка желаний клиента.", no_args_is_help=True)


def _settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


@app.command()
def login() -> None:
    """Открывает браузер для разового входа в аккаунт маркетплейса.

    Пароль и код из СМС вводит клиент — модуль их не видит и не хранит.
    Сессия остаётся в профиле модуля и живёт до тех пор, пока её не сбросит сам
    маркетплейс.
    """

    async def _run() -> None:
        settings = _settings()
        async with open_session(settings, require_auth=False) as session:
            await session.page.goto("https://www.ozon.ru/", wait_until="domcontentloaded")
            console.print(
                "\n[bold]Войдите в аккаунт в открывшемся окне.[/bold]\n"
                "[dim]Модуль ждёт появления сессии и закроется сам.[/dim]\n"
            )
            for _ in range(120):  # до 10 минут ожидания
                if await session.is_authenticated():
                    console.print(
                        "[green]Вход выполнен, сессия сохранена в профиле модуля.[/green]"
                    )
                    return
                await asyncio.sleep(5)
            console.print("[yellow]Вход не завершён — сессия не появилась.[/yellow]")

    asyncio.run(_run())


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Что ищем: «омега 3 solgar»")],
    top: Annotated[int, typer.Option(help="Сколько вариантов показать")] = 3,
    limit: Annotated[int, typer.Option(help="Сколько предложений просмотреть")] = 24,
) -> None:
    """Ищет товар и показывает лучшие варианты. Ничего не покупает."""
    asyncio.run(_search_and_offer(WishItem(query=query), top=top, limit=limit, buy=False))


@app.command()
def buy(
    query: Annotated[str, typer.Argument(help="Что покупаем")],
    top: Annotated[int, typer.Option(help="Сколько вариантов показать")] = 3,
) -> None:
    """Ищет товар, спрашивает клиента и доводит выбранный вариант до корзины.

    Оплату модуль не подтверждает — последний шаг всегда за клиентом.
    """
    asyncio.run(_search_and_offer(WishItem(query=query), top=top, limit=24, buy=True))


@app.command()
def run(
    wishlist_file: Annotated[Path | None, typer.Option(help="Файл списка желаний")] = None,
    buy_mode: Annotated[
        bool, typer.Option("--buy", help="Предлагать покупку по каждому пункту")
    ] = False,
) -> None:
    """Проходит весь список желаний клиента."""
    settings = _settings()
    path = wishlist_file or settings.wishlist_file
    if not path.exists():
        console.print(f"[red]Файл списка желаний не найден: {path}[/red]")
        raise typer.Exit(1)

    wishes = load_wishlist(path)
    console.print(f"Желаний в списке: [bold]{len(wishes)}[/bold]")
    for wish in wishes:
        asyncio.run(_search_and_offer(wish, top=3, limit=24, buy=buy_mode))


async def _search_and_offer(wish: WishItem, *, top: int, limit: int, buy: bool) -> None:
    settings = _settings()
    audit = Audit(settings.audit_dir)
    adapter = OzonAdapter()

    try:
        # Для поиска вход не нужен — он нужен для цены по карте и для корзины.
        async with open_session(settings, require_auth=buy) as session:
            console.print(f"\n[dim]Ищу «{wish.query}» на ozon.ru…[/dim]")
            offers = await adapter.search(session, wish, limit=limit)
            audit.searched(wish, len(offers))

            if not offers:
                console.print("[yellow]Ничего подходящего не нашлось.[/yellow]")
                return

            scored = rank(offers, top=top)
            audit.offered(wish, scored)
            show_offers(wish, scored)

            if not buy:
                return

            choice = ask_choice(scored)
            audit.chosen(wish, choice)
            if choice is None:
                console.print("[dim]Покупка отменена клиентом.[/dim]")
                return

            console.print(f"\n[dim]Кладу в корзину: {choice.offer.title}[/dim]")
            attempt = await adapter.add_to_cart(session, choice.offer)
            audit.purchase(attempt)

            if attempt.stage == PurchaseStage.FAILED:
                console.print(f"[red]Не удалось оформить: {attempt.error}[/red]")
            else:
                console.print(
                    "\n[green]Товар в корзине, заказ доведён до оформления.[/green]\n"
                    "[bold]Проверьте состав заказа и нажмите «Оплатить» сами — "
                    "модуль деньги не списывает.[/bold]"
                )

    except NotAuthenticated as exc:
        console.print(f"[yellow]{exc}[/yellow]")
    except ChallengeDetected as exc:
        console.print(f"[yellow]{exc}[/yellow]")


if __name__ == "__main__":
    app()
