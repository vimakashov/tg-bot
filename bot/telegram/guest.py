from __future__ import annotations
import logging
import re
import time
from dataclasses import dataclass

from bot.telegram.api import TelegramError

log = logging.getLogger("tgbot.guest")

TELEGRAM_MAX = 4096
FALLBACK_TEXT = "⚠️ AI is unavailable right now, please try again in a moment."
CLEAR_REPLY = "🧠 Context cleared — starting fresh."


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


def is_clear_command(text: str) -> bool:
    return text.strip().casefold() == "/clear"


def build_messages(history: list[dict], user_text: str, reply_text: str | None,
                   system_prompt: str) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
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
    if is_clear_command(user_text):
        await store.clear(gm.chat_id, gm.user_id)
        await api.answer_guest_query(gm.query_id, CLEAR_REPLY, rich=False)
        return
    
    await stream_guest_reply(gm, api, ai, store, config)


async def stream_guest_reply(gm: GuestMessage, api, ai, store, config) -> None:
    user_text = strip_bot_mention(gm.text, config.bot_username)
    history = await store.get_history(gm.chat_id, gm.user_id, config.context_messages)
    messages = build_messages(history, user_text, gm.reply_text, config.system_prompt)
    
    full_text = ""
    draft_id = time.time_ns()
    
    try:
        async for chunk in ai.stream_completion(messages):
            full_text += chunk
            await api.send_rich_message_draft(gm.chat_id, draft_id, full_text)
            
        if full_text:
            await api.send_rich_message(gm.chat_id, full_text)
            await store.append(gm.chat_id, gm.user_id, "user", user_text)
            await store.append(gm.chat_id, gm.user_id, "assistant", full_text)
            
    except Exception as e:
        log.exception("Streaming guest reply failed: %s", e)
        if full_text:
            # Fallback to plain text if something went wrong after some text was generated
            try:
                await api.send_message(gm.chat_id, full_text)
            except Exception:
                pass
        else:
            # If no text was generated, send fallback
            try:
                await api.answer_guest_query(gm.query_id, FALLBACK_TEXT, rich=False)
            except Exception:
                pass
