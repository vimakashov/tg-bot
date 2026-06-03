from __future__ import annotations
import httpx


class TelegramError(Exception):
    pass


class TelegramApi:
    def __init__(self, token: str, http_client: httpx.AsyncClient | None = None):
        self._base = f"https://api.telegram.org/bot{token}"
        self._client = http_client or httpx.AsyncClient(timeout=30)

    async def call(self, method: str, **params) -> object:
        payload = {k: v for k, v in params.items() if v is not None}
        try:
            resp = await self._client.post(f"{self._base}/{method}", json=payload)
        except httpx.HTTPError as e:
            raise TelegramError(f"{method} request failed: {e}") from e
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"{method} failed: {data.get('description')}")
        return data["result"]

    async def answer_guest_query(self, guest_query_id: str, text: str,
                                 result_id: str = "1") -> object:
        # Bot API 10.0: answerGuestQuery takes a `result` (InlineQueryResult),
        # NOT a plain `text`. We wrap the reply as an article whose message body
        # is an InputTextMessageContent. Returns a SentGuestMessage (with
        # inline_message_id), which can later be edited via editMessageText.
        result = {
            "type": "article",
            "id": result_id,
            "title": "AI",
            "input_message_content": {"message_text": text},
        }
        return await self.call("answerGuestQuery",
                               guest_query_id=guest_query_id, result=result)

    async def edit_inline_message_text(self, inline_message_id: str, text: str) -> object:
        return await self.call("editMessageText",
                               inline_message_id=inline_message_id, text=text)

    async def send_business_message(self, business_connection_id: str, chat_id: int,
                                    text: str) -> object:
        # Secretary mode: standard sendMessage with a business_connection_id sends
        # the message AS the owner. The chat must have been active in the last 24h
        # and the connection's can_reply must be true, or the API returns ok:false.
        return await self.call("sendMessage",
                               business_connection_id=business_connection_id,
                               chat_id=chat_id, text=text)

    async def set_webhook(self, url: str, secret_token: str) -> object:
        return await self.call("setWebhook", url=url, secret_token=secret_token,
                               allowed_updates=["guest_message", "message"])

    async def close(self) -> None:
        await self._client.aclose()
