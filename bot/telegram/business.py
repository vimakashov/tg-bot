from __future__ import annotations
import logging
from dataclasses import dataclass

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
