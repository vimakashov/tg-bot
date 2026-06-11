import httpx
import pytest
from bot.telegram.api import TelegramApi, TelegramError


def _ok(result=True):
    return {"ok": True, "result": result}


async def test_answer_guest_query_sends_result_object():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok({"inline_message_id": "abc"}))

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    res = await api.answer_guest_query("q1", "hello", rich=False)
    assert res == {"inline_message_id": "abc"}
    assert seen["url"].endswith("/bot123:abc/answerGuestQuery")
    body = seen["json"]
    # guest_query_id + the reply wrapped as an InlineQueryResult article whose
    # InputTextMessageContent.message_text carries the reply.
    assert b"q1" in body and b"hello" in body
    assert b"input_message_content" in body and b"message_text" in body
    await api.close()


async def test_answer_guest_query_rich_uses_rich_message_markdown():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok({"inline_message_id": "abc"}))

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.answer_guest_query("q1", "**bold**", rich=True)
    body = seen["json"]
    # rich form: input_message_content carries an InputRichMessageContent
    assert b"rich_message" in body and b"markdown" in body and b"**bold**" in body
    assert b"message_text" not in body
    await api.close()


async def test_answer_guest_query_plain_uses_message_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok({"inline_message_id": "abc"}))

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.answer_guest_query("q1", "plain text", rich=False)
    body = seen["json"]
    assert b"message_text" in body and b"plain text" in body
    assert b"rich_message" not in body
    await api.close()


async def test_edit_inline_message_text():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok())

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.edit_inline_message_text("inline-1", "updated text")
    assert seen["url"].endswith("/editMessageText")
    assert b"inline-1" in seen["json"] and b"updated text" in seen["json"]
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


async def test_send_business_message_posts_connection_chat_and_text():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok({"message_id": 1}))

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.send_business_message("conn1", 999, "hello there")
    assert seen["url"].endswith("/sendMessage")
    body = seen["json"]
    assert b"conn1" in body and b"hello there" in body
    assert b"business_connection_id" in body and b"999" in body
    await api.close()


async def test_send_rich_business_message_posts_rich_markdown():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok({"message_id": 1}))

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.send_rich_business_message("conn1", 999, "**hello there**")
    assert seen["url"].endswith("/sendRichMessage")
    body = seen["json"]
    assert b"business_connection_id" in body and b"conn1" in body and b"999" in body
    assert b"rich_message" in body and b"markdown" in body and b"**hello there**" in body
    await api.close()


async def test_set_webhook_includes_business_updates():
    seen = {}

    def handler(request):
        seen["json"] = request.read()
        return httpx.Response(200, json=_ok())

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await api.set_webhook("https://bot.example.com/webhook", "s3cret")
    body = seen["json"]
    assert b"guest_message" in body
    assert b"business_connection" in body
    assert b"business_message" in body
    await api.close()


async def test_raises_on_not_ok():
    def handler(request):
        return httpx.Response(200, json={"ok": False, "description": "bad"})

    api = TelegramApi("123:abc", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(TelegramError):
        await api.answer_guest_query("q1", "hi")
    await api.close()
