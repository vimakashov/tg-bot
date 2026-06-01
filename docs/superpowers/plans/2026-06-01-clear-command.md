# `/clear` Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user reset their own conversation context in a chat by mentioning `@<bot> /clear`.

**Architecture:** Add a `clear(chat_id, user_id)` method to `MemoryStore` that deletes the caller's history rows. In `handle_guest_message`, after stripping the bot mention, detect an exact `/clear` command via a new pure `is_clear_command` helper; if matched, clear the store, answer once with a fixed confirmation, and return early (no Groq call, no history append).

**Tech Stack:** Python 3.9/3.12, aiosqlite, aiohttp, pytest (`asyncio_mode=auto`).

Spec: `docs/superpowers/specs/2026-06-01-clear-command-design.md`

---

### Task 1: `MemoryStore.clear`

**Files:**
- Modify: `bot/memory/store.py` (add `clear` method after `prune`, around line 50)
- Test: `tests/test_store.py` (append at end of file)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_store.py`:

```python
async def test_clear_removes_only_caller_scope(store):
    await store.append(1, 100, "user", "a")
    await store.append(1, 200, "user", "b")   # same chat, other user
    await store.append(2, 100, "user", "c")   # other chat, same user
    await store.clear(1, 100)
    assert await store.get_history(1, 100, 10) == []
    assert await store.get_history(1, 200, 10) == [{"role": "user", "content": "b"}]
    assert await store.get_history(2, 100, 10) == [{"role": "user", "content": "c"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_store.py::test_clear_removes_only_caller_scope -v`
Expected: FAIL with `AttributeError: 'MemoryStore' object has no attribute 'clear'`

- [ ] **Step 3: Write minimal implementation**

In `bot/memory/store.py`, add this method immediately after `prune` (before `close`):

```python
    async def clear(self, chat_id: int, user_id: int) -> None:
        await self._db.execute(
            "DELETE FROM messages WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        )
        await self._db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_store.py::test_clear_removes_only_caller_scope -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bot/memory/store.py tests/test_store.py
git commit -m "feat: add MemoryStore.clear to wipe a caller's history scope"
```

---

### Task 2: `is_clear_command` helper

**Files:**
- Modify: `bot/telegram/guest.py` (add `CLEAR_REPLY` constant near `FALLBACK_TEXT` line 9; add `is_clear_command` after `strip_bot_mention`, around line 44)
- Test: `tests/test_guest.py` (add tests; extend the import line at the top)

- [ ] **Step 1: Write the failing test**

In `tests/test_guest.py`, extend the existing import to also pull in the new names:

```python
from bot.telegram.guest import (
    GuestMessage, parse_guest_message, strip_bot_mention, build_messages, handle_guest_message,
    FALLBACK_TEXT, CLEAR_REPLY, is_clear_command,
)
```

Add these tests (anywhere after `test_strip_bot_mention`):

```python
def test_is_clear_command_exact():
    assert is_clear_command("/clear") is True

def test_is_clear_command_case_and_whitespace():
    assert is_clear_command("  /CLEAR  ") is True

def test_is_clear_command_after_stripping_botname_form():
    # "/clear@testbot" -> strip_bot_mention removes "@testbot" -> "/clear"
    assert is_clear_command(strip_bot_mention("/clear@testbot", "testbot")) is True

def test_is_clear_command_rejects_extra_text():
    assert is_clear_command("/clear please") is False

def test_is_clear_command_rejects_unrelated():
    assert is_clear_command("hello") is False
    assert is_clear_command("") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_guest.py -k is_clear_command -v`
Expected: FAIL — `ImportError` (cannot import `CLEAR_REPLY` / `is_clear_command`)

- [ ] **Step 3: Write minimal implementation**

In `bot/telegram/guest.py`, add the constant right after `FALLBACK_TEXT` (line 9):

```python
CLEAR_REPLY = "🧠 Context cleared — starting fresh."
```

Add this function immediately after `strip_bot_mention`:

```python
def is_clear_command(text: str) -> bool:
    return text.strip().casefold() == "/clear"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_guest.py -k is_clear_command -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add bot/telegram/guest.py tests/test_guest.py
git commit -m "feat: add is_clear_command helper and CLEAR_REPLY constant"
```

---

### Task 3: Wire `/clear` into the handler

**Files:**
- Modify: `bot/telegram/guest.py` — `handle_guest_message` (add branch after `strip_bot_mention`, around line 63)
- Modify: `tests/test_guest.py` — add `clear` to `FakeStore`; add handler test

- [ ] **Step 1: Write the failing test**

In `tests/test_guest.py`, add a `clear` method to the existing `FakeStore` class (alongside `get_history` / `append`):

```python
    async def clear(self, chat_id, user_id):
        self.cleared = (chat_id, user_id)
```

Also add `self.cleared = None` at the end of `FakeStore.__init__`.

Add this test near the other handler tests:

```python
async def test_handler_clear_command_resets_and_skips_ai():
    store, ai, api = FakeStore(history=[{"role": "user", "content": "old"}]), FakeAI(["should not run"]), FakeApi()
    await handle_guest_message(_update("@testbot /clear"), api, ai, store, Cfg())
    assert store.cleared == (42, 7)              # (chat_id, user_id) from _update
    assert api.answers == [("q1", CLEAR_REPLY)]  # answered exactly once
    assert store.appended == []                  # no history written
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_guest.py::test_handler_clear_command_resets_and_skips_ai -v`
Expected: FAIL — `store.cleared` is `None` and `api.answers` holds the AI reply, because the handler still runs the normal flow.

- [ ] **Step 3: Write minimal implementation**

In `bot/telegram/guest.py`, inside `handle_guest_message`, insert the branch right after the `user_text = strip_bot_mention(...)` line (line 63) and before `history = await store.get_history(...)`:

```python
    user_text = strip_bot_mention(gm.text, config.bot_username)
    if is_clear_command(user_text):
        await store.clear(gm.chat_id, gm.user_id)
        await api.answer_guest_query(gm.query_id, CLEAR_REPLY)
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_guest.py::test_handler_clear_command_resets_and_skips_ai -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `pytest -q`
Expected: all tests PASS (existing tests unaffected — `FakeAI` is never iterated for `/clear`, and the normal-message tests still append history).

- [ ] **Step 6: Commit**

```bash
git add bot/telegram/guest.py tests/test_guest.py
git commit -m "feat: handle /clear in guest handler — wipe context, confirm, skip Groq"
```

---

### Task 4: Documentation

**Files:**
- Modify: `CLAUDE.md` — `bot/telegram/guest.py` bullet under "Architecture"
- Modify: `README.md` — usage section (if present), document the `/clear` command

- [ ] **Step 1: Update CLAUDE.md**

In the `bot/telegram/guest.py` architecture bullet, append a sentence noting the early-return branch:

```
The handler also recognizes an exact `@<bot> /clear` (via `is_clear_command`, checked after `strip_bot_mention`) and, when matched, wipes the caller's `(chat_id, user_id)` history via `store.clear`, replies once with `CLEAR_REPLY`, and returns before any Groq call.
```

- [ ] **Step 2: Update README.md usage**

Add a line to the user-facing usage section describing the command:

```
- `@<bot> /clear` — reset your own conversation context in the current chat; the bot confirms and the next message starts fresh.
```

(If README has no usage section, add a short "Usage" section with that line.)

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document the /clear command"
```

---

## Self-Review notes

- **Spec coverage:** store.clear (Task 1), is_clear_command + CLEAR_REPLY (Task 2), handler branch + early return / no-Groq / no-append (Task 3), docs (Task 4). All spec test cases mapped: scope-isolation (T1), exact/case/botname-form/extra-text/empty (T2), handler one-shot + skip-AI (T3).
- **Type consistency:** `clear(chat_id, user_id)`, `is_clear_command(text) -> bool`, `CLEAR_REPLY` used identically across tasks and tests.
- **No placeholders:** all code shown inline.
- **Note on existing tests:** the normal-flow handler tests use `@testbot hi`, which is not `/clear`, so the new branch never fires for them.
