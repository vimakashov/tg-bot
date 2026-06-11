import pytest
from bot.telegram.api import TelegramError
from bot.telegram.business import (
    BusinessConnection, parse_business_connection,
    BusinessMessage, parse_business_message,
    handle_business_connection,
    handle_business_message,
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


class FakeAI:
    def __init__(self, chunks=None, error=None):
        self._chunks = chunks or []
        self._error = error

    async def stream_completion(self, messages):
        if self._error:
            raise self._error
        for c in self._chunks:
            yield c


class FakeApi:
    def __init__(self, error=None, rich_error=None):
        self.sent = []         # successful sends (rich or plain): (conn, chat, text)
        self.rich_sent = []    # every rich attempt
        self.plain_sent = []   # every plain attempt
        self._error = error
        self._rich_error = rich_error

    async def send_rich_business_message(self, business_connection_id, chat_id, text):
        self.rich_sent.append((business_connection_id, chat_id, text))
        if self._rich_error:
            raise self._rich_error
        self.sent.append((business_connection_id, chat_id, text))

    async def send_business_message(self, business_connection_id, chat_id, text):
        self.plain_sent.append((business_connection_id, chat_id, text))
        if self._error:
            raise self._error
        self.sent.append((business_connection_id, chat_id, text))


BUSINESS_PROMPT = "Reply as the owner."


class Cfg:
    context_messages = 10
    business_system_prompt = BUSINESS_PROMPT


def _enabled_conn(owner_id=555):
    return {"connection_id": "conn1", "owner_user_id": owner_id,
            "can_reply": True, "is_enabled": True}


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


async def test_business_autopilot_replies_and_persists():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(["Hel", "lo!"]), FakeApi()
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    assert api.sent == [("conn1", 999, "Hello!")]
    assert store.appended == [("user", "hi"), ("assistant", "Hello!")]


async def test_business_skips_owner_own_messages():
    store = FakeStore(connection=_enabled_conn(owner_id=555))
    ai, api = FakeAI(["should not run"]), FakeApi()
    await handle_business_message(_msg_update(from_id=555, text="note to self"), api, ai, store, Cfg())
    assert api.sent == []
    assert store.appended == []


async def test_business_skips_non_private_chats():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(["nope"]), FakeApi()
    await handle_business_message(_msg_update(from_id=999, chat_type="group"), api, ai, store, Cfg())
    assert api.sent == []


async def test_business_skips_empty_text():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(["nope"]), FakeApi()
    upd = _msg_update(from_id=999)
    del upd["business_message"]["text"]
    await handle_business_message(upd, api, ai, store, Cfg())
    assert api.sent == []


async def test_business_drops_when_connection_missing():
    store = FakeStore(connection=None)
    ai, api = FakeAI(["nope"]), FakeApi()
    await handle_business_message(_msg_update(from_id=999), api, ai, store, Cfg())
    assert api.sent == []


async def test_business_drops_when_can_reply_false():
    conn = _enabled_conn()
    conn["can_reply"] = False
    store = FakeStore(connection=conn)
    ai, api = FakeAI(["nope"]), FakeApi()
    await handle_business_message(_msg_update(from_id=999), api, ai, store, Cfg())
    assert api.sent == []


async def test_business_drops_when_disabled():
    conn = _enabled_conn()
    conn["is_enabled"] = False
    store = FakeStore(connection=conn)
    ai, api = FakeAI(["nope"]), FakeApi()
    await handle_business_message(_msg_update(from_id=999), api, ai, store, Cfg())
    assert api.sent == []


async def test_business_stays_silent_on_ai_error():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(error=RuntimeError("groq down")), FakeApi()
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    assert api.sent == []
    assert store.appended == []


async def test_business_stays_silent_on_empty_output():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI([]), FakeApi()
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    assert api.sent == []
    assert store.appended == []


async def test_business_does_not_persist_when_send_fails():
    store = FakeStore(connection=_enabled_conn())
    ai = FakeAI(["Hello!"])
    api = FakeApi(rich_error=TelegramError("can't parse markdown"),
                  error=RuntimeError("outside 24h window"))
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    assert api.sent == []
    assert store.appended == []


async def test_business_falls_back_to_plain_on_rich_rejection():
    store = FakeStore(connection=_enabled_conn())
    ai = FakeAI(["**Hello!**"])
    api = FakeApi(rich_error=TelegramError("can't parse markdown"))
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    # rich attempted, then plain fallback succeeded
    assert api.rich_sent == [("conn1", 999, "**Hello!**")]
    assert api.plain_sent == [("conn1", 999, "**Hello!**")]
    assert store.appended == [("user", "hi"), ("assistant", "**Hello!**")]


async def test_business_truncates_to_4096():
    store = FakeStore(connection=_enabled_conn())
    ai, api = FakeAI(["x" * 5000]), FakeApi()
    await handle_business_message(_msg_update(from_id=999, text="hi"), api, ai, store, Cfg())
    _, _, text = api.sent[0]
    assert len(text) == 4096
