# Secretary (Business) Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Telegram Business "secretary" mode to the existing Guest-Mode bot — the bot replies on the owner's behalf, in the owner's voice, to incoming private 1:1 messages in chats the owner has connected via Telegram Business.

**Architecture:** A new `bot/telegram/business.py` mirrors the guest module: two pure parse functions (the only places that encode the Business JSON shape), plus `handle_business_connection` (persists connection records) and `handle_business_message` (autopilot reply via Groq). A new update-type dispatcher in `main.py` routes `business_connection` / `business_message` / `guest_message` updates. Connections and per-conversation history live in two new SQLite tables, keyed by `(connection_id, chat_id)`, leaving the guest `messages` table untouched. Replies go out via `sendMessage` with a `business_connection_id`. AI failure → stay silent (never send a fake message as the owner).

**Tech Stack:** Python 3.12 (Docker) / 3.9 (local `.venv`), aiohttp webhook, httpx Bot API client, aiosqlite, Groq OpenAI-compatible streaming, pytest (`asyncio_mode=auto`).

**Source spec:** `docs/superpowers/specs/2026-06-03-secretary-mode-design.md`

---

## File Structure

**New files:**
- `bot/telegram/business.py` — Secretary-mode core. `BusinessConnection` / `BusinessMessage` dataclasses, `parse_business_connection`, `parse_business_message` (the only encoders of the Business JSON shape), `handle_business_connection`, `handle_business_message`. Reuses `build_messages` and `TELEGRAM_MAX` from `guest.py` (DRY).
- `tests/test_business.py` — unit + behavioral tests for the parsers and both handlers.

**Modified files:**
- `bot/config.py` — add `DEFAULT_BUSINESS_SYSTEM_PROMPT` and the `business_system_prompt` field (env `BUSINESS_SYSTEM_PROMPT`). No new required vars.
- `bot/memory/store.py` — add `business_connections` and `business_messages` tables; `upsert_connection` / `get_connection` / `delete_connection` / `append_business` / `get_business_history`; extend `prune` to clean `business_messages`.
- `bot/telegram/api.py` — add `send_business_message`; extend `set_webhook` `allowed_updates` with `business_connection` and `business_message`.
- `bot/main.py` — add a module-level `dispatch(update, …)` that routes by update type; wire it into the `handler` closure.
- `tests/test_store.py`, `tests/test_telegram_api.py`, `tests/test_config.py` — extend with the new behavior.
- `tests/test_main_dispatch.py` (new) — tests for the dispatcher.
- `.env.example`, `README.md`, `CLAUDE.md` — document `BUSINESS_SYSTEM_PROMPT` and the new mode.

**Note on Serena:** CLAUDE.md asks for Serena MCP tools for code edits. The plan shows the exact final code for each symbol; apply it with `serena.replace_symbol_body` / `serena.insert_after_symbol` / `serena.create_text_file` where it fits, or plain Edit/Write if Serena is unavailable. Either way the resulting code must match the blocks below exactly.

---

## Task 1: Config — `BUSINESS_SYSTEM_PROMPT`

**Files:**
- Modify: `bot/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py` (the import line at top becomes
`from bot.config import Config, MissingConfig, DEFAULT_SYSTEM_PROMPT, DEFAULT_BUSINESS_SYSTEM_PROMPT`):

```python
def test_business_system_prompt_default():
    cfg = Config.from_env(_base_env())
    assert cfg.business_system_prompt == DEFAULT_BUSINESS_SYSTEM_PROMPT


def test_business_system_prompt_override():
    env = _base_env() | {"BUSINESS_SYSTEM_PROMPT": "Reply as me, briefly."}
    cfg = Config.from_env(env)
    assert cfg.business_system_prompt == "Reply as me, briefly."
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_config.py::test_business_system_prompt_default tests/test_config.py::test_business_system_prompt_override -v`
Expected: FAIL — `ImportError: cannot import name 'DEFAULT_BUSINESS_SYSTEM_PROMPT'`.

- [ ] **Step 3: Implement**

In `bot/config.py`, after the `DEFAULT_SYSTEM_PROMPT` block, add:

```python
# First-person persona for Secretary (Business) Mode. The bot replies AS the owner.
# Deliberately conservative: it must not commit the owner to payments, meetings, or promises.
DEFAULT_BUSINESS_SYSTEM_PROMPT = (
    "You are replying on behalf of the account owner, in the first person, as if you were them. "
    "Be polite, concise, and natural. Do NOT agree to payments, send money, make firm commitments, "
    "schedule meetings, or make promises on the owner's behalf — if asked, say you'll get back to them. "
    "If you are unsure or the request is sensitive, keep the reply brief and non-committal."
)
```

