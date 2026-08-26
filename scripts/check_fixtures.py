#!/usr/bin/env python3
"""Проверка, что в фикстурах не осталось идентификаторов сессии.

Фикстуры снимаются с живой витрины и попадают в публичный репозиторий, а ответ
`composer-api` содержит трекинговые токены сессии браузера. Один раз их уже
пришлось вычищать вручную перед публикацией — эта проверка не даёт истории
повториться и запускается в CI на каждый коммит.

Скрипт не чинит, а сообщает. Чинит `scripts/sanitize_fixture.py`.

Запуск:
    python scripts/check_fixtures.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

PLACEHOLDER = "REDACTED"

# Поля, значение которых обязано быть заглушкой.
SENSITIVE_FIELDS = ("userToken", "pageToken", "requestID", "widgetToken", "advertLite", "uid")

# Параметры ссылок, в которых витрина передаёт токены.
SENSITIVE_PARAMS = ("at", "paginator_token", "start_page_id", "search_page_state")

# Значение токена: 32 символа base64url. Отличает токен от обычного текста.
TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{32}$")


def check_file(path: Path) -> list[str]:
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")

    for field in SENSITIVE_FIELDS:
        for value in re.findall(rf'"{field}":\s*"([^"]*)"', text):
            if value != PLACEHOLDER and TOKEN_SHAPE.match(value):
                problems.append(f"{path.name}: поле {field} содержит токен, а не {PLACEHOLDER}")

    for param in SENSITIVE_PARAMS:
        for value in re.findall(rf'[?&]{param}=([^&"\\]+)', text):
            if value != PLACEHOLDER:
                problems.append(f"{path.name}: ссылка содержит {param}={value[:16]}…")

    # trackingTokenAliases — словарь токенов целиком, его положено обнулять.
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return problems
    if payload.get("trackingTokenAliases"):
        problems.append(f"{path.name}: trackingTokenAliases не обнулён")

    return problems


def main() -> int:
    fixtures = sorted(FIXTURES.glob("*.json"))
    if not fixtures:
        print("Фикстур не найдено — проверять нечего.")
        return 0

    problems = [problem for path in fixtures for problem in check_file(path)]

    if problems:
        print("В фикстурах остались идентификаторы сессии:\n")
        for problem in problems:
            print(f"  ✗ {problem}")
        print(
            f"\nПочинить: python scripts/sanitize_fixture.py <файл>\n"
            f"Проверено файлов: {len(fixtures)}, проблем: {len(problems)}"
        )
        return 1

    print(f"Фикстуры чистые: проверено файлов — {len(fixtures)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
