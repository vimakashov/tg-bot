# brainratbot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram Guest-Mode AI bot (`@brainratbot`) that streams Groq-generated replies, runs in webhook mode on a VPS, and starts/stops with one Docker Compose command.

**Architecture:** A small async Python service. An **aiohttp** server receives the Telegram webhook and dispatches `guest_message` updates to a handler. The handler loads short per-user history from **SQLite**, calls **Groq** (OpenAI-compatible streaming), throttles partial output into `sendMessageDraft` calls, and finalizes the reply with `answerGuestQuery`. **Caddy** terminates TLS in front of the bot. All Telegram Bot API calls go through a thin raw `TelegramApi` (httpx) client.

**Implementation note (deviation from spec wording):** The spec named *aiogram 3*. The Guest-Mode methods (`guest_message`, `answerGuestQuery`, `sendMessageDraft`) are not present in any released aiogram version, so this plan uses **aiohttp** (the same server layer aiogram is built on) for the webhook plus a **raw httpx Telegram client** for Bot API calls. This is fully compatible with adding aiogram later for member mode. No unused dependency is added (YAGNI).

**Tech Stack:** Python 3.12, aiohttp (webhook server), httpx (Groq + Telegram HTTP), SQLite (`sqlite3` stdlib via `aiosqlite` for async), pytest + pytest-asyncio + pytest-aiohttp (tests), Docker + Docker Compose, Caddy.

---

## File Structure

```
tg-bot/
├── bot/
│   ├── __init__.py
│   ├── config.py              # env loading, fail-fast validation
│   ├── ai/
│   │   ├── __init__.py
│   │   └── groq_client.py     # Groq streaming client + SSE parse
│   ├── memory/
│   │   ├── __init__.py
│   │   └── store.py           # SQLite last-N history store
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── api.py             # raw Telegram Bot API client (httpx)
│   │   ├── guest.py           # guest_message parse + handler + prompt build
│   │   └── webhook.py         # aiohttp app, secret-token check
│   ├── streaming.py           # throttled stream accumulator
│   └── main.py                # wiring, startup webhook registration, run
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_groq_client.py
│   ├── test_store.py
│   ├── test_streaming.py
│   ├── test_telegram_api.py
│   ├── test_guest.py
│   └── test_webhook.py
├── Dockerfile
├── docker-compose.yml
├── Caddyfile
├── requirements.txt
├── .env.example
├── .gitignore
├── pytest.ini
└── README.md
```

---

## Task 0: Project scaffolding

**Files:**
- Create: `.gitignore`, `requirements.txt`, `pytest.ini`, `bot/__init__.py`, `bot/ai/__init__.py`, `bot/memory/__init__.py`, `bot/telegram/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Initialize git**

```bash
cd /Users/mkv73-mini/Documents/Projects/github/tg-bot
git init
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
__pycache__/
*.pyc
.env
.venv/
venv/
*.db
*.sqlite3
data/
.pytest_cache/
caddy_data/
caddy_config/
```

- [ ] **Step 3: Create `requirements.txt`**

```
aiohttp==3.10.11
httpx==0.27.2
aiosqlite==0.20.0
python-dotenv==1.0.1
pytest==8.3.4
pytest-asyncio==0.24.0
pytest-aiohttp==1.0.5
```

- [ ] **Step 4: Create `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 5: Create empty package markers**

Create these files, each empty:
`bot/__init__.py`, `bot/ai/__init__.py`, `bot/memory/__init__.py`, `bot/telegram/__init__.py`, `tests/__init__.py`

- [ ] **Step 6: Create virtualenv and install**

Run:
```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```
Expected: installs succeed.

- [ ] **Step 7: Commit**

```bash
git add .gitignore requirements.txt pytest.ini bot tests
git commit -m "chore: project scaffolding"
```

---

## Task 1: Config loading

