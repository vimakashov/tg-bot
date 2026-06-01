# bot/main.py
from __future__ import annotations
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
log = logging.getLogger("brainratbot")


def build_app(config: Config) -> web.Application:
    store = MemoryStore(config.db_path)
    ai = GroqClient(config.groq_api_key, config.groq_model)
    api = TelegramApi(config.bot_token)

    async def handler(update: dict) -> None:
        await handle_guest_message(update, api, ai, store, config)

    app = create_app(handler, config.webhook_secret)

    async def on_startup(_app: web.Application) -> None:
        await store.init()
        webhook_url = f"https://{config.webhook_domain}/webhook"
        try:
            await api.set_webhook(webhook_url, config.webhook_secret)
            log.info("Webhook registered at %s", webhook_url)
        except Exception:
            log.exception("Failed to register webhook at %s", webhook_url)

    async def on_cleanup(_app: web.Application) -> None:
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
