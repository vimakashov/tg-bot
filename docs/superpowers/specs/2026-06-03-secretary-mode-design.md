# Secretary (Business) Mode — Design

**Date:** 2026-06-03
**Status:** Approved design — implementation plan to follow

## 1. Summary

Add **Secretary Mode** to the existing Guest-Mode Telegram bot. Secretary Mode is
Telegram's **Business connection** feature ("secretary bots",
`https://core.telegram.org/bots/features#secretary-bots`): the account owner connects the
bot to their personal Telegram account via Telegram Business, and the bot answers incoming
messages **on the owner's behalf**.

Scope for this iteration:

- **Full autopilot** — the bot replies to every incoming message in connected chats.
- **Owner's voice** — replies are written in the first person, as if from the owner. The
  exact persona text is configurable via `BUSINESS_SYSTEM_PROMPT`.
- **Private 1:1 chats only** — group and channel messages are ignored.
- Runs in the **same bot and deployment** as Guest Mode; adds a new update handler alongside
  the guest path.

This is a larger change than the guest path: it adds new update types, persistent storage of
business connections, a new handler module, and a new send method.

## 2. Grounding in the Telegram Bot API

Secretary Mode uses **Telegram Business** updates and methods:

- **Updates**
  - `business_connection` — the owner establishes, modifies, or terminates a connection.
    Carries the connection `id`, the owner `user`, and `can_reply` (write permission). Also an
    enabled/disabled state.
  - `business_message` — a message in a connected chat. The bot receives all standard message
    updates in permitted chats **except** messages from itself or other bots; this **includes
    the owner's own outgoing messages**.
  - (`edited_business_message`, `deleted_business_messages` exist but are **out of scope** —
    see §11.)
- **Sending** — standard send methods (`sendMessage`, `sendChatAction`, …) accept a
  **`business_connection_id`** parameter to send as the owner.
- **Constraints**
  - Write permission is gated by `can_reply` on the active `BusinessConnection`.
  - The bot may send messages only in chats **active within the last 24 hours**.
  - The owner controls — entirely within the Telegram app — whether the bot is connected and
    which chats it can access. **This is the opt-in.** There is no server-side enable flag (see
    §3); if the owner hasn't connected the bot, Telegram simply sends no business updates.

> ⚠️ **Implementer caveat:** verify exact field/method names against the live API
> (`https://core.telegram.org/bots/api`) at build time, as with the guest path. The two parse
> functions in `business.py` are the only places that encode the assumed JSON shape — if the
> real shape differs, change only those.

## 3. Decisions (locked)

| Area | Choice | Rationale |
|------|--------|-----------|
| When to reply | **Full autopilot** — every incoming message | Chosen by owner; risk noted in §8 |
| Voice | **First person, as the owner** | Persona text via `BUSINESS_SYSTEM_PROMPT` |
| Chat scope | **Private 1:1 only** | Groups in autopilot are noisy/risky |
| Coexistence | Same bot/deployment as Guest Mode; new handler | One process, one webhook |
| Enable mechanism | **No env flag.** Opt-in is the Telegram Business connection itself | A server flag would duplicate Telegram's own UI gate; the owner can disconnect in-app as an instant kill switch |
| Memory keying | **Separate `business_messages` table** keyed by `(connection_id, chat_id)` | Leaves the guest `messages` table and its call sites untouched |
| AI failure behavior | **Stay silent** (log only) | A fake "AI unavailable" message sent as the owner is inappropriate |

## 4. Architecture & data flow

```
Telegram ─webhook─▶ aiohttp /webhook ─▶ dispatch(update) [in main.py]
                                         ├─ guest_message        → handle_guest_message      (unchanged)
                                         ├─ business_connection  → handle_business_connection (upsert/delete in SQLite)
                                         └─ business_message      → handle_business_message
                                                                     ├─ Groq (stream, accumulate)
                                                                     └─ SQLite (business history + connections)
                                              reply: sendMessage(business_connection_id=…, chat_id=…, text=…)
```

`webhook.py` stays generic (header check, always-200, dispatch to a single handler). The
top-level dispatcher that inspects the update type lives in `main.py`, next to the existing
`handler` wiring. Unknown update types are ignored.

### `handle_business_message` flow

1. `parse_business_message(update)` → `None` if not a `business_message`.
2. Drop if `chat.type != "private"` or the message has no text.
3. Look up the connection by `business_connection_id` in SQLite → owner `user_id`,
   `can_reply`, enabled. If missing, disabled, or `can_reply` is false → log + drop.
4. **Skip if the message author is the owner** (`from.id == owner_user_id`) — those are the
   owner's own outgoing messages; we don't answer ourselves.
5. Load history for `(connection_id, chat_id)` (last `CONTEXT_MESSAGES`).
6. Build the prompt with `BUSINESS_SYSTEM_PROMPT` (+ reply-to context, mirroring guest).
7. Accumulate the full Groq stream.
8. On non-empty output: `send_business_message(connection_id, chat_id, text)`, truncate to
   `TELEGRAM_MAX`, then persist the user message and the reply to history.