**Files:**
- Create: `bot/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from bot.config import Config, MissingConfig


def _base_env():
    return {
        "BOT_TOKEN": "123:abc",
        "GROQ_API_KEY": "gsk_x",
        "WEBHOOK_DOMAIN": "bot.example.com",
        "WEBHOOK_SECRET": "s3cret",
        "BOT_USERNAME": "brainratbot",
    }


def test_loads_required_and_defaults():
    cfg = Config.from_env(_base_env())
    assert cfg.bot_token == "123:abc"
    assert cfg.groq_api_key == "gsk_x"
    assert cfg.webhook_domain == "bot.example.com"
    assert cfg.webhook_secret == "s3cret"
    assert cfg.bot_username == "brainratbot"
    # defaults
    assert cfg.groq_model == "llama-3.3-70b-versatile"
    assert cfg.context_messages == 10
    assert cfg.db_path == "/data/memory.db"
    assert cfg.history_ttl_seconds == 86400
    assert cfg.port == 8080
    assert cfg.stream_interval == 1.0


def test_overrides_from_env():
    env = _base_env() | {"GROQ_MODEL": "llama-3.1-8b-instant", "CONTEXT_MESSAGES": "4", "PORT": "9000"}
    cfg = Config.from_env(env)
    assert cfg.groq_model == "llama-3.1-8b-instant"
    assert cfg.context_messages == 4
    assert cfg.port == 9000


def test_missing_required_raises():
    env = _base_env()
    del env["BOT_TOKEN"]
    with pytest.raises(MissingConfig) as e:
        Config.from_env(env)
    assert "BOT_TOKEN" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.config'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/config.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/config.py tests/test_config.py
git commit -m "feat: config loading with fail-fast validation"
```

---

## Task 2: Memory store (SQLite last-N history)

**Files:**
- Create: `bot/memory/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_store.py
import time
import pytest
from bot.memory.store import MemoryStore


@pytest.fixture
async def store(tmp_path):
    s = MemoryStore(str(tmp_path / "m.db"))
    await s.init()
    yield s
    await s.close()


async def test_append_and_get_history_in_order(store):
    await store.append(1, 100, "user", "hello")
    await store.append(1, 100, "assistant", "hi there")
    await store.append(1, 100, "user", "how are you")
    hist = await store.get_history(1, 100, limit=10)
    assert hist == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
        {"role": "user", "content": "how are you"},
    ]


async def test_history_is_scoped_per_user_and_chat(store):
    await store.append(1, 100, "user", "a")
    await store.append(1, 200, "user", "b")
    await store.append(2, 100, "user", "c")
    assert await store.get_history(1, 100, 10) == [{"role": "user", "content": "a"}]
    assert await store.get_history(1, 200, 10) == [{"role": "user", "content": "b"}]


async def test_get_history_returns_last_n(store):
    for i in range(5):
        await store.append(1, 100, "user", f"m{i}")
    hist = await store.get_history(1, 100, limit=2)
    assert hist == [{"role": "user", "content": "m3"}, {"role": "user", "content": "m4"}]


async def test_prune_removes_expired(store):
    old = time.time() - 10_000
    await store.append(1, 100, "user", "old", created_at=old)
    await store.append(1, 100, "user", "new")
    await store.prune(ttl_seconds=5000)
    hist = await store.get_history(1, 100, 10)
    assert hist == [{"role": "user", "content": "new"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.memory.store'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/memory/store.py
from __future__ import annotations
import time
import aiosqlite


class MemoryStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_scope ON messages (chat_id, user_id, id)"
        )
        await self._db.commit()

    async def append(self, chat_id: int, user_id: int, role: str, content: str,
                     created_at: float | None = None) -> None:
        ts = time.time() if created_at is None else created_at
        await self._db.execute(
            "INSERT INTO messages (chat_id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, user_id, role, content, ts),
        )
        await self._db.commit()

    async def get_history(self, chat_id: int, user_id: int, limit: int) -> list[dict]:
        cur = await self._db.execute(
            "SELECT role, content FROM messages WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, user_id, limit),
        )
        rows = await cur.fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    async def prune(self, ttl_seconds: int) -> None:
        cutoff = time.time() - ttl_seconds
        await self._db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/memory/store.py tests/test_store.py
git commit -m "feat: SQLite short-context memory store"
```

---

## Task 3: Groq streaming client

**Files:**
- Create: `bot/ai/groq_client.py`
- Test: `tests/test_groq_client.py`

- [ ] **Step 1: Write the failing test for SSE parsing**

