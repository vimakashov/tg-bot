import pytest
from bot.telegram.business import (
    BusinessConnection, parse_business_connection,
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
