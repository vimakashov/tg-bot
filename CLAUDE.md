# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A configurable Telegram AI bot (Bot API 10.0) with two modes, both served from one webhook process:

- **Guest Mode** — a user mentions `@<your_bot> <question>` in any chat; Telegram sends a `guest_message` update; the bot generates a reply with the **Groq** API and answers once via `answerGuestQuery`. An exact `@<bot> /clear` wipes the caller's history instead of replying.
- **Secretary (Business) Mode** — Telegram Business connection updates (`business_connection` / `business_message`); the bot replies **as the owner** in connected private 1:1 chats on full autopilot, via `sendMessage` with a `business_connection_id`.

It runs in **webhook** mode behind Caddy, on a VPS, via Docker Compose. The bot's identity is fully env-driven — `BOT_USERNAME`, `SYSTEM_PROMPT`, and `BUSINESS_SYSTEM_PROMPT` are configuration, never hardcoded; keep it that way when editing.

Designs/plans (`docs/superpowers/`): Guest-Mode core — `specs/2026-06-01-brainratbot-design.md` + `plans/2026-06-01-brainratbot.md`; `/clear` command — `specs/2026-06-01-clear-command-design.md` + `plans/2026-06-01-clear-command.md`; Secretary Mode — `specs/2026-06-03-secretary-mode-design.md` + `plans/2026-06-03-secretary-mode.md`.

## Tooling: use Serena MCP for code work

For searching, reading, and editing code in this repo, **use the Serena MCP tools** (prefix `serena`) rather than raw file/grep tools. This is mandatory for code work — do not fall back to Grep/Read/Edit on `.py` files just because Serena's tools aren't loaded yet.