```python
# tests/test_groq_client.py
import httpx
import pytest
from bot.ai.groq_client import parse_sse_line, GroqClient, AIError


def test_parse_sse_line_extracts_content():
    line = 'data: {"choices":[{"delta":{"content":"Hel"}}]}'
    assert parse_sse_line(line) == "Hel"


def test_parse_sse_line_done_returns_none():
    assert parse_sse_line("data: [DONE]") is None


def test_parse_sse_line_blank_or_no_content_returns_none():
    assert parse_sse_line("") is None
    assert parse_sse_line('data: {"choices":[{"delta":{}}]}') is None
```

- [ ] **Step 2: Write the failing test for the streaming client**

Append to `tests/test_groq_client.py`:

```python
async def test_stream_completion_yields_chunks():
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        'data: [DONE]\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer gsk_test"
        payload = request.read()
        assert b'"stream": true' in payload or b'"stream":true' in payload
        return httpx.Response(200, text=sse_body)

    transport = httpx.MockTransport(handler)
    client = GroqClient("gsk_test", "llama-3.3-70b-versatile",
                        http_client=httpx.AsyncClient(transport=transport))
    chunks = [c async for c in client.stream_completion([{"role": "user", "content": "hi"}])]
    assert "".join(chunks) == "Hello world"
    await client.close()


async def test_stream_completion_raises_on_http_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    client = GroqClient("gsk_test", "m", http_client=httpx.AsyncClient(transport=transport))
    with pytest.raises(AIError):
        async for _ in client.stream_completion([{"role": "user", "content": "hi"}]):
            pass
    await client.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_groq_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.ai.groq_client'`

- [ ] **Step 4: Write minimal implementation**

```python
# bot/ai/groq_client.py
from __future__ import annotations
import json
from typing import AsyncIterator
import httpx

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class AIError(Exception):
    pass


def parse_sse_line(line: str) -> str | None:
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    data = line[len("data:"):].strip()
    if data == "[DONE]":
        return None
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return None
    try:
        return obj["choices"][0]["delta"].get("content") or None
    except (KeyError, IndexError):
        return None


class GroqClient:
    def __init__(self, api_key: str, model: str, http_client: httpx.AsyncClient | None = None):
        self._api_key = api_key
        self._model = model
        self._client = http_client or httpx.AsyncClient(timeout=60)

    async def stream_completion(self, messages: list[dict]) -> AsyncIterator[str]:
        payload = {"model": self._model, "messages": messages, "stream": True}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with self._client.stream("POST", GROQ_URL, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise AIError(f"Groq HTTP {resp.status_code}: {body[:200]!r}")
                async for line in resp.aiter_lines():
                    content = parse_sse_line(line)
                    if content:
                        yield content
        except httpx.HTTPError as e:
            raise AIError(f"Groq request failed: {e}") from e

    async def close(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_groq_client.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add bot/ai/groq_client.py tests/test_groq_client.py
git commit -m "feat: Groq streaming client with SSE parsing"
```

---

## Task 4: Throttled stream accumulator

**Files:**
- Create: `bot/streaming.py`
- Test: `tests/test_streaming.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_streaming.py
from bot.streaming import stream_with_throttle


async def _agen(items):
    for i in items:
        yield i


async def test_returns_full_concatenated_text():
    full = await stream_with_throttle(_agen(["a", "b", "c"]), on_update=lambda _t: _noop(),
                                      min_interval=0.0, clock=_fake_clock([0, 0, 0]))
    assert full == "abc"


async def _noop():
    return None


def _fake_clock(times):
    seq = iter(times)
    return lambda: next(seq)


async def test_throttles_updates_by_interval():
    calls = []

    async def on_update(text):
        calls.append(text)

    # clock returns one value per chunk; interval=1.0
    # times: chunk1 t=0 (first -> emit), chunk2 t=0.5 (skip), chunk3 t=1.0 (emit)
    full = await stream_with_throttle(
        _agen(["a", "b", "c"]), on_update=on_update,
        min_interval=1.0, clock=_fake_clock([0.0, 0.5, 1.0]),
    )
    assert full == "abc"
    assert calls == ["a", "abc"]  # accumulated text at each emit point


async def test_first_chunk_always_emits():
    calls = []

    async def on_update(text):
        calls.append(text)

    full = await stream_with_throttle(
        _agen(["x"]), on_update=on_update, min_interval=999.0, clock=_fake_clock([0.0]),
    )
    assert full == "x"
    assert calls == ["x"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_streaming.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.streaming'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/streaming.py
from __future__ import annotations
import time
from typing import AsyncIterator, Awaitable, Callable


async def stream_with_throttle(
    chunks: AsyncIterator[str],
    on_update: Callable[[str], Awaitable[None]],
    min_interval: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Consume `chunks`, calling `on_update(accumulated_text)` at most once per
    `min_interval` seconds (the first chunk always emits). Returns the full text.
    on_update errors are swallowed so a failed draft never aborts generation."""
    buffer = ""
    last_emit: float | None = None
    async for chunk in chunks:
        buffer += chunk
        now = clock()
        if last_emit is None or (now - last_emit) >= min_interval:
            try:
                await on_update(buffer)
            except Exception:
                pass
            last_emit = now
    return buffer
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_streaming.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/streaming.py tests/test_streaming.py
git commit -m "feat: throttled stream accumulator"
```

