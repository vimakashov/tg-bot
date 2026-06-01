# bot/main.py
from __future__ import annotations
import asyncio
import logging
from aiohttp import web
from dotenv import load_dotenv

from bot.config import Config
from bot.ai.groq_client import GroqClient
from bot.memory.store import MemoryStore
from bot.telegram.api import TelegramApi
from bot.telegram.guest import handle_guest_message
from bot.telegram.webhook import create_app

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tgbot")

PRUNE_INTERVAL_SECONDS = 3600


def build_app(config: Config) -> web.Application:
    store = MemoryStore(config.db_path)
    ai = GroqClient(config.groq_api_key, config.groq_model)
    api = TelegramApi(config.bot_token)

    async def handler(update: dict) -> None:
        await handle_guest_message(update, api, ai, store, config)

    app = create_app(handler, config.webhook_secret)

    async def prune_loop() -> None:
        while True:
            await asyncio.sleep(PRUNE_INTERVAL_SECONDS)
            try:
                await store.prune(config.history_ttl_seconds)
            except Exception:
                log.exception("Periodic prune failed")

    async def on_startup(app_: web.Application) -> None:
        await store.init()
        await store.prune(config.history_ttl_seconds)
        app_["prune_task"] = asyncio.create_task(prune_loop())
        webhook_url = f"https://{config.webhook_domain}/webhook"
        try:
            await api.set_webhook(webhook_url, config.webhook_secret)
            log.info("Webhook registered at %s", webhook_url)
        except Exception:
            log.exception("Failed to register webhook at %s", webhook_url)

    async def on_cleanup(app_: web.Application) -> None:
        task = app_.get("prune_task")
        if task is not None:
            task.cancel()
        await ai.close()
        await api.close()
        await store.close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    load_dotenv()
    config = Config.from_env()
    app = build_app(config)
    web.run_app(app, host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
