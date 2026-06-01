from __future__ import annotations
import os
from dataclasses import dataclass


class MissingConfig(Exception):
    pass


@dataclass(frozen=True)
class Config:
    bot_token: str
    groq_api_key: str
    webhook_domain: str
    webhook_secret: str
    bot_username: str
    groq_model: str = "llama-3.3-70b-versatile"
    context_messages: int = 10
    db_path: str = "/data/memory.db"
    history_ttl_seconds: int = 86400
    port: int = 8080
    stream_interval: float = 1.0

    @staticmethod
    def from_env(env: dict | None = None) -> "Config":
        env = dict(os.environ if env is None else env)
        required = ["BOT_TOKEN", "GROQ_API_KEY", "WEBHOOK_DOMAIN", "WEBHOOK_SECRET", "BOT_USERNAME"]
        missing = [k for k in required if not env.get(k)]
        if missing:
            raise MissingConfig(f"Missing required env vars: {', '.join(missing)}")
        return Config(
            bot_token=env["BOT_TOKEN"],
            groq_api_key=env["GROQ_API_KEY"],
            webhook_domain=env["WEBHOOK_DOMAIN"],
            webhook_secret=env["WEBHOOK_SECRET"],
            bot_username=env["BOT_USERNAME"].lstrip("@"),
            groq_model=env.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            context_messages=int(env.get("CONTEXT_MESSAGES", "10")),
            db_path=env.get("DB_PATH", "/data/memory.db"),
            history_ttl_seconds=int(env.get("HISTORY_TTL_SECONDS", "86400")),
            port=int(env.get("PORT", "8080")),
            stream_interval=float(env.get("STREAM_INTERVAL", "1.0")),
        )