9. On Groq failure or empty output: stay silent (log only) — do not send anything.

### `handle_business_connection` flow

Upsert the connection record (`connection_id`, `owner_user_id`, `can_reply`, `is_enabled`,
`updated_at`). If the update indicates the connection was removed/disabled, mark it disabled
(or delete). Persisted in SQLite so a process restart keeps working.

## 5. Components (new / changed)

- **`bot/telegram/business.py`** (new) — the core. Mirrors the guest module's structure.
  - `parse_business_connection(update) -> BusinessConnection | None` — the single place that
    knows the `business_connection` JSON shape.
  - `parse_business_message(update) -> BusinessMessage | None` — the single place that knows
    the `business_message` JSON shape (connection id, chat id, chat type, from-user id, text,
    reply-to text).
  - `build_messages(...)` — prompt assembly with `BUSINESS_SYSTEM_PROMPT` (can reuse/share the
    guest helper if the signature fits).
  - `handle_business_connection(update, store)` and
    `handle_business_message(update, api, ai, store, config)`.
- **`bot/telegram/api.py`** — add
  `send_business_message(business_connection_id, chat_id, text)` (calls `sendMessage` with
  `business_connection_id`). Extend `set_webhook` `allowed_updates` with `business_connection`
  and `business_message`. *(Optional, deferred: `send_chat_action` "typing" with
  `business_connection_id` for a more natural feel.)*
- **`bot/main.py`** — add the update-type dispatcher; wire `handle_business_connection` and
  `handle_business_message` with the same `api`/`ai`/`store`/`config` instances.
- **`bot/memory/store.py`** — add:
  - Table `business_connections(connection_id TEXT PRIMARY KEY, owner_user_id INTEGER,
    can_reply INTEGER, is_enabled INTEGER, updated_at REAL)` with
    `upsert_connection` / `get_connection` / `delete_connection`.
  - Table `business_messages(id, connection_id TEXT, chat_id INTEGER, role, content,
    created_at)` with `append_business` / `get_business_history`, indexed by
    `(connection_id, chat_id, id)`. Extend `prune` to also clean this table by TTL.
- **`bot/config.py`** — add `business_system_prompt: str` (env `BUSINESS_SYSTEM_PROMPT`, with a
  first-person default persona). Reuse `context_messages` and `history_ttl_seconds`. No new
  required vars.

## 6. Error handling

- Groq error/timeout/empty → **stay silent**, log only (unlike guest's visible fallback).
- `sendMessage` failure (outside the 24-hour window, `can_reply` false, transient) → log +
  drop, never crash the handler.
- `business_connection` lookup miss for an incoming message → log + drop.
- Webhook always returns 200 (existing behavior) so Telegram doesn't retry-storm.

## 7. Privacy & data flow

- Telegram Business provides **no bulk history dump**; the bot accumulates context only from
  the `business_message` updates it receives while connected, stored in local SQLite on the
  VPS.
- The only data sent **back to Telegram** is the generated reply (`sendMessage`). Conversation
  history is **never** sent back to Telegram.
- The only external party that sees conversation content is **Groq** (the LLM provider). The
  amount sent is bounded by `CONTEXT_MESSAGES`. SQLite is VPS-local and TTL-pruned
  (`HISTORY_TTL_SECONDS`).
- Because business chats are private (not public mentions like guest mode), this is more
  sensitive than the guest path — hence the explicit bound on context and local-only storage.

## 8. Risks / ethics

- **Impersonation:** replying in the first person means the other party may not realize they
  are talking to a bot. This is a known, accepted risk for this iteration. The default
  `BUSINESS_SYSTEM_PROMPT` should be written to avoid making harmful commitments on the owner's
  behalf (e.g., not agreeing to payments, meetings, or promises).
- **Autopilot blast radius:** the bot answers everyone automatically. Mitigations: private-only
  scope, owner-controlled chat selection in Telegram, instant in-app disconnect.

## 9. Configuration summary

- New: `BUSINESS_SYSTEM_PROMPT` (optional; first-person default).
- Reused: `CONTEXT_MESSAGES`, `HISTORY_TTL_SECONDS`, all existing required vars.
- `set_webhook` `allowed_updates` gains `business_connection`, `business_message`.

## 10. Testing

- **Unit:** `parse_business_connection`, `parse_business_message` against synthetic updates;
  `business_connections` and `business_messages` store methods; the update-type dispatcher.
- **Behavioral:** autopilot reply sends via `send_business_message`; owner's own messages are
  skipped; non-private chats are skipped; Groq failure produces **no** outgoing message;
  `can_reply=false` / missing connection gates the reply; connection upsert/disable round-trip.
- `pytest.ini` `asyncio_mode=auto` — no `@pytest.mark.asyncio` needed.

## 11. Out of scope (YAGNI / deferred)

- `edited_business_message` and `deleted_business_messages` handling.
- Group/channel chats in secretary mode.
- "Away/draft/approval" reply policies and owner-presence detection.
- Owner-facing commands (e.g., `/clear`) inside business chats.
- Multiple AI providers / model routing.
- `send_chat_action` "typing" indicator (noted as an optional nicety).
