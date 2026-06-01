from __future__ import annotations
import logging
from typing import Awaitable, Callable
from aiohttp import web

log = logging.getLogger("tgbot.webhook")
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def create_app(handler: Callable[[dict], Awaitable[None]], secret: str) -> web.Application:
    async def webhook(request: web.Request) -> web.Response:
        if request.headers.get(SECRET_HEADER) != secret:
            return web.Response(status=403, text="forbidden")
        update = await request.json()
        try:
            await handler(update)
        except Exception:
            log.exception("handler failed")
        return web.Response(text="ok")

    async def health(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_post("/webhook", webhook)
    app.router.add_get("/health", health)
    return app
