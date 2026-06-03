from __future__ import annotations
import os
from dataclasses import dataclass


class MissingConfig(Exception):
    pass


# Generic, bot-agnostic default. Override per deployment with the SYSTEM_PROMPT env var.
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant in Telegram. "
    "Answer the user's message directly and concisely."
)

# First-person persona for Secretary (Business) Mode. The bot replies AS the owner.
# Deliberately conservative: it must not commit the owner to payments, meetings, or promises.
DEFAULT_BUSINESS_SYSTEM_PROMPT = (
    "You are replying on behalf of the account owner, in the first person, as if you were them. "
    "Be polite, concise, and natural. Do NOT agree to payments, send money, make firm commitments, "
    "schedule meetings, or make promises on the owner's behalf — if asked, say you'll get back to them. "
    "If you are unsure or the request is sensitive, keep the reply brief and non-committal."
)


@dataclass(frozen=True)
class Config:
    bot_token: str
    groq_api_key: str
    webhook_domain: str
    webhook_secret: str
    bot_username: str
    groq_model: str = "llama-3.3-70b-versatile"
    ai_base_url: str = "https://api.groq.com/openai/v1/chat/completions"
    context_messages: int = 10
    db_path: str = "/data/memory.db"
    history_ttl_seconds: int = 86400
    port: int = 8080
    stream_interval: float = 1.0
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    business_system_prompt: str = DEFAULT_BUSINESS_SYSTEM_PROMPT

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
            ai_base_url=env.get("AI_BASE_URL", "https://api.groq.com/openai/v1/chat/completions"),
            context_messages=int(env.get("CONTEXT_MESSAGES", "10")),
            db_path=env.get("DB_PATH", "/data/memory.db"),
            history_ttl_seconds=int(env.get("HISTORY_TTL_SECONDS", "86400")),
            port=int(env.get("PORT", "8080")),
            stream_interval=float(env.get("STREAM_INTERVAL", "1.0")),
            system_prompt=env.get("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
            business_system_prompt=env.get("BUSINESS_SYSTEM_PROMPT", DEFAULT_BUSINESS_SYSTEM_PROMPT),
        )