- **The Serena tools are *deferred*:** at session start their schemas are not loaded — they appear only as bare names (e.g. `mcp__plugin_serena_serena__find_symbol`) in a `<system-reminder>`. You must **load them first via `ToolSearch`** (`select:<tool_name>,...`) before they can be called; calling one without loading its schema fails. Loading them is the first step, not an excuse to skip Serena.
- **First in a session:** load the startup tools via `ToolSearch`, then call `serena.initial_instructions`, then `serena.activate_project` for this directory (and `serena.onboarding` if Serena reports it hasn't been done).
- **Keep the index fresh:** the symbol cache lives in `.serena/cache/` and goes stale after code changes land out-of-session. Rebuild it with `uvx --from serena-agent serena project index` (run from the repo root) when symbol lookups look outdated.
- **Search:** `serena.find_symbol`, `serena.get_symbols_overview`, `serena.find_referencing_symbols`, `serena.search_for_pattern` — prefer these over plain Grep/Read for navigating code.
- **Edit:** `serena.replace_symbol_body`, `serena.insert_after_symbol` / `insert_before_symbol`, `serena.replace_content` — prefer these over raw Edit/Write for code changes, so edits stay symbol-aware.
- Plain Read/Bash are still fine for non-code files (configs, docs, `docker-compose.yml`, logs) and for running tests.

## Model usage (token savings)

- **Planning / design / architecture / code review:** use **Opus 4.8 at medium reasoning effort**. Reserve Opus for the work that needs judgment.
- **Implementation tasks** (writing code to a clear spec, editing files, updating tests, mechanical changes): use **Sonnet or Haiku**. Most tasks here are well-specified and don't need Opus.
- When dispatching subagents, set the implementer model to Sonnet/Haiku and keep Opus for the planner/reviewer roles.

## Commands

```bash
# Setup (local dev)
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

# Tests (TDD project — keep it green)
pytest -q                                   # full suite
pytest tests/test_guest.py -v               # one file
pytest tests/test_guest.py::test_handler_accumulates_and_answers_once -v   # one test

# Run the server locally (no Docker). Needs the 5 required env vars; DB_PATH must be writable.
BOT_TOKEN=x BOT_USERNAME=your_bot_username GROQ_API_KEY=x WEBHOOK_DOMAIN=localhost \
WEBHOOK_SECRET=s DB_PATH=/tmp/m.db PORT=8080 python -m bot.main
curl localhost:8080/health        # -> ok   (setWebhook will fail with a fake token; it's logged, server stays up)
```

`pytest.ini` sets `asyncio_mode=auto`, so async tests/fixtures need **no** `@pytest.mark.asyncio`. Note the local `.venv` is Python 3.9 while the Docker image is 3.12 — code uses `from __future__ import annotations`, so `X | None` hints work on both.

## Architecture (the big picture)

Data flow: `Telegram → Caddy (443, TLS) → aiohttp /webhook → handle_guest_message → Groq (stream) + SQLite`.

- **`bot/main.py`** wires everything and runs `web.run_app`. **`build_app` is synchronous on purpose**: all async setup (SQLite `store.init()`, `set_webhook`, the periodic prune task) happens inside aiohttp `on_startup`, so everything lives on `web.run_app`'s event loop. Do **not** open the aiosqlite connection on a different loop (e.g. via `run_until_complete` before `run_app`) — it fails at runtime with "attached to a different loop". `set_webhook` in startup is wrapped in try/except so a bad token logs-and-continues instead of aborting startup. The top-level `dispatch(update)` function routes by update type: `business_connection` → `handle_business_connection`, `business_message` → `handle_business_message`, `guest_message` → `handle_guest_message`; unknown types are silently ignored. `set_webhook` subscribes to `business_connection` + `business_message` in addition to the guest update types.
- **`bot/telegram/webhook.py`** — `create_app(handler, secret)`: checks the `X-Telegram-Bot-Api-Secret-Token` header (403 on mismatch), dispatches to `handler(update)`, and **always returns 200 even if the handler raises** (logged) to avoid Telegram retry-storms. Also serves `/health`.
- **`bot/telegram/guest.py`** — the orchestration core. `parse_guest_message` is the **single** place that knows the `guest_message` JSON shape (an explicit, documented assumption). The handler is **single-shot**: guest mode permits exactly one reply, so it accumulates the full Groq stream and calls `answer_guest_query` once. There is no per-token draft streaming in this path. It also recognizes an exact `@<bot> /clear` (via `is_clear_command`, checked right after `strip_bot_mention`): when matched it wipes the caller's `(chat_id, user_id)` history with `store.clear`, replies once with `CLEAR_REPLY`, and returns before any Groq call.
- **`bot/telegram/business.py`** — the Secretary Mode orchestration core. `parse_business_connection` and `parse_business_message` are the **single** place that know the Business update JSON shapes (same explicit assumption as `guest.py`). The handler runs in **full autopilot**: every incoming message in a connected private 1:1 chat gets a reply, unless the message is from the owner themselves (skipped silently). On AI failure or empty output it **stays silent** — unlike guest mode's visible fallback, sending a fake message as the owner is inappropriate. History is keyed by `(connection_id, chat_id)` and stored in separate `business_connections` / `business_messages` SQLite tables, leaving the guest `messages` table untouched. Replies go via `sendMessage` with a `business_connection_id` parameter.
- **`bot/telegram/api.py`** — thin raw httpx client for the Bot API. We use raw calls (not aiogram) because the Guest-Mode methods aren't in any released framework. `call()` drops `None` params and raises `TelegramError` when the API returns `ok:false`.
- **`bot/ai/groq_client.py`** — Groq OpenAI-compatible streaming. `stream_completion(messages)` is an async generator yielding text chunks; `parse_sse_line` is a pure, separately-tested function. Swappable interface so the AI backend can change without touching Telegram code.
- **`bot/memory/store.py`** — SQLite last-N history keyed by `(chat_id, user_id)`; `prune(ttl)` is wired into `main.py` (startup + hourly). History is saved **only on a successful reply**.
- **`bot/streaming.py`** — `stream_with_throttle` (rate-limited accumulator). **Currently unused by the guest path** (single-shot). It is reserved for the deferred streaming-via-edit / member-mode work — don't delete it assuming it's dead.

## Telegram Bot API gotchas (these are the ones that bit us)

- `answerGuestQuery` takes `guest_query_id` + **`result`** (an `InlineQueryResult`), **not** a plain `text`. The reply is wrapped as an article with `input_message_content.message_text`. Passing `text` returns `400 Bad Request: result isn't specified`.
- `answerGuestQuery` returns a `SentGuestMessage` with an `inline_message_id` → use `edit_inline_message_text` (already implemented) to add live streaming-via-edit later.
- `sendMessageDraft` is a **private-chat** method requiring a non-zero `draft_id`, finalized with `sendMessage` — it is **not** valid for guest queries. Don't reintroduce it into the guest path.
- **Secretary Mode sending** uses plain `sendMessage` with an extra `business_connection_id` parameter — there is no separate `sendBusinessMessage` method. Two constraints apply: (1) the connection's `can_reply` must be `true` (check the stored `BusinessConnection` before calling); (2) the target chat must have been active within the last 24 hours. Sending outside that window returns an error; log and drop it.
- When changing any Bot API call, verify the exact parameter names against `https://core.telegram.org/bots/api` — the live page is large; `curl` it and grep the method's `<h4>`/`<table>` rather than relying on summaries.

## Deployment

The VPS clones from GitHub `origin` (`git@github.com:vimakashov/tg-bot.git`). **Committing locally is not deploying** — push to `origin/main`, then on the VPS:

```bash
git fetch origin && git reset --hard origin/main
docker compose build --no-cache bot        # `up -d` / `restart` alone REUSES the old image — always rebuild after code changes
docker compose up -d
docker compose exec bot grep -n input_message_content /app/bot/telegram/api.py   # verify the new code is actually in the container
```

Ports: 443/80 = Caddy (public, in firewall), 8080 = bot (internal Docker network only). Secrets live in `.env` (gitignored); `.env.example` has placeholders. README covers ports, Caddy setup (Docker default + native alternative), and run/stop.