In the `Config` dataclass, add the field after `system_prompt`:

```python
    business_system_prompt: str = DEFAULT_BUSINESS_SYSTEM_PROMPT
```

In `from_env`, add to the `Config(...)` constructor call (after the `system_prompt=...` line):

```python
            business_system_prompt=env.get("BUSINESS_SYSTEM_PROMPT", DEFAULT_BUSINESS_SYSTEM_PROMPT),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (all config tests, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add bot/config.py tests/test_config.py
git commit -m "feat(config): add BUSINESS_SYSTEM_PROMPT for secretary mode"
```

---

## Task 2: Store — `business_connections` table

**Files:**
- Modify: `bot/memory/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_store.py`:

```python
async def test_upsert_and_get_connection(store):
    await store.upsert_connection("conn1", owner_user_id=555, can_reply=True, is_enabled=True)
    conn = await store.get_connection("conn1")
    assert conn == {"connection_id": "conn1", "owner_user_id": 555,
                    "can_reply": True, "is_enabled": True}


async def test_get_connection_missing_returns_none(store):
    assert await store.get_connection("nope") is None


async def test_upsert_connection_overwrites(store):
    await store.upsert_connection("conn1", owner_user_id=555, can_reply=True, is_enabled=True)
    await store.upsert_connection("conn1", owner_user_id=555, can_reply=False, is_enabled=False)
    conn = await store.get_connection("conn1")
    assert conn["can_reply"] is False
    assert conn["is_enabled"] is False
    assert conn["owner_user_id"] == 555


async def test_delete_connection(store):
    await store.upsert_connection("conn1", owner_user_id=555, can_reply=True, is_enabled=True)
    await store.delete_connection("conn1")
    assert await store.get_connection("conn1") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_store.py::test_upsert_and_get_connection -v`
Expected: FAIL — `AttributeError: 'MemoryStore' object has no attribute 'upsert_connection'`.

- [ ] **Step 3: Implement**

In `bot/memory/store.py`, inside `init()`, after the existing `idx_scope` index creation and before `await self._db.commit()`, add the table + index:

```python
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS business_connections (
                connection_id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                can_reply INTEGER NOT NULL,
                is_enabled INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
```

Add these methods to the `MemoryStore` class (place them after `clear`):

```python
    async def upsert_connection(self, connection_id: str, owner_user_id: int,
                                can_reply: bool, is_enabled: bool,
                                updated_at: float | None = None) -> None:
        ts = time.time() if updated_at is None else updated_at
        await self._db.execute(
            """
            INSERT INTO business_connections
                (connection_id, owner_user_id, can_reply, is_enabled, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(connection_id) DO UPDATE SET
                owner_user_id=excluded.owner_user_id,
                can_reply=excluded.can_reply,
                is_enabled=excluded.is_enabled,
                updated_at=excluded.updated_at
            """,
            (connection_id, owner_user_id, int(can_reply), int(is_enabled), ts),
        )
        await self._db.commit()

    async def get_connection(self, connection_id: str) -> dict | None:
        cur = await self._db.execute(
            "SELECT connection_id, owner_user_id, can_reply, is_enabled "
            "FROM business_connections WHERE connection_id=?",
            (connection_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return {
            "connection_id": row[0],
            "owner_user_id": row[1],
            "can_reply": bool(row[2]),
            "is_enabled": bool(row[3]),
        }

    async def delete_connection(self, connection_id: str) -> None:
        await self._db.execute(
            "DELETE FROM business_connections WHERE connection_id=?",
            (connection_id,),
        )
        await self._db.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS (existing + 4 new connection tests).

- [ ] **Step 5: Commit**

```bash
git add bot/memory/store.py tests/test_store.py
git commit -m "feat(store): add business_connections table + upsert/get/delete"
```

---

## Task 3: Store — `business_messages` history + prune

**Files:**
- Modify: `bot/memory/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_store.py`:

```python
async def test_append_and_get_business_history_in_order(store):
    await store.append_business("conn1", 100, "user", "hello")
    await store.append_business("conn1", 100, "assistant", "hi there")
    hist = await store.get_business_history("conn1", 100, limit=10)
    assert hist == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


async def test_business_history_scoped_per_connection_and_chat(store):
    await store.append_business("conn1", 100, "user", "a")
    await store.append_business("conn1", 200, "user", "b")
    await store.append_business("conn2", 100, "user", "c")
    assert await store.get_business_history("conn1", 100, 10) == [{"role": "user", "content": "a"}]
    assert await store.get_business_history("conn1", 200, 10) == [{"role": "user", "content": "b"}]
    assert await store.get_business_history("conn2", 100, 10) == [{"role": "user", "content": "c"}]


