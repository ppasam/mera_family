"""Локальный веб-интерфейс поверх модуля.

Отдаёт страницу `web/index.html` и обслуживает её запросы. Поиск настоящий: тот
же браузер, та же сессия клиента, тот же разбор `composer-api`, что и в командах
терминала. Введённый товар попадает в список желаний, выбор клиента — в журнал.

Браузер живёт в отдельном потоке со своим циклом событий и переиспользуется
между запросами. Открывать сессию на каждый поиск нельзя: витрина видит серию
запусков вместо непрерывной работы, а счётчик запросов обнуляется, и лимит темпа
перестаёт что-либо ограничивать.

Сервер слушает только localhost и предназначен для одного человека за своим
компьютером — ни авторизации, ни защиты от параллельных запросов здесь нет.
"""

from __future__ import annotations

import asyncio
import json
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .adapters.ozon import OzonAdapter
from .audit import Audit
from .browser import ChallengeDetected, NotAuthenticated, Session, open_session
from .config import Settings, load_wishlist, remove_wish
from .models import Offer, WishItem
from .rank import rank

PAGE = Path(__file__).resolve().parents[2] / "web" / "index.html"


class BrowserWorker:
    """Держит одну браузерную сессию в фоновом потоке.

    Сессия открывается при первом запросе и живёт до остановки сервера, чтобы
    витрина видела одного посетителя, а не череду новых.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.adapter = OzonAdapter()
        self.audit = Audit(settings.audit_dir)
        # Что уже подобрано по каждому желанию. Сам список желаний живёт в файле,
        # а вот «найдено 16, выбран такой-то» — состояние текущего сеанса подбора.
        self.progress: dict[str, dict[str, Any]] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._session: Session | None = None
        self._exit: Any = None
        self._lock = threading.Lock()
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    async def _ensure_session(self) -> Session:
        if self._session is None:
            # Контекстный менеджер держим вручную: сессия должна пережить запрос.
            self._exit = open_session(self.settings, require_auth=False)
            self._session = await self._exit.__aenter__()
        return self._session

    def search(self, query: str, *, top: int = 3, limit: int = 24) -> dict[str, Any]:
        """Ищет товар и отдаёт результат в том виде, который понимает страница."""
        with self._lock:  # один поиск за раз: браузер не умеет параллельно
            return self._submit(self._search(query, top=top, limit=limit))

    async def _search(self, query: str, *, top: int, limit: int) -> dict[str, Any]:
        session = await self._ensure_session()

        # Поиск через строку — разовый: список желаний он не пополняет. Иначе в
        # списке оседали бы опечатки и разовые запросы, и команда `run` искала бы
        # по ним при каждом обходе. Список ведётся осознанно — руками в файле.
        #
        # Но если товар в списке уже описан, берём описание целиком: с брендом,
        # стоп-словами и потолком цены, а не голую строку запроса.
        wish = next(
            (
                item
                for item in load_wishlist(self.settings.wishlist_file)
                if item.query.strip().lower() == query.strip().lower()
            ),
            WishItem(query=query),
        )

        offers = await self.adapter.search(session, wish, limit=limit)
        self.audit.searched(wish, len(offers))

        scored = rank(offers, top=top) if offers else []
        if scored:
            self.audit.offered(wish, scored)
        ranked = {item.offer.sku: (position, item) for position, item in enumerate(scored, 1)}

        items = [_as_json(offer, ranked.get(offer.sku)) for offer in offers]
        items.sort(key=lambda item: (item["rank"] or 99, item["price"]))

        self.progress[wish.query] = {
            "found": len(items),
            "picked": self.progress.get(wish.query, {}).get("picked"),
        }

        return {
            "query": wish.query,
            "marketplace": "ozon",
            "items": items,
            "live": True,
            "inWishlist": any(
                item.query.strip().lower() == query.strip().lower()
                for item in load_wishlist(self.settings.wishlist_file)
            ),
            "wishlist": self.wishlist(),
        }

    def wishlist(self) -> list[dict[str, Any]]:
        """Список желаний клиента вместе с тем, что по ним уже подобрано."""
        return [
            {
                "query": item.query,
                "brand": item.brand,
                "maxPrice": int(item.max_price) if item.max_price else None,
                **self.progress.get(item.query, {"found": None, "picked": None}),
            }
            for item in load_wishlist(self.settings.wishlist_file)
        ]

    def forget(self, query: str) -> dict[str, Any]:
        """Убирает желание из списка вместе с состоянием подбора по нему."""
        removed = remove_wish(self.settings.wishlist_file, query)
        self.progress.pop(query, None)
        return {"removed": removed, "wishlist": self.wishlist()}

    def choose(self, query: str, sku: str, title: str, price: int) -> dict[str, Any]:
        """Отмечает выбор клиента: в журнале действий и в состоянии подбора."""
        self.progress.setdefault(query, {"found": None})["picked"] = {
            "sku": sku,
            "title": title,
            "price": price,
        }
        self.audit.picked_in_ui(query, sku, title, price)
        return {"ok": True, "wishlist": self.wishlist()}

    def close(self) -> None:
        if self._session is not None:
            self._submit(self._exit.__aexit__(None, None, None))
            self._session = None
        self._loop.call_soon_threadsafe(self._loop.stop)


def _as_json(offer: Offer, ranked: tuple[int, Any] | None) -> dict[str, Any]:
    """Приводит предложение к структуре, которую понимает страница подбора."""
    position, scored = ranked if ranked else (None, None)
    return {
        "sku": offer.sku,
        "title": offer.title,
        "url": str(offer.url),
        "price": int(offer.price),
        "priceOriginal": int(offer.price_original) if offer.price_original else None,
        "discount": offer.discount_percent,
        "rating": offer.rating,
        "reviews": offer.reviews_count,
        "seller": (
            {
                "name": offer.seller.name,
                "official": offer.seller.is_official,
                "brandVerified": offer.seller.brand_verified,
            }
            if offer.seller
            else None
        ),
        "delivery": offer.delivery.date_text if offer.delivery else None,
        # Картинка отдаётся ссылкой: страницу открывает свой же сервер, и
        # загрузка с домена витрины ему не запрещена.
        "image": str(offer.image_url) if offer.image_url else None,
        "recommended": scored is not None,
        "rank": position,
        "score": scored.score if scored else None,
        "reasons": scored.reasons if scored else [],
        "warnings": scored.warnings if scored else [],
    }


class Handler(BaseHTTPRequestHandler):
    worker: BrowserWorker

    def do_GET(self) -> None:
        route = urlparse(_decoded_path(self.path))

        if route.path in ("/", "/index.html"):
            self._send_page()
        elif route.path == "/api/search":
            query = (parse_qs(route.query).get("q") or [""])[0].strip()
            self._send_search(query)
        elif route.path == "/api/wishlist":
            self._send_json(
                {
                    "wishlist": self.worker.wishlist(),
                    "pauseBetweenItems": self.worker.settings.pace.between_items,
                }
            )
        elif route.path == "/api/forget":
            query = (parse_qs(route.query).get("q") or [""])[0]
            self._send_json(self.worker.forget(query))
        elif route.path == "/api/choose":
            params = parse_qs(route.query)
            self._send_json(
                self.worker.choose(
                    (params.get("q") or [""])[0],
                    (params.get("sku") or [""])[0],
                    (params.get("title") or [""])[0],
                    int((params.get("price") or ["0"])[0]),
                )
            )
        else:
            self._send_json({"error": "не найдено"}, status=404)

    def _send_page(self) -> None:
        if not PAGE.exists():
            self._send_json({"error": f"страница интерфейса не найдена: {PAGE}"}, status=500)
            return
        body = PAGE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_search(self, query: str) -> None:
        if not query:
            self._send_json({"error": "пустой запрос"}, status=400)
            return
        try:
            self._send_json(self.worker.search(query))
        except NotAuthenticated as exc:
            self._send_json({"error": str(exc)}, status=401)
        except ChallengeDetected as exc:
            self._send_json({"error": str(exc)}, status=429)
        except Exception as exc:  # витрина могла измениться или сеть отвалиться
            self._send_json({"error": f"поиск не удался: {exc}"}, status=500)

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=_encode).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        """Свой формат лога: строка на запрос вместо шумного стандартного."""
        print(f"  {fmt % args}")


def _decoded_path(path: str) -> str:
    """Возвращает строку запроса в UTF-8.

    Базовый обработчик разбирает строку HTTP-запроса как latin-1 — так велит
    стандарт. Браузер кириллицу экранирует, и с ним всё в порядке, но запрос,
    отправленный сырыми UTF-8 байтами (curl, скрипт), превратился бы в
    «Ð¾Ð¼ÐµÐ³Ð°». Перекодируем обратно, если это возможно.
    """
    try:
        return path.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return path


def _encode(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value)
    return str(value)


def serve(settings: Settings, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Поднимает локальный сервер до Ctrl+C."""
    worker = BrowserWorker(settings)
    Handler.worker = worker
    httpd = ThreadingHTTPServer((host, port), Handler)
    try:
        print(
            f"Интерфейс подбора: http://{host}:{port}/\n"
            f"Список желаний:    {settings.wishlist_file.resolve()}\n"
            f"Профиль браузера:  {settings.browser_profile}\n"
            "Остановить — Ctrl+C\n"
        )
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстанавливаю…")
    finally:
        httpd.server_close()
        worker.close()