---

## Task 5: Raw Telegram API client

**Files:**
- Create: `bot/telegram/api.py`
- Test: `tests/test_telegram_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telegram_api.py
import httpx
import pytest
from bot.telegram.api import TelegramApi, TelegramError


def _ok(result=True):
    return {"ok": True, "result": result}


async def test_answer_guest_query_posts_expected():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok({"message_id": 5}))

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    res = await api.answer_guest_query("q1", "hello")
    assert res == {"message_id": 5}
    assert seen["url"].endswith("/bot123:abc/answerGuestQuery")
    assert b"q1" in seen["json"] and b"hello" in seen["json"]
    await api.close()


async def test_send_message_draft_includes_guest_query_id():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok())

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.send_message_draft(chat_id=42, text="partial", guest_query_id="q1")
    assert seen["url"].endswith("/sendMessageDraft")
    assert b'"q1"' in seen["json"]
    await api.close()


async def test_set_webhook_posts_url_and_secret():
    seen = {}

    def handler(request):
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok())

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.set_webhook("https://bot.example.com/webhook", "s3cret")
    assert b"bot.example.com/webhook" in seen["json"]
    assert b"s3cret" in seen["json"]
    assert b"guest_message" in seen["json"]
    await api.close()


async def test_raises_on_not_ok():
    def handler(request):
        return httpx.Response(200, json={"ok": False, "description": "bad"})

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(TelegramError):
        await api.answer_guest_query("q1", "hi")
    await api.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_telegram_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.telegram.api'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/telegram/api.py
from __future__ import annotations
import httpx


class TelegramError(Exception):
    pass


class TelegramApi:
    def __init__(self, token: str, http_client: httpx.AsyncClient | None = None):
        self._base = f"https://api.telegram.org/bot{token}"
        self._client = http_client or httpx.AsyncClient(timeout=30)

    async def call(self, method: str, **params) -> object:
        payload = {k: v for k, v in params.items() if v is not None}
        try:
            resp = await self._client.post(f"{self._base}/{method}", json=payload)
        except httpx.HTTPError as e:
            raise TelegramError(f"{method} request failed: {e}") from e
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"{method} failed: {data.get('description')}")
        return data["result"]

    async def answer_guest_query(self, guest_query_id: str, text: str) -> object:
        return await self.call("answerGuestQuery", guest_query_id=guest_query_id, text=text)

    async def send_message_draft(self, chat_id: int, text: str,
                                 guest_query_id: str | None = None) -> object:
        return await self.call("sendMessageDraft", chat_id=chat_id, text=text,
                               guest_query_id=guest_query_id)

    async def set_webhook(self, url: str, secret_token: str) -> object:
        return await self.call("setWebhook", url=url, secret_token=secret_token,
                               allowed_updates=["guest_message", "message"])

    async def close(self) -> None:
        await self._client.aclose()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_telegram_api.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add bot/telegram/api.py tests/test_telegram_api.py
git commit -m "feat: raw Telegram Bot API client (guest methods)"
```

---

## Task 6: Guest message parsing, prompt building, and handler

**Files:**
- Create: `bot/telegram/guest.py`
- Test: `tests/test_guest.py`

