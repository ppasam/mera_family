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
from .browser import ChallengeDetected, NotAuthenticated, Session, open_session
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
    asyncio.run(_walk([WishItem(query=query)], top=top, limit=limit, buy=False))


@app.command()
def buy(
    query: Annotated[str, typer.Argument(help="Что покупаем")],
    top: Annotated[int, typer.Option(help="Сколько вариантов показать")] = 3,
) -> None:
    """Ищет товар, спрашивает клиента и доводит выбранный вариант до корзины.

    Оплату модуль не подтверждает — последний шаг всегда за клиентом.
    """
    asyncio.run(_walk([WishItem(query=query)], top=top, limit=24, buy=True))


@app.command()
def serve(
    port: Annotated[int, typer.Option(help="Порт локального сервера")] = 8765,
) -> None:
    """Поднимает страницу подбора в браузере.

    Введённый товар попадает в список желаний, поиск идёт на живую витрину через
    браузер клиента. Слушает только localhost.
    """
    from .server import serve as run_server

    run_server(_settings(), port=port)


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
    asyncio.run(_walk(wishes, top=3, limit=24, buy=buy_mode))


async def _walk(wishes: list[WishItem], *, top: int, limit: int, buy: bool) -> None:
    """Проходит список желаний в одной сессии браузера.

    Сессия одна на весь прогон по двум причинам. Первая: перезапуск браузера на
    каждый товар выглядит для витрины страннее, чем непрерывная работа. Вторая
    важнее — счётчик запросов живёт в сессии, и при перезапуске он обнулялся бы,
    превращая `max_queries_per_session` в лимит «на один товар» вместо лимита на
    весь прогон. Обоснование темпа — wiki/sources/wildberries-i-limity-parsinga.md
    """
    settings = _settings()
    audit = Audit(settings.audit_dir)
    adapter = OzonAdapter()

    try:
        # Для поиска вход не нужен — он нужен для цены по карте и для корзины.
        async with open_session(settings, require_auth=buy) as session:
            for index, wish in enumerate(wishes):
                if index:
                    # Переход к следующему товару — самое заметное для витрины
                    # место, здесь пауза длиннее всех остальных.
                    pause = settings.pace.between_items
                    console.print(f"[dim]Пауза {pause:.0f} с перед следующим товаром…[/dim]")
                    await asyncio.sleep(pause)
                await _offer_one(session, wish, adapter, audit, top=top, limit=limit, buy=buy)

    except NotAuthenticated as exc:
        console.print(f"[yellow]{exc}[/yellow]")
    except ChallengeDetected as exc:
        console.print(f"[yellow]{exc}[/yellow]")


async def _offer_one(
    session: Session,
    wish: WishItem,
    adapter: OzonAdapter,
    audit: Audit,
    *,
    top: int,
    limit: int,
    buy: bool,
) -> None:
    """Один товар: поиск, подборка, подтверждение клиента, корзина."""
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
            "\n[green]Товар в корзине.[/green]\n"
            "[bold]Оформите заказ и оплатите сами — модуль деньги не списывает.[/bold]"
        )


if __name__ == "__main__":
    app()
