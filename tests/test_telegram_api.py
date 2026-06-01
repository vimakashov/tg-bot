import httpx
import pytest
from bot.telegram.api import TelegramApi, TelegramError


def _ok(result=True):
    return {"ok": True, "result": result}


async def test_answer_guest_query_posts_expected():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok({"message_id": 5}))

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    res = await api.answer_guest_query("q1", "hello")
    assert res == {"message_id": 5}
    assert seen["url"].endswith("/bot123:abc/answerGuestQuery")
    assert b"q1" in seen["json"] and b"hello" in seen["json"]
    await api.close()


async def test_send_message_draft_includes_guest_query_id():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok())

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.send_message_draft(chat_id=42, text="partial", guest_query_id="q1")
    assert seen["url"].endswith("/sendMessageDraft")
    assert b'"q1"' in seen["json"]
    await api.close()


async def test_set_webhook_posts_url_and_secret():
    seen = {}

    def handler(request):
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok())

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.set_webhook("https://bot.example.com/webhook", "s3cret")
    assert b"bot.example.com/webhook" in seen["json"]
    assert b"s3cret" in seen["json"]
    assert b"guest_message" in seen["json"]
    await api.close()


async def test_raises_on_not_ok():
    def handler(request):
        return httpx.Response(200, json={"ok": False, "description": "bad"})

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(TelegramError):
        await api.answer_guest_query("q1", "hi")
    await api.close()