> **API-shape note for the implementer:** The exact JSON shape of `guest_message` is new.
> This task assumes `update["guest_message"]` is a Message object with: `chat.id`, `from.id`,
> `text`, `guest_query_id`, and optional `reply_to_message.text`. Verify against the live API
> and adjust `parse_guest_message` if fields differ — the rest of the handler depends only on
> the `GuestMessage` dataclass, so changes stay localized.

- [ ] **Step 1: Write the failing test for parsing + mention stripping + prompt build**

```python
# tests/test_guest.py
import pytest
from bot.telegram.guest import (
    GuestMessage, parse_guest_message, strip_bot_mention, build_messages, handle_guest_message,
    SYSTEM_PROMPT, FALLBACK_TEXT,
)


def _update(text="@brainratbot hello", reply=None):
    gm = {
        "guest_query_id": "q1",
        "chat": {"id": 42},
        "from": {"id": 7},
        "text": text,
    }
    if reply is not None:
        gm["reply_to_message"] = {"text": reply}
    return {"guest_message": gm}


def test_parse_returns_none_for_non_guest_update():
    assert parse_guest_message({"message": {"text": "hi"}}) is None


def test_parse_extracts_fields():
    gm = parse_guest_message(_update(reply="context here"))
    assert gm == GuestMessage(query_id="q1", chat_id=42, user_id=7,
                              text="@brainratbot hello", reply_text="context here")


def test_strip_bot_mention():
    assert strip_bot_mention("@brainratbot hello there", "brainratbot") == "hello there"
    assert strip_bot_mention("hey @BrainRatBot what's up", "brainratbot") == "hey what's up"
    assert strip_bot_mention("no mention", "brainratbot") == "no mention"


def test_build_messages_includes_system_history_reply_and_user():
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "ok"}]
    msgs = build_messages(history, "what is 2+2", reply_text="the math question")
    assert msgs[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert msgs[1:3] == history
    assert msgs[-1]["role"] == "user"
    assert "what is 2+2" in msgs[-1]["content"]
    assert "the math question" in msgs[-1]["content"]
```

- [ ] **Step 2: Write the failing test for the handler (with fakes)**

Append to `tests/test_guest.py`:

```python
class FakeStore:
    def __init__(self, history=None):
        self._history = history or []
        self.appended = []

    async def get_history(self, chat_id, user_id, limit):
        return list(self._history)

    async def append(self, chat_id, user_id, role, content):
        self.appended.append((role, content))


class FakeAI:
    def __init__(self, chunks=None, error=None):
        self._chunks = chunks or []
        self._error = error

    async def stream_completion(self, messages):
        if self._error:
            raise self._error
        for c in self._chunks:
            yield c


class FakeApi:
    def __init__(self):
        self.drafts = []
        self.answers = []

    async def send_message_draft(self, chat_id, text, guest_query_id=None):
        self.drafts.append((chat_id, text, guest_query_id))

    async def answer_guest_query(self, guest_query_id, text):
        self.answers.append((guest_query_id, text))


class Cfg:
    bot_username = "brainratbot"
    context_messages = 10
    stream_interval = 0.0


async def test_handler_streams_and_finalizes():
    store, ai, api = FakeStore(), FakeAI(["Hel", "lo!"]), FakeApi()
    await handle_guest_message(_update("@brainratbot hi"), api, ai, store, Cfg())
    assert api.answers == [("q1", "Hello!")]
    assert api.drafts  # at least one draft emitted
    assert store.appended == [("user", "hi"), ("assistant", "Hello!")]


async def test_handler_ignores_non_guest_update():
    store, ai, api = FakeStore(), FakeAI(["x"]), FakeApi()
    await handle_guest_message({"message": {}}, api, ai, store, Cfg())
    assert api.answers == []


async def test_handler_sends_fallback_on_ai_error():
    store, ai, api = FakeStore(), FakeAI(error=RuntimeError("groq down")), FakeApi()
    await handle_guest_message(_update("@brainratbot hi"), api, ai, store, Cfg())
    assert api.answers == [("q1", FALLBACK_TEXT)]


async def test_handler_truncates_to_4096():
    store, ai, api = FakeStore(), FakeAI(["x" * 5000]), FakeApi()
    await handle_guest_message(_update("@brainratbot hi"), api, ai, store, Cfg())
    qid, text = api.answers[0]
    assert len(text) == 4096
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_guest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.telegram.guest'`

