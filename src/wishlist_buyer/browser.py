"""Управление браузерной сессией.

Модуль работает в собственном постоянном профиле Chrome, в который клиент один
раз входит руками (команда `wishlist login`). Дальше сессия живёт сама: куки
настоящие, вход настоящий, IP домашний. Пароли клиента модулю не нужны и не
запрашиваются — вход происходит в открытом окне, руками владельца аккаунта.

Темп работы задаётся Pace и намеренно медленный. Капчу модуль не обходит:
увидел — остановился и отдал управление человеку.
"""

from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from patchright.async_api import BrowserContext, Page, async_playwright

from .config import Settings

# Признаки того, что витрина показала проверку вместо содержимого.
_CHALLENGE_MARKERS = (
    "Доступ ограничен",
    "проверка безопасности",
    "challenge",
    "Что-то пошло не так",
    "Подтвердите, что вы не робот",
)


class ChallengeDetected(RuntimeError):
    """Витрина показала антибот-проверку. Дальше решает человек, не скрипт."""


class NotAuthenticated(RuntimeError):
    """В профиле нет активной сессии клиента — нужен `wishlist login`."""


@dataclass(slots=True)
class Session:
    context: BrowserContext
    page: Page
    settings: Settings
    _queries: int = 0

    async def pause(self) -> None:
        """Пауза между действиями — человек не кликает раз в 50 мс."""
        pace = self.settings.pace
        await asyncio.sleep(random.uniform(pace.min_action_delay, pace.max_action_delay))

    async def human_scroll(self) -> None:
        """Прокрутка страницы: без неё поведение читается как машинное."""
        low, high = self.settings.pace.scroll_steps
        for _ in range(random.randint(low, high)):
            await self.page.mouse.wheel(0, random.randint(300, 900))
            await asyncio.sleep(random.uniform(0.4, 1.4))

    async def goto(self, url: str) -> None:
        """Переход на страницу с проверкой на антибот и с человеческим темпом."""
        if self._queries >= self.settings.pace.max_queries_per_session:
            raise RuntimeError(
                f"исчерпан лимит запросов за сессию "
                f"({self.settings.pace.max_queries_per_session}) — продолжим позже"
            )
        self._queries += 1

        await self.page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(self.settings.pace.page_settle)
        await self.ensure_no_challenge()

    async def ensure_no_challenge(self) -> None:
        title = await self.page.title()
        body = await self.page.locator("body").inner_text(timeout=5000)
        haystack = f"{title}\n{body[:2000]}".lower()
        for marker in _CHALLENGE_MARKERS:
            if marker.lower() in haystack:
                raise ChallengeDetected(
                    "Ozon показал проверку. Решите её в открытом окне браузера "
                    "и запустите команду заново."
                )

    async def is_authenticated(self) -> bool:
        """Вход определяется по кукам сессии, а не по вёрстке шапки."""
        cookies = await self.context.cookies("https://www.ozon.ru")
        names = {c["name"] for c in cookies}
        return bool(names & {"__Secure-access-token", "__Secure-refresh-token"})


@asynccontextmanager
async def open_session(settings: Settings, *, require_auth: bool = True) -> AsyncIterator[Session]:
    """Открывает браузер на постоянном профиле модуля."""
    settings.ensure_dirs()
    profile: Path = settings.browser_profile

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            channel="chrome",             # настоящий Chrome, не Chromium из поставки
            headless=not settings.headful,
            no_viewport=True,
            locale="ru-RU",
            timezone_id="Europe/Samara",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        session = Session(context=context, page=page, settings=settings)
        try:
            if require_auth and not await session.is_authenticated():
                raise NotAuthenticated(
                    "в профиле нет сессии Ozon — выполните `wishlist login` и войдите вручную"
                )
            yield session
        finally:
            await context.close()
