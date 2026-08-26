#!/usr/bin/env python3
"""Проба: дёргаем composer-api из контекста уже открытой страницы ozon.ru.

Запрос уходит same-origin — с настоящими куками и заголовками браузера,
поэтому антибот видит обычное поведение SPA, а не сторонний запрос.
"""
from __future__ import annotations
import asyncio, json, sys
from pathlib import Path
from urllib.parse import quote
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from wishlist_buyer.browser import open_session
from wishlist_buyer.config import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

JS = """
async (path) => {
  const r = await fetch('/api/composer-api.bx/page/json/v2?url=' + encodeURIComponent(path), {
    headers: {'Accept': 'application/json'}, credentials: 'include'
  });
  return {status: r.status, text: await r.text()};
}
"""

async def main(query: str) -> int:
    settings = Settings()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    async with open_session(settings, require_auth=False) as s:
        await s.page.goto("https://www.ozon.ru/", wait_until="domcontentloaded")
        await asyncio.sleep(4)
        path = f"/search/?text={quote(query)}&from_global=true"
        print("Запрашиваю:", path)
        res = await s.page.evaluate(JS, path)
        print("HTTP:", res["status"], "| длина ответа:", len(res["text"]))
        if res["status"] != 200:
            print(res["text"][:600]); return 1
        data = json.loads(res["text"])
        out = FIXTURES / "ozon-composer-search.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Сохранено:", out.name)
        print("\nКлючи верхнего уровня:", list(data.keys()))
        states = data.get("widgetStates", {})
        print(f"\nВиджетов: {len(states)}")
        for key in states:
            print(f"  {key:<50} {len(states[key]):>8} симв.")
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "омега 3 solgar")))
