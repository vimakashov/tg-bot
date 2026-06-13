from __future__ import annotations
import logging
import time
import re
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


async def _answer_oneshot(api, query_id: str, text: str) -> None:
    """Single answerGuestQuery, rich-first with a plain retry on rejection.
    Used when no streaming message was ever established (AI failure / empty
    output)."""
    try:
        await api.answer_guest_query(query_id, text, rich=True)
    except TelegramError as e:
        log.warning("rich answerGuestQuery rejected, falling back to plain: %s", e)
        await api.answer_guest_query(query_id, text, rich=False)


async def stream_guest_reply(api, ai, messages, gm, store, user_text,
                             interval, clock=time.monotonic) -> None:
    """Stream the Groq reply live: deliver the first throttled chunk via
    answerGuestQuery (capturing the inline_message_id) and edit that message on
    each later throttled tick plus once at the end. On a rejected first rich send,
    drain the stream and fall back to one plain answerGuestQuery. Edit failures
    (429 / transient) are swallowed — the next tick or the final edit corrects the
    displayed text. History is persisted only after a reply is delivered."""
    inline_id = None
    full = ""
    last_emit = None
    rich_rejected = False
    last_shown = None

    async def emit(text: str) -> None:
        nonlocal inline_id, rich_rejected, last_shown
        if rich_rejected:
            return  # stop sending; finalize as a plain one-shot below
        if inline_id is None:
            try:
                res = await api.answer_guest_query(gm.query_id, text, rich=True)
                inline_id = (res or {}).get("inline_message_id")
                last_shown = text
            except TelegramError as e:
                log.warning("rich answerGuestQuery rejected, falling back to plain: %s", e)
                rich_rejected = True
        else:
            try:
                await api.edit_inline_message_text(inline_id, text, rich=True)
                last_shown = text
            except Exception:
                pass  # transient / 429: a later edit corrects the displayed text

    try:
        async for chunk in ai.stream_completion(messages):
            full += chunk
            now = clock()
            if last_emit is None or (now - last_emit) >= interval:
                await emit(full[:TELEGRAM_MAX])
                last_emit = now
    except Exception:
        log.exception("AI generation failed")

    if not full:
        # Nothing generated -> visible fallback message (matches old behaviour).
        await _answer_oneshot(api, gm.query_id, FALLBACK_TEXT)
        return

    reply = full[:TELEGRAM_MAX]
    if rich_rejected:
        # First rich send was already rejected for this recipient; deliver the
        # complete text once as plain (no rich retry — we know it'll be rejected).
        await api.answer_guest_query(gm.query_id, reply, rich=False)
    elif inline_id is None:
        # Defensive: no inline id was captured -> one-shot the full reply.
        await _answer_oneshot(api, gm.query_id, reply)
    else:
        # Final edit with the complete text — skip if the last successful emit
        # already showed it (avoids a spurious "message is not modified" warning).
        if reply != last_shown:
            try:
                await api.edit_inline_message_text(inline_id, reply, rich=True)
            except Exception:
                log.warning("final editMessageText failed; message keeps last partial")

    await store.append(gm.chat_id, gm.user_id, "user", user_text)
    await store.append(gm.chat_id, gm.user_id, "assistant", full)


async def handle_guest_message(update: dict, api, ai, store, config) -> None:
    gm = parse_guest_message(update)
    if gm is None:
        return
    user_text = strip_bot_mention(gm.text, config.bot_username)
    if is_clear_command(user_text):
        await store.clear(gm.chat_id, gm.user_id)
        await api.answer_guest_query(gm.query_id, CLEAR_REPLY, rich=False)
        return
    history = await store.get_history(gm.chat_id, gm.user_id, config.context_messages)
    messages = build_messages(history, user_text, gm.reply_text, config.system_prompt)

    # Stream the reply live: first chunk via answerGuestQuery, then edit that
    # message until generation completes. Falls back to a one-shot answer if the
    # rich path is rejected. See stream_guest_reply.
    await stream_guest_reply(api, ai, messages, gm, store, user_text,
                             config.stream_interval)
