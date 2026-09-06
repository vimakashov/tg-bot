# Ngrok Integration for Local Development

## Context
The current setup is designed for a VPS deployment where Caddy handles HTTPS on port 443. For local development on a Mac, Telegram cannot reach the local machine's webhooks directly. We need a way to provide a public HTTPS endpoint that tunnels traffic to the local Docker environment without using port 443 on the host machine.

## Goal
Enable local development using `ngrok` as a tunnel, ensuring:
1. Telegram can send webhooks via HTTPS.
2. No conflict with port 443 on the host Mac.
3. All infrastructure is managed via Docker Compose.

## Architecture & Data Flow
`Telegram API` $\rightarrow$ `ngrok Public URL (HTTPS)` $\rightarrow$ `ngrok container` $\rightarrow$ `Caddy container (port 80)` $\rightarrow$ `Bot container (port 8080)`

**Note on Caddy connectivity:**
* **Internal (Tunnel):** The `ngrok` container communicates with `caddy` via the internal Docker network using **HTTP** on port `80`.
* **External (Local Testing):** The `caddy` container is configured to expose port `4443` to your Mac, allowing you to test the HTTPS endpoint locally via `https://localhost:4443`.

**Note on Port 4443:**
The `caddy` container will be configured to expose port `4443` to the host machine for local testing/access, but the `ngrok` container will communicate with `caddy` via the internal Docker network on port `80`.

## Implementation Details

### 1. `docker-compose.yml` changes
- **Add `ngrok` service**:
  - Uses `ngrok/ngrok` image.
  - Command: `http caddy:80` (tunnels to the caddy service on the internal network).
  - Requires `NGROK_AUTHTOKEN` in `.env` (for persistent URLs, though not strictly required for simple testing).
- **Modify `caddy` service**:
  - Change `ports` from `"80:80"` and `"443:443"` to `"80:80"` and `"4443:443"`.
  - This allows local access via `https://localhost:4443`.

### 2. `.env` changes
- **`WEBHOOK_DOMAIN`**: Users will manually update this with the URL provided by the `ngrok` container logs after starting it.

### 3. Workflows
*Note: This is a "one-time setup per session" workflow because free ngrok URLs change on restart.*
1. `docker compose up -d ngrok`
2. Check logs: `docker compose logs ngrok` to find the URL.
3. Update `.env`: `WEBHOOK_DOMAIN=your-id.ngrok-free.app`
4. `docker compose up -d` (starts the rest of the stack)

## Trade-offs & Constraints
- **Pros**: Extremely easy setup; bypasses router/firewall issues; provides instant HTTPS.
- **Cons**: On the free tier, the URL changes on every restart, requiring an `.env` update.

## Verification
- Successful webhook registration in Telegram API (verify via `getWebhook` endpoint).
- `curl`ing the ngrok URL to ensure it reaches the `bot` container.
- Verifying Caddy can still be accessed via `localhost:4443`.
