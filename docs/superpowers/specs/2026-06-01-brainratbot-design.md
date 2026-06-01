# brainratbot — AI Telegram Bot (Guest Mode + Streaming)

**Date:** 2026-06-01
**Status:** Approved design — implementation to follow later

## 1. Summary

A Telegram bot (`@brainratbot`) that answers users in any private chat or group via
**Guest Mode**: a user summons it by mentioning `@brainratbot` (or replying to it) and
the bot streams an AI-generated reply. It runs on a VPS in **webhook** mode, talks to the
**Groq** free AI API, keeps a short per-user conversation memory, and starts/stops with a
single Docker Compose command.

## 2. Grounding in the modern Telegram Bot API

Features come from Bot API ~9.5–10.0 (early–mid 2026):

- **Guest Mode (API 10.0, May 2026)** — enabled in BotFather's MiniApp.
  - New `Update` field: `guest_message`.
  - New method: `answerGuestQuery` (the single reply back to the summoning chat).
  - New class: `SentGuestMessage`.
  - New `Message` fields: `guest_bot_caller_user`, `guest_bot_caller_chat`, `guest_query_id`.
  - New `User` field: `supports_guest_queries`.
  - Guest mode gives **no chat history and no member list** — only the summoning message
    (and the message it replied to, if any). The bot may issue **one** reply.
- **Streaming (API 9.5)** — `sendMessageDraft` streams partial text to the user while the
  reply is being generated, then the final message is sent.
- **Threads in private chats (API 9.3)** — `message_thread_id` / `is_topic_message` supported
  in private chats; `has_topics_enabled` on `User`. (Used opportunistically, not required.)

> ⚠️ **Implementer caveat:** exact method/field names and the interaction between
> `sendMessageDraft` and `answerGuestQuery` are very new. Verify each against the live API at
> build time. If incremental drafting is not permitted inside a guest reply, fall back to a
> single edited/finalized message (see §6).

## 3. Decisions (locked)

| Area | Choice |
|------|--------|
| AI platform | **Groq** (free tier, OpenAI-compatible, fast streaming; e.g. Llama 3.3 70B) |
| Language / framework | **Python + aiogram 3** (async, webhook + raw API friendly) |
| Webhook / TLS | **Caddy** reverse proxy with automatic Let's Encrypt HTTPS (requires a domain) |
| Run / ops | **Docker Compose** (`docker compose up -d` / `down`) |
| Memory | **Short context memory** in SQLite (last N messages per user/chat) |
| Modes | **Guest mode only** (member mode deferred) |

## 4. Architecture

```
Telegram  ──HTTPS webhook──▶  Caddy (:443, auto-TLS)  ──▶  bot (aiogram, :8080 internal)
                                                              │
                                                              ├─▶ Groq API (streaming chat completions)
                                                              └─▶ SQLite (short conversation memory)
```

Everything runs via `docker compose up -d` on the VPS. Caddy terminates TLS and
reverse-proxies to the bot container. The bot port is internal to the Docker network and is
**not** published publicly.

## 5. Components

Each unit has one purpose, a defined interface, and is independently testable.

- **`config.py`** — loads env (`BOT_TOKEN`, `GROQ_API_KEY`, `WEBHOOK_DOMAIN`,
  `WEBHOOK_SECRET`, `GROQ_MODEL`, `CONTEXT_MESSAGES`) from `.env`. Fails fast on missing
  required values.
- **`telegram/webhook.py`** — aiohttp app that aiogram mounts on; validates the Telegram
  secret-token header; routes updates to handlers. Registers the webhook on startup.
- **`telegram/guest.py`** — handles the `guest_message` update: extracts user text,
  `guest_query_id`, and caller context; calls the AI service; streams the reply; finalizes
  via `answerGuestQuery`.
- **`ai/groq_client.py`** — wraps Groq's OpenAI-compatible streaming endpoint.
  Interface: `stream_completion(messages) -> AsyncIterator[str]`. Provider-swappable so the
  AI backend can change without touching Telegram code.
- **`memory/store.py`** — SQLite-backed last-N history keyed by `(chat_id, user_id)`, with
  TTL-based pruning. Interface: `get_history(...)`, `append(...)`.
- **`streaming.py`** — throttled streamer: accumulates Groq chunks and updates the Telegram
  message (`sendMessageDraft` while generating, then final send) at most ~once/second to
  respect rate limits.

## 6. Data flow (one guest interaction)

1. A user in any chat types `@brainratbot <question>` → Telegram sends a `guest_message`
   update.
2. The bot loads short history for that `(chat_id, user_id)` and appends the new message.
3. It calls Groq with streaming; as chunks arrive, `streaming.py` shows a live-updating draft.
4. On completion, the reply is finalized with `answerGuestQuery` (one reply, per guest rules)
   and the exchange is saved to memory.

**Streaming fallback:** if the live API does not allow incremental drafts within a guest
reply, accumulate the full Groq output (optionally showing a "typing"/draft once) and send the
single finalized `answerGuestQuery`.

## 7. Error handling

- Groq error/timeout → graceful fallback message ("⚠️ AI unavailable, try again").
- Rate limit (429) from Groq or Telegram → exponential backoff.
- Output > Telegram's 4096-char limit → truncate or split into a couple of messages.
- Invalid/expired `guest_query_id` → log and drop.
- Webhook secret-token header mismatch → respond `403`.

## 8. Security

- The real bot token lives **only** in an untracked `.env` (git-ignored). A committed
  `.env.example` holds placeholders.
- A Telegram webhook **secret token** header is checked on every incoming request.
- **Action item:** the bot token was shared in plain text during planning — revoke/regenerate
  it via BotFather and store the fresh token in `.env`. The literal token is never written to
  any committed file.

## 9. Deployment / ops (to be documented in README.md)

- **Ports:**
  - `443` — Caddy, public HTTPS for the Telegram webhook (open in VPS firewall).
  - `80` — Caddy, Let's Encrypt ACME HTTP challenge (open in VPS firewall).
  - `8080` — bot, **internal to the Docker network only** (not published).
- **Start:** `docker compose up -d` (also registers the webhook with Telegram on boot).
- **Stop:** `docker compose down`.
- **Logs:** `docker compose logs -f bot`.
- **Prerequisites:** a domain A-record pointing at the VPS IP; Guest Mode enabled for the bot
  in BotFather's MiniApp; `.env` populated.

## 10. Testing

- **Unit:** Groq client (mocked stream), memory store, streaming throttler, `guest_message`
  parsing — using synthetic Telegram updates.
- **Integration:** local webhook handler fed a synthetic `guest_message` payload, asserting
  `answerGuestQuery` is called with the streamed content.

## 11. Out of scope (YAGNI / deferred)

- Full member mode (bot added to a group/DM with history access).
- Multi-thread topic management beyond opportunistic `message_thread_id` passthrough.
- Multiple simultaneous AI providers / model routing.
- Persistent long-term memory or RAG.
