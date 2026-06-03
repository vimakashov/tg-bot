import pytest
from bot.main import dispatch


class Recorder:
    def __init__(self):
        self.calls = []


def _make_recorder(monkeypatch):
    """Patch the three handlers in bot.main to record which one dispatch calls."""
    import bot.main as m
    rec = Recorder()

    async def fake_guest(update, api, ai, store, config):
        rec.calls.append(("guest", update))

    async def fake_business_msg(update, api, ai, store, config):
        rec.calls.append(("business_message", update))

    async def fake_business_conn(update, store):
        rec.calls.append(("business_connection", update))

    monkeypatch.setattr(m, "handle_guest_message", fake_guest)
    monkeypatch.setattr(m, "handle_business_message", fake_business_msg)
    monkeypatch.setattr(m, "handle_business_connection", fake_business_conn)
    return rec


async def test_dispatch_routes_guest_message(monkeypatch):
    rec = _make_recorder(monkeypatch)
    await dispatch({"guest_message": {"x": 1}}, None, None, None, None)
    assert rec.calls == [("guest", {"guest_message": {"x": 1}})]


async def test_dispatch_routes_business_connection(monkeypatch):
    rec = _make_recorder(monkeypatch)
    await dispatch({"business_connection": {"id": "c1"}}, None, None, None, None)
    assert rec.calls == [("business_connection", {"business_connection": {"id": "c1"}})]


async def test_dispatch_routes_business_message(monkeypatch):
    rec = _make_recorder(monkeypatch)
    await dispatch({"business_message": {"x": 1}}, None, None, None, None)
    assert rec.calls == [("business_message", {"business_message": {"x": 1}})]


async def test_dispatch_unknown_update_is_ignored(monkeypatch):
    rec = _make_recorder(monkeypatch)
    await dispatch({"edited_message": {"x": 1}}, None, None, None, None)
    assert rec.calls == []
