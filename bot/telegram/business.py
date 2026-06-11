from __future__ import annotations
import logging
from dataclasses import dataclass

from bot.telegram.api import TelegramError
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

    # AI failure or empty output -> stay silent. A fake "AI unavailable" message
    # sent AS the owner would be inappropriate (spec section 3, 6).
    if not full:
        return

    reply = full[:TELEGRAM_MAX]
    try:
        await api.send_rich_business_message(bm.connection_id, bm.chat_id, reply)
    except TelegramError as e:
        # Telegram rejected the rich Markdown -> resend as plain text (AS the
        # owner). Log the reason: a silent fallback would hide a systematically-
        # failing rich path, which looks exactly like "no formatting".
        log.warning("rich sendRichMessage rejected (chat %s), falling back to plain: %s",
                    bm.chat_id, e)
        try:
            await api.send_business_message(bm.connection_id, bm.chat_id, reply)
        except Exception:
            log.exception("send_business_message (plain fallback) failed (chat %s)", bm.chat_id)
            return
    except Exception:
        log.exception("send_rich_business_message failed (chat %s)", bm.chat_id)
        return

    # Persist only on a successful send (mirrors the guest path).
    await store.append_business(bm.connection_id, bm.chat_id, "user", bm.text)
    await store.append_business(bm.connection_id, bm.chat_id, "assistant", reply)
