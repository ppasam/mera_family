#!/usr/bin/env python3
"""Э1: разведка внутреннего API витрины Ozon.

Скрипт не парсит HTML. Он открывает страницу поиска в браузере и перехватывает
ответы `composer-api.bx` — тот самый JSON, которым фронтенд Ozon наполняет
выдачу. Всё, что перехвачено, складывается в tests/fixtures: дальше адаптер
пишется и тестируется на этих фикстурах, без похода на сайт.

Запуск:
    python scripts/recon_ozon.py "омега 3 solgar"
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wishlist_buyer.browser import ChallengeDetected, open_session  # noqa: E402
from wishlist_buyer.config import Settings  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
COMPOSER = re.compile(r"composer-api\.bx/page/json")


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9а-яА-Я]+", "-", text).strip("-").lower()


async def main(query: str) -> int:
    settings = Settings()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    captured: list[dict] = []

    async with open_session(settings, require_auth=False) as session:

        async def on_response(response) -> None:
            if not COMPOSER.search(response.url):
                return
            try:
                payload = await response.json()
            except Exception:  # ответ не JSON — для разведки неинтересен
                return
            captured.append({"url": response.url, "status": response.status, "payload": payload})
            print(f"  ← перехвачен composer-api: {response.url[:120]}")

        session.page.on("response", on_response)

        url = f"https://www.ozon.ru/search/?text={quote(query)}&from_global=true"
        print(f"Открываю поиск: {query}")
        try:
            await session.goto(url)
            await session.human_scroll()
            await session.pause()
        except ChallengeDetected as exc:
            print(f"\n⚠️  {exc}")
            print("Окно браузера открыто — решите проверку вручную, затем повторите запуск.")
            await asyncio.sleep(60)
            return 2

    if not captured:
        print("\nНи одного ответа composer-api не перехвачено.")
        return 1

    out = FIXTURES / f"ozon-search-{_slug(query)}.json"
    out.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nСохранено ответов: {len(captured)} → {out.relative_to(FIXTURES.parents[1])}")

    # Карта виджетов: по ней станет ясно, откуда брать выдачу, цены и доставку.
    print("\nВиджеты в ответах:")
    for item in captured:
        states = item["payload"].get("widgetStates", {})
        for key in states:
            print(f"  {key.split('-')[0]:<32} {len(states[key])} симв.")
    return 0


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "омега 3 solgar"
    raise SystemExit(asyncio.run(main(query)))