- [ ] **Step 4: Write minimal implementation**

```python
# bot/telegram/guest.py
from __future__ import annotations
import re
from dataclasses import dataclass

from bot.streaming import stream_with_throttle

TELEGRAM_MAX = 4096
SYSTEM_PROMPT = (
    "You are @brainratbot, a concise, helpful AI assistant inside Telegram. "
    "Answer the user's message directly and clearly."
)
FALLBACK_TEXT = "⚠️ AI is unavailable right now, please try again in a moment."


@dataclass(frozen=True)
class GuestMessage:
    query_id: str
    chat_id: int
    user_id: int
    text: str
    reply_text: str | None = None


def parse_guest_message(update: dict) -> GuestMessage | None:
    gm = update.get("guest_message")
    if not gm:
        return None
    reply = gm.get("reply_to_message") or {}
    return GuestMessage(
        query_id=gm["guest_query_id"],
        chat_id=gm["chat"]["id"],
        user_id=gm["from"]["id"],
        text=gm.get("text", ""),
        reply_text=reply.get("text"),
    )


def strip_bot_mention(text: str, bot_username: str) -> str:
    cleaned = re.sub(rf"@{re.escape(bot_username)}\b", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def build_messages(history: list[dict], user_text: str, reply_text: str | None) -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    if reply_text:
        content = f'Context (message the user replied to): "{reply_text}"\n\nUser: {user_text}'
    else:
        content = user_text
    messages.append({"role": "user", "content": content})
    return messages


async def handle_guest_message(update: dict, api, ai, store, config) -> None:
    gm = parse_guest_message(update)
    if gm is None:
        return
    user_text = strip_bot_mention(gm.text, config.bot_username)
    history = await store.get_history(gm.chat_id, gm.user_id, config.context_messages)
    messages = build_messages(history, user_text, gm.reply_text)

    async def on_update(partial: str) -> None:
        await api.send_message_draft(gm.chat_id, partial[:TELEGRAM_MAX], gm.query_id)

    try:
        full = await stream_with_throttle(
            ai.stream_completion(messages), on_update,
            min_interval=config.stream_interval,
        )
    except Exception:
        full = ""

    reply = (full[:TELEGRAM_MAX]) if full else FALLBACK_TEXT
    await api.answer_guest_query(gm.query_id, reply)

    if full:
        await store.append(gm.chat_id, gm.user_id, "user", user_text)
        await store.append(gm.chat_id, gm.user_id, "assistant", full)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_guest.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Commit**

```bash
git add bot/telegram/guest.py tests/test_guest.py
git commit -m "feat: guest_message parsing, prompt build, streaming handler"
```

---

## Task 7: Webhook server (aiohttp + secret-token check)

**Files:**
- Create: `bot/telegram/webhook.py`
- Test: `tests/test_webhook.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_webhook.py
import pytest
from bot.telegram.webhook import create_app


@pytest.fixture
def received():
    return []


@pytest.fixture
def app(received):
    async def handler(update):
        received.append(update)
    return create_app(handler, secret="s3cret")


