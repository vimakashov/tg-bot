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

    async def answer_guest_query(self, guest_query_id: str, text: str) -> object:
        return await self.call("answerGuestQuery", guest_query_id=guest_query_id, text=text)

    async def send_message_draft(self, chat_id: int, text: str,
                                 guest_query_id: str | None = None) -> object:
        return await self.call("sendMessageDraft", chat_id=chat_id, text=text,
                               guest_query_id=guest_query_id)

    async def set_webhook(self, url: str, secret_token: str) -> object:
        return await self.call("setWebhook", url=url, secret_token=secret_token,
                               allowed_updates=["guest_message", "message"])

    async def close(self) -> None:
        await self._client.aclose()
