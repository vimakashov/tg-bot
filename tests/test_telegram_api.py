import httpx
import json
import pytest
from bot.telegram.api import TelegramApi

async def test_send_rich_message_payload():
    requests = []
    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": "some_result"})
    
    mock_transport = httpx.MockTransport(handler)
    api = TelegramApi(token="dummy", http_client=httpx.AsyncClient(transport=mock_transport))
    
    await api.send_rich_message(chat_id=123, text="final")
    
    request = requests[0]
    assert "sendRichMessage" in request.url.path
    data = json.loads(request.content.decode())
    assert data["chat_id"] == 123
    assert data["input_message_content"]["rich_message"]["markdown"] == "final"
