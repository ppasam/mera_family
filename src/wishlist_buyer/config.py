"""Конфигурация модуля: пути, режимы, темп работы."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .models import Marketplace, WishItem


def _path(env: str, default: str) -> Path:
    return Path(os.environ.get(env, default)).expanduser()


def _flag(env: str, default: bool) -> bool:
    raw = os.environ.get(env)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


@dataclass(slots=True)
class Pace:
    """Темп работы. Не декоративный: именно он отличает клиента от парсера.

    Значения подобраны под одиночного пользователя с коротким списком желаний.
    Ускорять их — прямой путь к капче и блокировке IP на уровне CDN.
    """

    min_action_delay: float = 0.8
    max_action_delay: float = 2.6
    page_settle: float = 3.0

    # Пауза между страницами одной выдачи.
    between_queries: float = 20.0

    # Пауза перед переходом к следующему товару списка желаний. Практики парсинга
    # сходятся на «около минуты между товарами» для Ozon; берём с запасом вниз,
    # потому что запросы идут из настоящей сессии клиента, а не с прокси.
    # Обоснование и числа — wiki/sources/wildberries-i-limity-parsinga.md
    between_items: float = 45.0

    # Лимит навигаций на весь прогон, а не на один товар. Ниже порога, после
    # которого витрина начинает показывать проверку (20–30 запросов).
    max_queries_per_session: int = 18

    scroll_steps: tuple[int, int] = (2, 5)


@dataclass(slots=True)
class Settings:
    browser_profile: Path = field(
        default_factory=lambda: _path(
            "WISHLIST_BROWSER_PROFILE", "~/.local/share/wishlist-buyer/chrome-profile"
        )
    )
    source_profile: Path = field(
        default_factory=lambda: _path("WISHLIST_SOURCE_PROFILE", "~/.config/google-chrome/Default")
    )
    audit_dir: Path = field(
        default_factory=lambda: _path("WISHLIST_AUDIT_DIR", "~/.local/share/wishlist-buyer/audit")
    )
    wishlist_file: Path = field(
        default_factory=lambda: _path("WISHLIST_FILE", "config/wishlist.yaml")
    )
    cache_db: Path = field(
        default_factory=lambda: _path("WISHLIST_CACHE_DB", "~/.local/share/wishlist-buyer/cache.db")
    )
    headful: bool = field(default_factory=lambda: _flag("WISHLIST_HEADFUL", True))
    pace: Pace = field(default_factory=Pace)

    def ensure_dirs(self) -> None:
        for directory in (self.browser_profile.parent, self.audit_dir, self.cache_db.parent):
            directory.mkdir(parents=True, exist_ok=True)


def load_wishlist(path: Path) -> list[WishItem]:
    """Читает список желаний из YAML.

    Минимальная форма — строка запроса; развёрнутая — словарь с полями WishItem.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_items = data.get("items", data if isinstance(data, list) else [])

    items: list[WishItem] = []
    for entry in raw_items:
        if isinstance(entry, str):
            items.append(WishItem(query=entry))
        else:
            if "marketplaces" in entry:
                entry["marketplaces"] = [Marketplace(m) for m in entry["marketplaces"]]
            items.append(WishItem(**entry))
    return items