async def test_get_business_history_returns_last_n(store):
    for i in range(5):
        await store.append_business("conn1", 100, "user", f"m{i}")
    hist = await store.get_business_history("conn1", 100, limit=2)
    assert hist == [{"role": "user", "content": "m3"}, {"role": "user", "content": "m4"}]


async def test_prune_also_removes_expired_business_messages(store):
    old = time.time() - 10_000
    await store.append_business("conn1", 100, "user", "old", created_at=old)
    await store.append_business("conn1", 100, "user", "new")
    await store.prune(ttl_seconds=5000)
    assert await store.get_business_history("conn1", 100, 10) == [{"role": "user", "content": "new"}]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_store.py::test_append_and_get_business_history_in_order -v`
Expected: FAIL — `AttributeError: 'MemoryStore' object has no attribute 'append_business'`.

- [ ] **Step 3: Implement**

In `init()`, after the `business_connections` table from Task 2 and before `await self._db.commit()`, add:

```python
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS business_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                connection_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_business_scope "
            "ON business_messages (connection_id, chat_id, id)"
        )
```

Add these methods to `MemoryStore` (after `delete_connection`):

```python
    async def append_business(self, connection_id: str, chat_id: int, role: str,
                              content: str, created_at: float | None = None) -> None:
        ts = time.time() if created_at is None else created_at
        await self._db.execute(
            "INSERT INTO business_messages (connection_id, chat_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (connection_id, chat_id, role, content, ts),
        )
        await self._db.commit()

    async def get_business_history(self, connection_id: str, chat_id: int,
                                   limit: int) -> list[dict]:
        cur = await self._db.execute(
            "SELECT role, content FROM business_messages "
            "WHERE connection_id=? AND chat_id=? ORDER BY id DESC LIMIT ?",
            (connection_id, chat_id, limit),
        )
        rows = await cur.fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]
```

Extend `prune` — replace its body so it cleans both tables:

```python
    async def prune(self, ttl_seconds: int) -> None:
        cutoff = time.time() - ttl_seconds
        await self._db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
        await self._db.execute("DELETE FROM business_messages WHERE created_at < ?", (cutoff,))
        await self._db.commit()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_store.py -v`
Expected: PASS (all store tests).

- [ ] **Step 5: Commit**

```bash
git add bot/memory/store.py tests/test_store.py
git commit -m "feat(store): add business_messages history + prune by TTL"
```

---

## Task 4: API — `send_business_message`

**Files:**
- Modify: `bot/telegram/api.py`
- Test: `tests/test_telegram_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_telegram_api.py`:

```python
async def test_send_business_message_posts_connection_chat_and_text():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok({"message_id": 1}))

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.send_business_message("conn1", 999, "hello there")
    assert seen["url"].endswith("/sendMessage")
    body = seen["json"]
    assert b"conn1" in body and b"hello there" in body
    assert b"business_connection_id" in body and b"999" in body
    await api.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_telegram_api.py::test_send_business_message_posts_connection_chat_and_text -v`
Expected: FAIL — `AttributeError: 'TelegramApi' object has no attribute 'send_business_message'`.

- [ ] **Step 3: Implement**

In `bot/telegram/api.py`, add this method to `TelegramApi` (after `edit_inline_message_text`):

```python
    async def send_business_message(self, business_connection_id: str, chat_id: int,
                                    text: str) -> object:
        # Secretary mode: standard sendMessage with a business_connection_id sends
        # the message AS the owner. The chat must have been active in the last 24h
        # and the connection's can_reply must be true, or the API returns ok:false.
        return await self.call("sendMessage",
                               business_connection_id=business_connection_id,
                               chat_id=chat_id, text=text)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_telegram_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/telegram/api.py tests/test_telegram_api.py