async def test_rejects_missing_secret(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.post("/webhook", json={"guest_message": {}})
    assert resp.status == 403


async def test_rejects_wrong_secret(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.post("/webhook", json={"x": 1},
                             headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
    assert resp.status == 403


async def test_accepts_valid_secret_and_dispatches(aiohttp_client, app, received):
    client = await aiohttp_client(app)
    resp = await client.post("/webhook", json={"guest_message": {"id": 1}},
                             headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert resp.status == 200
    assert received == [{"guest_message": {"id": 1}}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhook.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.telegram.webhook'`

- [ ] **Step 3: Write minimal implementation**

```python
# bot/telegram/webhook.py
from __future__ import annotations
import logging
from typing import Awaitable, Callable
from aiohttp import web

log = logging.getLogger("brainratbot.webhook")
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_webhook.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: PASS (all tests across all files green)

- [ ] **Step 6: Commit**

```bash
git add bot/telegram/webhook.py tests/test_webhook.py
git commit -m "feat: aiohttp webhook server with secret-token verification"
```

---

## Task 8: Application wiring (`main.py`)

**Files:**
- Create: `bot/main.py`

> This module wires components together and runs the server. It is exercised end-to-end by the
> deployment (Task 11 smoke test) rather than unit tests, since it only composes already-tested
> units and calls `web.run_app`.

- [ ] **Step 1: Write `bot/main.py`**

```python
# bot/main.py
from __future__ import annotations
import asyncio
import logging
from functools import partial
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


async def build_runtime(config: Config):
    store = MemoryStore(config.db_path)
    await store.init()
    ai = GroqClient(config.groq_api_key, config.groq_model)
    api = TelegramApi(config.bot_token)

    async def handler(update: dict) -> None:
        await handle_guest_message(update, api, ai, store, config)

    app = create_app(handler, config.webhook_secret)

    async def on_startup(_app):
        webhook_url = f"https://{config.webhook_domain}/webhook"
        await api.set_webhook(webhook_url, config.webhook_secret)
        log.info("Webhook registered at %s", webhook_url)

    async def on_cleanup(_app):
        await ai.close()
        await api.close()
        await store.close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    load_dotenv()
    config = Config.from_env()
    app = asyncio.get_event_loop().run_until_complete(build_runtime(config))
    web.run_app(app, host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports and fails fast without env**

Run: `python -c "import bot.main"`
Expected: no output, exit 0 (import succeeds; `main()` not called).

- [ ] **Step 3: Verify fail-fast on missing env**

Run: `python -m bot.main`
Expected: FAIL with `MissingConfig: Missing required env vars: BOT_TOKEN, GROQ_API_KEY, WEBHOOK_DOMAIN, WEBHOOK_SECRET, BOT_USERNAME`

- [ ] **Step 4: Commit**

```bash
git add bot/main.py
git commit -m "feat: application wiring and webhook registration on startup"
```

---

## Task 9: Containerization (Dockerfile, Compose, Caddy)

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `Caddyfile`, `.env.example`

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
RUN mkdir -p /data
EXPOSE 8080
CMD ["python", "-m", "bot.main"]
```

- [ ] **Step 2: Create `Caddyfile`**

```
{$WEBHOOK_DOMAIN} {
    reverse_proxy bot:8080
}
```

- [ ] **Step 3: Create `docker-compose.yml`**

```yaml
services:
  bot:
    build: .
    env_file: .env
    volumes:
      - ./data:/data
    expose:
      - "8080"
    restart: unless-stopped

  caddy:
    image: caddy:2.8-alpine
    depends_on:
      - bot
    ports:
      - "80:80"
      - "443:443"
    environment:
      WEBHOOK_DOMAIN: ${WEBHOOK_DOMAIN}
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./caddy_data:/data
      - ./caddy_config:/config
    restart: unless-stopped
```

- [ ] **Step 4: Create `.env.example`**

```env
# Telegram bot token from BotFather (KEEP SECRET — never commit the real one)
BOT_TOKEN=123456:replace-me
# Bot username without @ (used to strip the mention from guest messages)
BOT_USERNAME=brainratbot
# Groq API key from https://console.groq.com (free tier)
GROQ_API_KEY=gsk_replace-me
# Public domain whose A-record points at this VPS (used for HTTPS + webhook URL)
WEBHOOK_DOMAIN=bot.example.com
# Random string Telegram echoes back in the X-Telegram-Bot-Api-Secret-Token header
WEBHOOK_SECRET=change-me-to-a-long-random-string
# Optional overrides
GROQ_MODEL=llama-3.3-70b-versatile
CONTEXT_MESSAGES=10
DB_PATH=/data/memory.db
PORT=8080
```

- [ ] **Step 5: Validate compose file syntax**

Run: `docker compose config`
Expected: prints the resolved config with no errors (requires a `.env` present; create one from `.env.example` with dummy values if needed for this check).

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml Caddyfile .env.example
git commit -m "feat: Docker Compose + Caddy deployment"
```

---

## Task 10: README with run/stop instructions and ports

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

````markdown
# brainratbot

AI Telegram bot answering via **Guest Mode**: mention `@brainratbot <question>` in any
private chat or group and it streams a Groq-generated reply. Runs in webhook mode behind
Caddy (automatic HTTPS) via Docker Compose.

## Prerequisites

- A VPS with Docker + Docker Compose.
- A domain whose **A-record points at the VPS IP** (e.g. `bot.example.com`).
- **Guest Mode enabled** for the bot in BotFather's MiniApp.
- A free **Groq API key** from https://console.groq.com.

## Ports (open these in the VPS firewall)

| Port | Service | Purpose |
|------|---------|---------|
| 443  | Caddy   | Public HTTPS — receives the Telegram webhook |
| 80   | Caddy   | Let's Encrypt ACME HTTP challenge (cert issuance/renewal) |
| 8080 | bot     | **Internal only** (Docker network) — not published to the host |

## Setup

```bash
git clone <repo> && cd tg-bot
cp .env.example .env
# edit .env: BOT_TOKEN, GROQ_API_KEY, WEBHOOK_DOMAIN, WEBHOOK_SECRET, BOT_USERNAME
```

> ⚠️ **Security:** never commit `.env`. If your token was ever shared in plaintext,
> regenerate it in BotFather first.

## Start (one command)

```bash
docker compose up -d
```

This builds the bot, starts Caddy (which obtains a TLS cert for `WEBHOOK_DOMAIN`), and the
bot registers its webhook with Telegram on startup.

## Stop

```bash
docker compose down
```

## Logs

```bash
docker compose logs -f bot
docker compose logs -f caddy
```

## Verify

```bash
curl https://<WEBHOOK_DOMAIN>/health   # -> ok
```

Then mention `@brainratbot hello` in any chat where Guest Mode is allowed.

## Architecture

`Telegram → Caddy (443, TLS) → bot (aiohttp, 8080) → Groq (stream) + SQLite (memory)`

See `docs/superpowers/specs/2026-06-01-brainratbot-design.md` for the full design.

## Running tests

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest -v
```
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with ports, run/stop, and setup"
```

---

## Task 11: Full-suite green + local smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `pytest -v`
Expected: all tests PASS, no warnings about un-awaited coroutines.

- [ ] **Step 2: Build the image**

Run: `docker compose build`
Expected: image builds successfully.

- [ ] **Step 3: Local container smoke test (no real webhook)**

Run:
```bash
docker run --rm -e BOT_TOKEN=x -e BOT_USERNAME=brainratbot -e GROQ_API_KEY=x \
  -e WEBHOOK_DOMAIN=localhost -e WEBHOOK_SECRET=s -e PORT=8080 -p 8080:8080 \
  $(docker compose config --images | head -1) &
sleep 3
curl -s localhost:8080/health
```
Expected: `ok` (the startup `setWebhook` call to Telegram will log an error with the fake
token — that is expected; the server itself stays up and `/health` responds). Stop with
`docker stop` / Ctrl-C.

- [ ] **Step 4: Final commit / tag**

```bash
git add -A
git commit -m "chore: verified full suite + container smoke test" --allow-empty
```

---

## Self-Review Notes (already applied)

- **Spec coverage:** Guest parsing/handler (Task 6) ↔ spec §2/§6; streaming throttle (Task 4) + draft calls (Tasks 5–6) ↔ §5/§6 incl. fallback; Groq client (Task 3) ↔ §5; SQLite memory (Task 2) ↔ §5; secret-token check (Task 7) + `.env`/`.env.example` (Tasks 0/9) ↔ §8; Caddy/Compose/ports (Tasks 9–10) ↔ §4/§9; error handling (Task 6: AI fallback, 4096 truncation; Task 7: 403) ↔ §7; tests ↔ §10. Threads (§2/§11) intentionally deferred per "opportunistic / out of scope".
- **Type consistency:** `GuestMessage`, `Config`, `stream_with_throttle`, `TelegramApi.{answer_guest_query,send_message_draft,set_webhook}`, `GroqClient.stream_completion`, `MemoryStore.{get_history,append}` are named identically wherever referenced.
- **No placeholders:** every code step contains complete code; the only "verify against live API" notes are the deliberate, spec-mandated caveats around the brand-new Guest-Mode JSON shape, isolated to `parse_guest_message`.
- **Rate-limit/backoff (§7):** basic handling is present (errors → fallback; draft errors swallowed). Full exponential backoff on Telegram 429s is a reasonable enhancement but kept minimal here to honor YAGNI; add if observed in production.
