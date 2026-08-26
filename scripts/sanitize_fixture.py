#!/usr/bin/env python3
"""Очистка фикстуры витрины от идентификаторов сессии перед публикацией.

Ответ `composer-api` содержит трекинговые токены, привязанные к сессии браузера,
которым эту фикстуру снимали: `userToken`, `pageToken`, рекламные ключи в
`trackingInfo`. Доступа к аккаунту они не дают, но это следы конкретного
человека — в открытом репозитории им не место.

Заменяются только идентификаторы. Данные, ради которых фикстура и нужна —
названия, цены, рейтинги, сроки доставки, — остаются нетронутыми, поэтому тесты
после очистки должны проходить без изменений.

Запуск:
    python scripts/sanitize_fixture.py tests/fixtures/ozon-composer-search.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Поля-идентификаторы, значение которых заменяется заглушкой.
# `typographyToken` в список не входит: это имя стиля текста, а не идентификатор.
SENSITIVE = {"userToken", "pageToken", "requestID", "key", "advertLite", "advert", "widgetToken", "uid"}

PLACEHOLDER = "REDACTED"

# Токены встречаются и внутри ссылок: ?at=..., &paginator_token=..., &start_page_id=...
URL_PARAMS = re.compile(r"([?&](?:at|paginator_token|start_page_id|search_page_state)=)[^&\"]+")


def scrub(node):
    if isinstance(node, dict):
        return {
            key: (PLACEHOLDER if key in SENSITIVE and isinstance(value, str) else scrub(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [scrub(item) for item in node]
    if isinstance(node, str):
        return URL_PARAMS.sub(r"\1" + PLACEHOLDER, node)
    return node


def main(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))

    # widgetStates — словарь строк, каждая со своим JSON внутри.
    states = payload.get("widgetStates", {})
    for key, raw in states.items():
        try:
            states[key] = json.dumps(scrub(json.loads(raw)), ensure_ascii=False)
        except json.JSONDecodeError:
            states[key] = URL_PARAMS.sub(r"\1" + PLACEHOLDER, raw)

    # Корень чистится целиком: иначе userToken и pageToken, лежащие прямо в нём,
    # не попадают под проверку имени ключа. widgetStates уже обработан выше и
    # возвращается на место как есть.
    payload.pop("widgetStates", None)
    payload = scrub(payload)
    payload["widgetStates"] = states
    payload["trackingTokenAliases"] = {}

    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Фикстура очищена: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