git commit -m "feat(api): add send_business_message (sendMessage with business_connection_id)"
```

---

## Task 5: API — extend `set_webhook` allowed_updates

**Files:**
- Modify: `bot/telegram/api.py`
- Test: `tests/test_telegram_api.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_telegram_api.py` (and extend the existing `test_set_webhook_posts_url_and_secret` is optional — this new test covers it):

```python
async def test_set_webhook_includes_business_updates():
    seen = {}

    def handler(request):
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok())

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.set_webhook("https://bot.example.com/webhook", "s3cret")
    body = seen["json"]
    assert b"guest_message" in body
    assert b"business_connection" in body
    assert b"business_message" in body
    await api.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_telegram_api.py::test_set_webhook_includes_business_updates -v`
Expected: FAIL — assertion error: `b"business_connection"` not found in body.

- [ ] **Step 3: Implement**

In `bot/telegram/api.py`, replace the `set_webhook` `allowed_updates` list:

```python
    async def set_webhook(self, url: str, secret_token: str) -> object:
        return await self.call("setWebhook", url=url, secret_token=secret_token,
                               allowed_updates=["guest_message", "message",
                                                "business_connection", "business_message"])
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_telegram_api.py -v`
Expected: PASS (including the existing webhook test, which still finds `guest_message`).

- [ ] **Step 5: Commit**

```bash
git add bot/telegram/api.py tests/test_telegram_api.py
git commit -m "feat(api): subscribe webhook to business_connection + business_message updates"
```

---

## Task 6: business.py — `parse_business_connection`

**Files:**
- Create: `bot/telegram/business.py`
- Test: `tests/test_business.py`

> **Implementer caveat (from spec §2):** The assumed `business_connection` JSON shape
> (`id`, `user.id`, `can_reply`, `is_enabled`) is NOT yet verified against the live API.
> Before relying on it in production, `curl https://core.telegram.org/bots/api` and grep
> the `business_connection` section. If the real shape differs, change ONLY this parse
> function — nothing else depends on the JSON shape.

- [ ] **Step 1: Write the failing test**

Create `tests/test_business.py`:

```python
import pytest
from bot.telegram.business import (
    BusinessConnection, parse_business_connection,
)


def _conn_update(connection_id="conn1", owner_id=555, can_reply=True, is_enabled=True):
    return {
        "business_connection": {
            "id": connection_id,
            "user": {"id": owner_id},
            "can_reply": can_reply,
            "is_enabled": is_enabled,
        }
    }


def test_parse_business_connection_returns_none_for_other_update():
    assert parse_business_connection({"message": {"text": "hi"}}) is None


def test_parse_business_connection_extracts_fields():
    conn = parse_business_connection(_conn_update())
    assert conn == BusinessConnection(connection_id="conn1", owner_user_id=555,
                                      can_reply=True, is_enabled=True)


def test_parse_business_connection_disabled():
    conn = parse_business_connection(_conn_update(can_reply=False, is_enabled=False))
    assert conn.can_reply is False
    assert conn.is_enabled is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_business.py::test_parse_business_connection_extracts_fields -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bot.telegram.business'`.

- [ ] **Step 3: Implement**

Create `bot/telegram/business.py`:

```python
from __future__ import annotations
import logging
from dataclasses import dataclass

from bot.telegram.guest import build_messages, TELEGRAM_MAX

log = logging.getLogger("tgbot.business")


@dataclass(frozen=True)
class BusinessConnection:
    connection_id: str
    owner_user_id: int
    can_reply: bool
    is_enabled: bool


def parse_business_connection(update: dict) -> BusinessConnection | None:
    """Extract a BusinessConnection from a Telegram update.

    ASSUMPTION: the `business_connection` JSON shape (id, user.id, can_reply,
    is_enabled) follows the Bot API and is NOT yet verified against the live API.
    If the real shape differs, THIS is the only function to change.
    """
    bc = update.get("business_connection")
    if not bc:
        return None
    return BusinessConnection(
        connection_id=bc["id"],
        owner_user_id=bc["user"]["id"],
        can_reply=bool(bc.get("can_reply", False)),
        is_enabled=bool(bc.get("is_enabled", False)),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_business.py -v`
Expected: PASS (3 connection-parse tests).

- [ ] **Step 5: Commit**

```bash
git add bot/telegram/business.py tests/test_business.py
git commit -m "feat(business): add parse_business_connection"
```

---

## Task 7: business.py — `parse_business_message`

**Files:**
- Modify: `bot/telegram/business.py`
- Test: `tests/test_business.py`

> **Implementer caveat:** `business_message` is a standard Message object plus a
> `business_connection_id` field. Assumed fields: `business_connection_id`, `chat.id`,
> `chat.type`, `from.id`, `text`, `reply_to_message.text`. Verify against the live API;
> if it differs, change ONLY this parse function.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_business.py` (extend the import to
`from bot.telegram.business import (BusinessConnection, parse_business_connection, BusinessMessage, parse_business_message,)`):

```python
def _msg_update(connection_id="conn1", chat_id=999, chat_type="private",
                from_id=999, text="hello", reply=None):
    bm = {
        "business_connection_id": connection_id,
        "from": {"id": from_id},
        "chat": {"id": chat_id, "type": chat_type},
        "text": text,
    }
    if reply is not None:
        bm["reply_to_message"] = {"text": reply}
    return {"business_message": bm}


def test_parse_business_message_returns_none_for_other_update():
    assert parse_business_message({"message": {"text": "hi"}}) is None


