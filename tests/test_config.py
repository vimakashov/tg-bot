import pytest
from bot.config import Config, MissingConfig, DEFAULT_SYSTEM_PROMPT


def _base_env():
    return {
        "BOT_TOKEN": "123:abc",
        "GROQ_API_KEY": "gsk_x",
        "WEBHOOK_DOMAIN": "bot.example.com",
        "WEBHOOK_SECRET": "s3cret",
        "BOT_USERNAME": "testbot",
    }


def test_loads_required_and_defaults():
    cfg = Config.from_env(_base_env())
    assert cfg.bot_token == "123:abc"
    assert cfg.groq_api_key == "gsk_x"
    assert cfg.webhook_domain == "bot.example.com"
    assert cfg.webhook_secret == "s3cret"
    assert cfg.bot_username == "testbot"
    # defaults
    assert cfg.groq_model == "llama-3.3-70b-versatile"
    assert cfg.context_messages == 10
    assert cfg.db_path == "/data/memory.db"
    assert cfg.history_ttl_seconds == 86400
    assert cfg.port == 8080
    assert cfg.stream_interval == 1.0
    assert cfg.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert cfg.ai_base_url == "https://api.groq.com/openai/v1/chat/completions"


def test_overrides_from_env():
    env = _base_env() | {"GROQ_MODEL": "llama-3.1-8b-instant", "CONTEXT_MESSAGES": "4",
                         "PORT": "9000", "SYSTEM_PROMPT": "You are a pirate.",
                         "AI_BASE_URL": "http://192.168.1.50:8080/v1/chat/completions"}
    cfg = Config.from_env(env)
    assert cfg.groq_model == "llama-3.1-8b-instant"
    assert cfg.context_messages == 4
    assert cfg.port == 9000
    assert cfg.system_prompt == "You are a pirate."
    assert cfg.ai_base_url == "http://192.168.1.50:8080/v1/chat/completions"


def test_missing_required_raises():
    env = _base_env()
    del env["BOT_TOKEN"]
    with pytest.raises(MissingConfig) as e:
        Config.from_env(env)
    assert "BOT_TOKEN" in str(e.value)
