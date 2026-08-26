#!/usr/bin/env python3
"""Диагностика: что вообще отдаёт Ozon нашему браузеру."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wishlist_buyer.browser import open_session
from wishlist_buyer.config import Settings


async def main(query: str) -> int:
    settings = Settings()
    urls: list[tuple[int, str]] = []
    async with open_session(settings, require_auth=False) as s:
        s.page.on("response", lambda r: urls.append((r.status, r.url)))
        url = f"https://www.ozon.ru/search/?text={quote(query)}"
        resp = await s.page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(6)
        print("HTTP:", resp.status if resp else "нет ответа")
        print("URL после перехода:", s.page.url)
        print("Title:", await s.page.title())
        body = await s.page.locator("body").inner_text(timeout=10000)
        print("Длина текста body:", len(body))
        print("--- первые 500 символов ---")
        print(body[:500])
        shot = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "diag.png"
        await s.page.screenshot(path=str(shot))
        print("\nСкриншот:", shot)
        print("\n--- запросы к ozon (первые 40) ---")
        for st, u in urls[:40]:
            if "ozon" in u:
                print(f"  {st} {u[:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "омега 3 solgar")))
