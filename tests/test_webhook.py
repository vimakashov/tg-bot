import pytest
from bot.telegram.webhook import create_app


@pytest.fixture
def received():
    return []


@pytest.fixture
def app(received):
    async def handler(update):
        received.append(update)
    return create_app(handler, secret="s3cret")


async def test_rejects_missing_secret(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.post("/webhook", json={"guest_message": {}})
    assert resp.status == 403


async def test_rejects_wrong_secret(aiohttp_client, app):
    client = await aiohttp_client(app)
    resp = await client.post("/webhook", json={"x": 1},
                             headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
    assert resp.status == 403


async def test_accepts_valid_secret_and_dispatches(aiohttp_client, app, received):
    client = await aiohttp_client(app)
    resp = await client.post("/webhook", json={"guest_message": {"id": 1}},
                             headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"})
    assert resp.status == 200
    assert received == [{"guest_message": {"id": 1}}]
