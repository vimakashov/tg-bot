import pytest
from bot.telegram.business import (
    BusinessConnection, parse_business_connection,
    BusinessMessage, parse_business_message,
    handle_business_connection,
)


class FakeStore:
    def __init__(self, history=None, connection=None):
        self._history = history or []
        self._connection = connection
        self.upserts = []
        self.appended = []

    async def upsert_connection(self, connection_id, owner_user_id, can_reply, is_enabled):
        self.upserts.append((connection_id, owner_user_id, can_reply, is_enabled))
        self._connection = {"connection_id": connection_id, "owner_user_id": owner_user_id,
                            "can_reply": can_reply, "is_enabled": is_enabled}

    async def get_connection(self, connection_id):
        return self._connection

    async def get_business_history(self, connection_id, chat_id, limit):
        return list(self._history)

    async def append_business(self, connection_id, chat_id, role, content):
        self.appended.append((role, content))


def _conn_update(connection_id="conn1", owner_id=555, can_reply=True, is_enabled=True):
    return {
        "business_connection": {
            "id": connection_id,
            "user": {"id": owner_id},
            "can_reply": can_reply,
            "is_enabled": is_enabled,
        }
    }


def test_parse_business_connection_returns_none_for_other_update():
    assert parse_business_connection({"message": {"text": "hi"}}) is None


def test_parse_business_connection_extracts_fields():
    conn = parse_business_connection(_conn_update())
    assert conn == BusinessConnection(connection_id="conn1", owner_user_id=555,
                                      can_reply=True, is_enabled=True)


def test_parse_business_connection_disabled():
    conn = parse_business_connection(_conn_update(can_reply=False, is_enabled=False))
    assert conn.can_reply is False
    assert conn.is_enabled is False


def _msg_update(connection_id="conn1", chat_id=999, chat_type="private",
                from_id=999, text="hello", reply=None):
    bm = {
        "business_connection_id": connection_id,
        "from": {"id": from_id},
        "chat": {"id": chat_id, "type": chat_type},
        "text": text,
    }
    if reply is not None:
        bm["reply_to_message"] = {"text": reply}
    return {"business_message": bm}


def test_parse_business_message_returns_none_for_other_update():
    assert parse_business_message({"message": {"text": "hi"}}) is None


def test_parse_business_message_extracts_fields():
    bm = parse_business_message(_msg_update(reply="prev text"))
    assert bm == BusinessMessage(connection_id="conn1", chat_id=999, chat_type="private",
                                 from_user_id=999, text="hello", reply_text="prev text")


def test_parse_business_message_no_text_defaults_empty():
    update = _msg_update()
    del update["business_message"]["text"]
    bm = parse_business_message(update)
    assert bm.text == ""
    assert bm.reply_text is None


async def test_handle_business_connection_upserts():
    store = FakeStore()
    await handle_business_connection(_conn_update(connection_id="c9", owner_id=42,
                                                  can_reply=True, is_enabled=True), store)
    assert store.upserts == [("c9", 42, True, True)]


async def test_handle_business_connection_disabled_roundtrip():
    store = FakeStore()
    await handle_business_connection(_conn_update(can_reply=False, is_enabled=False), store)
    assert store.upserts == [("conn1", 555, False, False)]


async def test_handle_business_connection_ignores_other_updates():
    store = FakeStore()
    await handle_business_connection({"message": {}}, store)
    assert store.upserts == []
