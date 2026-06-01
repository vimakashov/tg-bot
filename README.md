# Telegram Guest-Mode AI Bot

A configurable AI Telegram bot answering via **Guest Mode**: mention `@<your_bot> <question>`
in any private chat or group and it replies with a Groq-generated answer. Runs in webhook mode
behind Caddy (automatic HTTPS) via Docker Compose. The bot's identity (username, system prompt)
is set entirely through environment variables — nothing is hardcoded.

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

## Caddy (HTTPS reverse proxy)

Telegram only delivers webhooks over **HTTPS with a valid certificate**. Caddy handles
this for you: it obtains and auto-renews a free Let's Encrypt certificate and reverse-proxies
incoming requests to the bot container.

### Default: Caddy in Docker (nothing to install)

In the default setup you do **not** install Caddy separately — it runs as the `caddy` service
from [docker-compose.yml](docker-compose.yml) using the official `caddy:2.8-alpine` image.
`docker compose up -d` pulls and starts it automatically.

How the pieces connect:

- [Caddyfile](Caddyfile) is the entire configuration:

  ```
  {$WEBHOOK_DOMAIN} {
      reverse_proxy bot:8080
  }
  ```

  `{$WEBHOOK_DOMAIN}` is read from Caddy's environment. Compose injects it from your `.env`
  (`WEBHOOK_DOMAIN: ${WEBHOOK_DOMAIN}` in the `caddy` service), so the **only** thing you
  configure is `WEBHOOK_DOMAIN` in `.env`. `bot:8080` is the bot container's name on the
  internal Docker network — that port is never published to the host.

- The `./caddy_data` volume persists issued certificates. **Keep it** across restarts —
  deleting it forces re-issuance and can hit Let's Encrypt rate limits.

**Requirements for the certificate to issue successfully:**

1. `WEBHOOK_DOMAIN` (e.g. `bot.example.com`) has a DNS **A-record pointing at the VPS IP**.
   Check with `dig +short <WEBHOOK_DOMAIN>`.
2. Ports **80 and 443 are open** in the VPS firewall and not used by another web server
   (stop any host nginx/apache on those ports first).
3. The domain is publicly reachable (Let's Encrypt validates from the internet).

Apply config changes (after editing the `Caddyfile`) without downtime:

```bash
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
# or simply: docker compose restart caddy
```

Watch certificate issuance / troubleshoot:

```bash
docker compose logs -f caddy        # look for "certificate obtained successfully"
```

Common issues: `WEBHOOK_DOMAIN` unset or still `bot.example.com` → no cert; DNS not pointing
at the VPS → ACME challenge fails; port 80/443 blocked or already in use → issuance hangs.

### Alternative: native Caddy on the VPS (no Caddy container)

Prefer Caddy installed on the host instead of in Docker? Install it from the official repo
(Debian/Ubuntu):

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

(For other systems see https://caddyserver.com/docs/install.) Caddy installs as a systemd
service. Then make two changes:

1. **Publish the bot to localhost only** so the host Caddy can reach it. In
   `docker-compose.yml`, remove the `caddy` service and give the `bot` service:

   ```yaml
   ports:
     - "127.0.0.1:8080:8080"
   ```

2. **Configure `/etc/caddy/Caddyfile`** (replace the domain with yours):

   ```
   bot.example.com {
       reverse_proxy 127.0.0.1:8080
   }
   ```

Then reload and manage Caddy with systemd:

```bash
sudo systemctl reload caddy     # apply Caddyfile changes
sudo systemctl status caddy     # check it's running / cert obtained
sudo journalctl -u caddy -f     # follow logs
```

With native Caddy, start/stop the bot with `docker compose up -d bot` / `docker compose down`,
and Caddy runs independently as a system service.

## Verify

```bash
curl https://<WEBHOOK_DOMAIN>/health   # -> ok
```

Then mention `@<your_bot> hello` in any chat where Guest Mode is allowed (use the
`BOT_USERNAME` you configured in `.env`).

Send `@<your_bot> /clear` to reset your own conversation context in that chat; the
bot confirms and the next message starts fresh. The reset is per-user, per-chat —
it only clears your history, not other participants'.

## Architecture

`Telegram → Caddy (443, TLS) → bot (aiohttp, 8080) → Groq (stream) + SQLite (memory)`

See `docs/superpowers/specs/2026-06-01-brainratbot-design.md` for the full design.

## Running tests

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pytest -v
```