def test_parse_business_message_extracts_fields():
    bm = parse_business_message(_msg_update(reply="prev text"))
    assert bm == BusinessMessage(connection_id="conn1", chat_id=999, chat_type="private",
                                 from_user_id=999, text="hello", reply_text="prev text")


def test_parse_business_message_no_text_defaults_empty():
    update = _msg_update()
    del update["business_message"]["text"]
    bm = parse_business_message(update)
    assert bm.text == ""
    assert bm.reply_text is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_business.py::test_parse_business_message_extracts_fields -v`
Expected: FAIL — `ImportError: cannot import name 'BusinessMessage'`.

- [ ] **Step 3: Implement**

In `bot/telegram/business.py`, add after the `BusinessConnection` dataclass / parse function:

```python
@dataclass(frozen=True)
class BusinessMessage:
    connection_id: str
    chat_id: int
    chat_type: str
    from_user_id: int
    text: str
    reply_text: str | None = None


def parse_business_message(update: dict) -> BusinessMessage | None:
    """Extract a BusinessMessage from a Telegram update.

    ASSUMPTION: `business_message` is a standard Message plus `business_connection_id`.
    Assumed fields: business_connection_id, chat.id, chat.type, from.id, text,
    reply_to_message.text. NOT yet verified against the live API. If the real shape
    differs, THIS is the only function to change.
    """
    bm = update.get("business_message")
    if not bm:
        return None
    reply = bm.get("reply_to_message") or {}
    return BusinessMessage(
        connection_id=bm["business_connection_id"],
        chat_id=bm["chat"]["id"],
        chat_type=bm["chat"].get("type", ""),
        from_user_id=bm["from"]["id"],
        text=bm.get("text", ""),
        reply_text=reply.get("text"),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_business.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/telegram/business.py tests/test_business.py
git commit -m "feat(business): add parse_business_message"
```

---

## Task 8: business.py — `handle_business_connection`

**Files:**
- Modify: `bot/telegram/business.py`
- Test: `tests/test_business.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_business.py` (extend the import with `handle_business_connection`). Also add this fake store near the top of the test file, after the imports:

```python
class FakeStore:
    def __init__(self, history=None, connection=None):
        self._history = history or []
        self._connection = connection
        self.upserts = []
        self.appended = []

    async def upsert_connection(self, connection_id, owner_user_id, can_reply, is_enabled):
        self.upserts.append((connection_id, owner_user_id, can_reply, is_enabled))
        self._connection = {"connection_id": connection_id, "owner_user_id": owner_user_id,
                            "can_reply": can_reply, "is_enabled": is_enabled}

    async def get_connection(self, connection_id):
        return self._connection

    async def get_business_history(self, connection_id, chat_id, limit):
        return list(self._history)

    async def append_business(self, connection_id, chat_id, role, content):
        self.appended.append((role, content))
```

And the test:

```python
async def test_handle_business_connection_upserts():
    store = FakeStore()
    await handle_business_connection(_conn_update(connection_id="c9", owner_id=42,
                                                  can_reply=True, is_enabled=True), store)
    assert store.upserts == [("c9", 42, True, True)]


async def test_handle_business_connection_disabled_roundtrip():
    store = FakeStore()
    await handle_business_connection(_conn_update(can_reply=False, is_enabled=False), store)
    assert store.upserts == [("conn1", 555, False, False)]


async def test_handle_business_connection_ignores_other_updates():
    store = FakeStore()
    await handle_business_connection({"message": {}}, store)
    assert store.upserts == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_business.py::test_handle_business_connection_upserts -v`
Expected: FAIL — `ImportError: cannot import name 'handle_business_connection'`.

- [ ] **Step 3: Implement**

In `bot/telegram/business.py`, add (after `parse_business_message`):

```python
async def handle_business_connection(update: dict, store) -> None:
    conn = parse_business_connection(update)
    if conn is None:
        return
    # Upsert always: a disabled/can_reply=false connection is stored with those
    # flags so handle_business_message's gate sees the current state. Survives
    # process restarts.
    await store.upsert_connection(conn.connection_id, conn.owner_user_id,
                                  conn.can_reply, conn.is_enabled)
    log.info("business_connection upserted: id=%s enabled=%s can_reply=%s",
             conn.connection_id, conn.is_enabled, conn.can_reply)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_business.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/telegram/business.py tests/test_business.py
git commit -m "feat(business): add handle_business_connection (persist connection state)"
```

---

## Task 9: business.py — `handle_business_message` (autopilot reply)

**Files:**
- Modify: `bot/telegram/business.py`
- Test: `tests/test_business.py`

This is the core handler. Flow (spec §4): parse → drop if not private or no text →
look up connection (drop if missing/disabled/`can_reply` false) → skip if author is the
owner → load history → build prompt with `business_system_prompt` → accumulate Groq stream →
on non-empty output send + persist; on failure/empty stay silent.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_business.py` (extend the import with `handle_business_message`). Add
the `FakeAI`, `FakeApi`, and `Cfg` helpers after `FakeStore`:

```python
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
    def __init__(self, error=None):
        self.sent = []
        self._error = error

    async def send_business_message(self, business_connection_id, chat_id, text):
        if self._error:
            raise self._error
        self.sent.append((business_connection_id, chat_id, text))


BUSINESS_PROMPT = "Reply as the owner."


class Cfg:
    context_messages = 10
    business_system_prompt = BUSINESS_PROMPT


def _enabled_conn(owner_id=555):
    return {"connection_id": "conn1", "owner_user_id": owner_id,
            "can_reply": True, "is_enabled": True}
```

Tests:

```python
async def test_business_autopilot_replies_and_persists():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(["Hel", "lo!"]), FakeApi()
    # incoming from the other party (from_id != owner 555)
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    assert api.sent == [("conn1", 999, "Hello!")]
    assert store.appended == [("user", "hi"), ("assistant", "Hello!")]


async def test_business_skips_owner_own_messages():
    store = FakeStore(connection=_enabled_conn(owner_id=555))
    ai, api = FakeAI(["should not run"]), FakeApi()
    await handle_business_message(_msg_update(from_id=555, text="note to self"), api, ai, store, Cfg())
    assert api.sent == []
    assert store.appended == []


async def test_business_skips_non_private_chats():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(["nope"]), FakeApi()
    await handle_business_message(_msg_update(from_id=999, chat_type="group"), api, ai, store, Cfg())
    assert api.sent == []


async def test_business_skips_empty_text():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(["nope"]), FakeApi()
    upd = _msg_update(from_id=999)
    del upd["business_message"]["text"]
    await handle_business_message(upd, api, ai, store, Cfg())
    assert api.sent == []


async def test_business_drops_when_connection_missing():
    store = FakeStore(connection=None)
    ai, api = FakeAI(["nope"]), FakeApi()
    await handle_business_message(_msg_update(from_id=999), api, ai, store, Cfg())
    assert api.sent == []


async def test_business_drops_when_can_reply_false():
    conn = _enabled_conn()
    conn["can_reply"] = False
    store = FakeStore(connection=conn)
    ai, api = FakeAI(["nope"]), FakeApi()
    await handle_business_message(_msg_update(from_id=999), api, ai, store, Cfg())
    assert api.sent == []


async def test_business_drops_when_disabled():
    conn = _enabled_conn()
    conn["is_enabled"] = False
    store = FakeStore(connection=conn)
    ai, api = FakeAI(["nope"]), FakeApi()
    await handle_business_message(_msg_update(from_id=999), api, ai, store, Cfg())
    assert api.sent == []


async def test_business_stays_silent_on_ai_error():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(error=RuntimeError("groq down")), FakeApi()
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    assert api.sent == []
    assert store.appended == []


async def test_business_stays_silent_on_empty_output():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI([]), FakeApi()
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    assert api.sent == []
    assert store.appended == []


async def test_business_does_not_persist_when_send_fails():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(["Hello!"]), FakeApi(error=RuntimeError("outside 24h window"))
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    assert store.appended == []


async def test_business_truncates_to_4096():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(["x" * 5000]), FakeApi()
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    _, _, text = api.sent[0]
    assert len(text) == 4096
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_business.py::test_business_autopilot_replies_and_persists -v`
Expected: FAIL — `ImportError: cannot import name 'handle_business_message'`.

- [ ] **Step 3: Implement**

In `bot/telegram/business.py`, add (after `handle_business_connection`):

```python
async def handle_business_message(update: dict, api, ai, store, config) -> None:
    bm = parse_business_message(update)
    if bm is None:
        return
    if bm.chat_type != "private" or not bm.text:
        return
    conn = await store.get_connection(bm.connection_id)
    if conn is None or not conn["is_enabled"] or not conn["can_reply"]:
        log.info("business_message dropped: connection %s missing/disabled/no-reply",
                 bm.connection_id)
        return
    # The bot receives the owner's own outgoing messages too — never answer ourselves.
    if bm.from_user_id == conn["owner_user_id"]:
        return

    history = await store.get_business_history(bm.connection_id, bm.chat_id,
                                               config.context_messages)
    messages = build_messages(history, bm.text, bm.reply_text,
                              config.business_system_prompt)

    # Accumulate the full Groq stream (single-shot, like the guest path).
    try:
        full = ""
        async for chunk in ai.stream_completion(messages):
            full += chunk
    except Exception:
        log.exception("AI generation failed (business)")
        full = ""

    # AI failure or empty output → stay silent. A fake "AI unavailable" message
    # sent AS the owner would be inappropriate (spec §3, §6).
    if not full:
        return

    reply = full[:TELEGRAM_MAX]
    try:
        await api.send_business_message(bm.connection_id, bm.chat_id, reply)
    except Exception:
        log.exception("send_business_message failed (chat %s)", bm.chat_id)
        return

    # Persist only on a successful send (mirrors the guest path).
    await store.append_business(bm.connection_id, bm.chat_id, "user", bm.text)
    await store.append_business(bm.connection_id, bm.chat_id, "assistant", reply)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_business.py -v`
Expected: PASS (all business tests).

- [ ] **Step 5: Commit**

```bash
git add bot/telegram/business.py tests/test_business.py
git commit -m "feat(business): add handle_business_message autopilot reply"
```

---

## Task 10: main.py — update-type dispatcher

**Files:**
- Modify: `bot/main.py`
- Test: `tests/test_main_dispatch.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_main_dispatch.py`:

```python
import pytest
from bot.main import dispatch


class Recorder:
    def __init__(self):
        self.calls = []


def _make_recorder(monkeypatch):
    """Patch the three handlers in bot.main to record which one dispatch calls."""
    import bot.main as m
    rec = Recorder()

    async def fake_guest(update, api, ai, store, config):
        rec.calls.append(("guest", update))

    async def fake_business_msg(update, api, ai, store, config):
        rec.calls.append(("business_message", update))

    async def fake_business_conn(update, store):
        rec.calls.append(("business_connection", update))

    monkeypatch.setattr(m, "handle_guest_message", fake_guest)
    monkeypatch.setattr(m, "handle_business_message", fake_business_msg)
    monkeypatch.setattr(m, "handle_business_connection", fake_business_conn)
    return rec


async def test_dispatch_routes_guest_message(monkeypatch):
    rec = _make_recorder(monkeypatch)
    await dispatch({"guest_message": {"x": 1}}, None, None, None, None)
    assert rec.calls == [("guest", {"guest_message": {"x": 1}})]


async def test_dispatch_routes_business_connection(monkeypatch):
    rec = _make_recorder(monkeypatch)
    await dispatch({"business_connection": {"id": "c1"}}, None, None, None, None)
    assert rec.calls == [("business_connection", {"business_connection": {"id": "c1"}})]


async def test_dispatch_routes_business_message(monkeypatch):
    rec = _make_recorder(monkeypatch)
    await dispatch({"business_message": {"x": 1}}, None, None, None, None)
    assert rec.calls == [("business_message", {"business_message": {"x": 1}})]


async def test_dispatch_unknown_update_is_ignored(monkeypatch):
    rec = _make_recorder(monkeypatch)
    await dispatch({"edited_message": {"x": 1}}, None, None, None, None)
    assert rec.calls == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_main_dispatch.py::test_dispatch_routes_business_connection -v`
Expected: FAIL — `ImportError: cannot import name 'dispatch' from 'bot.main'`.

- [ ] **Step 3: Implement**

In `bot/main.py`, update the imports:

```python
from bot.telegram.guest import handle_guest_message
from bot.telegram.business import handle_business_connection, handle_business_message
```

Add a module-level `dispatch` function (after the imports / `PRUNE_INTERVAL_SECONDS`,
before `build_app`):

```python
async def dispatch(update: dict, api, ai, store, config) -> None:
    """Route a Telegram update to the right handler by its top-level type.

    Unknown update types are ignored. Guest and business modes share the same
    api/ai/store/config instances and the one webhook.
    """
    if "business_connection" in update:
        await handle_business_connection(update, store)
    elif "business_message" in update:
        await handle_business_message(update, api, ai, store, config)
    elif "guest_message" in update:
        await handle_guest_message(update, api, ai, store, config)
```

Replace the `handler` closure inside `build_app`:

```python
    async def handler(update: dict) -> None:
        await dispatch(update, api, ai, store, config)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_main_dispatch.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: PASS — entire suite green.

- [ ] **Step 6: Commit**

```bash
git add bot/main.py tests/test_main_dispatch.py
git commit -m "feat(main): dispatch business + guest updates by type"
```

---

## Task 11: Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add `BUSINESS_SYSTEM_PROMPT` to `.env.example`**

Append to the "Optional overrides" section of `.env.example`:

```bash
# Secretary (Business) Mode persona. The bot replies AS the account owner, in the
# first person, to incoming private messages in chats connected via Telegram Business.
# Leave unset for a conservative default that won't make commitments on your behalf.
BUSINESS_SYSTEM_PROMPT=You are replying on behalf of the account owner, in the first person, as if you were them. Be polite, concise, and natural. Do NOT agree to payments, make firm commitments, schedule meetings, or make promises on the owner's behalf.
```

- [ ] **Step 2: Document Secretary Mode in `README.md`**

Add a "Secretary (Business) Mode" section near the existing mode description. Cover:
how the owner connects the bot via Telegram Business (Settings → Business → Chatbots),
that it replies in the owner's voice to private 1:1 chats only, that the opt-in /
kill-switch is the in-app connection itself (no env flag), the `BUSINESS_SYSTEM_PROMPT`
override, and the impersonation risk note from spec §8. (Write prose to match the
README's existing tone — no fixed text required, but it MUST mention: private-only,
in-app opt-in, `BUSINESS_SYSTEM_PROMPT`, stays silent on AI failure.)

- [ ] **Step 3: Document Secretary Mode in `CLAUDE.md`**

In the Architecture section, add a bullet for `bot/telegram/business.py` mirroring the
existing `guest.py` bullet: the two parse functions are the single place that know the
Business JSON shape; autopilot, private-only, owner-message skip, stay-silent-on-failure;
keyed by `(connection_id, chat_id)` in separate tables. Add a note under the dispatcher
description in `bot/main.py` that `dispatch` routes by update type. Note the
`send_business_message` gotcha (24h window + `can_reply`).

- [ ] **Step 4: Verify the suite is still green**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add .env.example README.md CLAUDE.md
git commit -m "docs: document Secretary (Business) Mode config and architecture"
```

---

## Self-Review

**Spec coverage:**
- §3 Full autopilot → Task 9 (replies to every non-owner incoming message). ✓
- §3 Owner's voice via `BUSINESS_SYSTEM_PROMPT` → Task 1 + Task 9 (build_messages uses it). ✓
- §3 Private 1:1 only → Task 9 (`chat_type != "private"` drop). ✓
- §3 Same bot/deployment, new handler → Task 10 dispatcher. ✓
- §3 No env flag / in-app opt-in → no enable flag added; gating is the connection record. ✓
- §3 Separate `business_messages` table keyed by `(connection_id, chat_id)` → Task 3. ✓
- §3 AI failure → stay silent → Task 9 (`if not full: return`). ✓
- §4 `handle_business_message` 9-step flow → Task 9 (matches step-for-step). ✓
- §4 `handle_business_connection` upsert/persist → Task 8. ✓
- §5 Components: `business.py` parsers + handlers (Tasks 6–9), `api.py` send + webhook (Tasks 4–5), `main.py` dispatch (Task 10), `store.py` two tables + prune (Tasks 2–3), `config.py` prompt (Task 1). ✓
- §6 Error handling: AI silent (Task 9), send failure log+drop+no-persist (Task 9 test `test_business_does_not_persist_when_send_fails`), lookup miss drop (Task 9), webhook always-200 (unchanged). ✓
- §9 Config summary: `BUSINESS_SYSTEM_PROMPT` new, reuse `CONTEXT_MESSAGES`/`HISTORY_TTL_SECONDS`, webhook allowed_updates extended → Tasks 1, 5, and reuse in Task 9. ✓
- §10 Testing: parsers, store methods, dispatcher, autopilot send, owner-skip, non-private-skip, Groq-failure-no-send, can_reply/missing gate, connection upsert/disable round-trip → covered across Tasks 2,3,6,7,8,9,10. ✓
- §11 Out of scope: no `edited_business_message`/`deleted_business_messages` (dispatcher ignores them via Task 10 `test_dispatch_unknown_update_is_ignored`), no groups, no away/draft, no in-chat `/clear`, no typing indicator. ✓

**Placeholder scan:** Task 11 Steps 2–3 intentionally describe doc prose rather than fixed text (docs match existing tone); all code steps contain complete code. No TODO/TBD in code.

**Type consistency:** `BusinessConnection(connection_id, owner_user_id, can_reply, is_enabled)` and `BusinessMessage(connection_id, chat_id, chat_type, from_user_id, text, reply_text)` used identically in parsers, handlers, and tests. `get_connection` returns a dict with keys `connection_id`/`owner_user_id`/`can_reply`/`is_enabled` — the same keys read in Task 9. `store.upsert_connection(connection_id, owner_user_id, can_reply, is_enabled)` signature matches the FakeStore in Task 8 and the real store in Task 2. `send_business_message(business_connection_id, chat_id, text)` consistent across Task 4, FakeApi (Task 9), and the handler call. `dispatch(update, api, ai, store, config)` consistent in Task 10. `build_messages(history, user_text, reply_text, system_prompt)` reused from guest unchanged. ✓
