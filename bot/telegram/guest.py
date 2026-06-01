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
    """Extract a GuestMessage from a Telegram update.

    ASSUMPTION: the `guest_message` JSON shape (guest_query_id, chat.id,
    from.id, text, reply_to_message.text) follows Bot API 10.0 and is NOT yet
    verified against the live API. If the real shape differs, THIS is the only
    function to change — the rest of the code depends solely on GuestMessage.
    """
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
