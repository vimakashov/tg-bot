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
