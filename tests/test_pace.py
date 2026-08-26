"""Тесты темпа работы — того, что отличает клиента от парсера.

Числа здесь не косметические: они держат модуль ниже порогов, после которых
витрина показывает проверку и блокирует адрес. Обоснование каждого — в
wiki/sources/wildberries-i-limity-parsinga.md. Тест ловит случайное ускорение
при рефакторинге.
"""

from __future__ import annotations

import inspect

from wishlist_buyer import cli
from wishlist_buyer.config import Pace


def test_queries_limit_below_challenge_threshold():
    """Витрина начинает показывать проверку после 20–30 навигаций."""
    assert Pace().max_queries_per_session < 20


def test_pause_between_items_is_the_longest():
    """Переход к следующему товару заметнее всего — пауза там должна быть максимальной."""
    pace = Pace()
    assert pace.between_items > pace.between_queries > pace.max_action_delay


def test_action_delays_are_random_range():
    pace = Pace()
    assert 0 < pace.min_action_delay < pace.max_action_delay


def test_walk_uses_single_session_for_whole_list():
    """Сессия одна на весь прогон.

    Если открывать браузер на каждый товар, счётчик запросов обнуляется и
    max_queries_per_session превращается в лимит «на один товар». Проверяем по
    исходнику: открытие сессии — снаружи цикла по желаниям.
    """
    source = inspect.getsource(cli._walk)
    open_at = source.index("open_session")
    loop_at = source.index("for index, wish in enumerate(wishes)")
    assert open_at < loop_at, "сессия должна открываться до цикла по товарам"

    # Один товар обрабатывается уже готовой сессией, а не открывает свою.
    assert "open_session" not in inspect.getsource(cli._offer_one)


def test_walk_pauses_between_items():
    source = inspect.getsource(cli._walk)
    assert "between_items" in source
    assert "asyncio.sleep" in source


def test_server_reuses_one_browser_session():
    """Сервер держит одну сессию на всё время работы.

    Открывать браузер на каждый HTTP-запрос — то же самое, что открывать его на
    каждый товар списка: витрина видит череду новых посетителей, а счётчик
    запросов обнуляется.
    """
    from wishlist_buyer import server

    source = inspect.getsource(server.BrowserWorker)
    assert "if self._session is None" in source, "сессия должна создаваться один раз"
    assert "open_session" in source


def test_walk_reports_failures_instead_of_traceback():
    """Клиенту нужна причина, а не трейсбек изнутри драйвера браузера."""
    source = inspect.getsource(cli._walk)
    assert "ProfileBusy" in source, "занятый профиль — самая частая причина отказа"
    assert "except Exception" in source, "неожиданная ошибка тоже должна объясняться"
