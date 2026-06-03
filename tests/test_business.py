import pytest
from bot.telegram.business import (
    BusinessConnection, parse_business_connection,
    BusinessMessage, parse_business_message,
)


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
