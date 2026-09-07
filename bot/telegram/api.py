from __future__ import annotations
import httpx
import logging

log = logging.getLogger("tgbot.api")


class TelegramError(Exception):
    pass


class TelegramApi:
    def __init__(self, token: str, http_client: httpx.AsyncClient | None = None,
                 config: object | None = None):
        self._base = f"https://api.telegram.org/bot{token}"
        self._client = http_client
        self._config = config

    @property
    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def call(self, method: str, **params) -> object:
        if "chat_id" in params:
            params["chat_id"] = int(params["chat_id"])
        if "draft_id" in params:
            params["draft_id"] = int(params["draft_id"])
        payload = {k: v for k, v in params.items() if v is not None}
        try:
            resp = await self._http_client.post(f"{self._base}/{method}", json=payload)
        except httpx.HTTPError as e:
            raise TelegramError(f"{method} request failed: {e}") from e
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"{method} failed: {data.get('description')}")
        return data["result"]

    async def answer_guest_query(self, guest_query_id: str, text: str,
                                 result_id: str = "1", rich: bool = True) -> object:
        # Bot API 10.0: answerGuestQuery takes a `result` (InlineQueryResult),
        # NOT a plain `text`. We wrap the reply as an article. Bot API 10.1 lets
        # the article's input_message_content be an InputRichMessageContent, so
        # the LLM's Markdown is rendered by Telegram. `rich=False` falls back to a
        # plain InputTextMessageContent when Telegram rejects the formatting.
        if rich:
            content = {"rich_message": {"markdown": text}}
        else:
            content = {"message_text": text}
        result = {
            "type": "article",
            "id": result_id,
            "title": "AI",
            "input_message_content": content,
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

    async def send_rich_business_message(self, business_connection_id: str, chat_id: int,
                                          text: str) -> object:
        # Bot API 10.1 Secretary mode: sendRichMessage with a business_connection_id
        # sends AS the owner with Markdown rendered by Telegram. The LLM's Markdown
        # goes straight into rich_message.markdown — no escaping. Same 24h-window /
        # can_reply constraints as send_business_message; ok:false -> TelegramError.
        return await self.call("sendRichMessage",
                                business_connection_id=business_connection_id,
                                chat_id=chat_id,
                                rich_message={"markdown": text})

    async def send_rich_message(self, chat_id: int, text: str):
        return await self.call("sendRichMessage",
                                 chat_id=chat_id,
                                 input_message_content={"rich_message": {"markdown": text}})

    async def send_message(self, chat_id: int, text: str) -> object:
        return await self.call("sendMessage", chat_id=chat_id, text=text)

    async def resolve_image_url(self, image_id: str) -> str | None:
        """Resolve an image URL from a JSON endpoint.

        GET {image_base_url}/{image_id}.json — returns the 'thumbnail' value
        or None on any failure (HTTP error, invalid JSON, missing key).
        """
        if not self._config or not self._config.image_base_url:
            return None
        url = f"{self._config.image_base_url}/{image_id}.json"
        try:
            resp = await self._http_client.get(url)
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except Exception:
            return None
        thumbnail = data.get("thumbnail") or ""
        if not thumbnail:
            return None
        return str(thumbnail)

    async def upload_photo_from_url(self, chat_id: int, url: str,
                                    business_connection_id: str | None = None) -> str | None:
        """Download an image from a URL and send it as a Telegram photo.

        Returns the Telegram file_id on success, or None on any failure.
        """
        try:
            resp = await self._http_client.get(url)
            resp.raise_for_status()
            photo_bytes = resp.content
        except Exception:
            log.warning("Failed to download image from %s", url)
            return None

        data = {"chat_id": str(chat_id)}
        if business_connection_id is not None:
            data["business_connection_id"] = business_connection_id

        files = {"photo": ("photo.jpg", photo_bytes, "image/jpeg")}

        try:
            resp = await self._http_client.post(
                f"{self._base}/sendPhoto",
                data=data,
                files=files,
            )
        except Exception:
            log.warning("sendPhoto upload failed for chat %s", chat_id)
            return None

        result = resp.json()
        if not result.get("ok"):
            log.warning("sendPhoto API error: %s", result.get("description"))
            return None

        file_id = result.get("result", {}).get("file_id")
        return file_id if isinstance(file_id, str) else None

    async def send_photo(self, chat_id: int, file_id: str,
                          business_connection_id: str | None = None) -> bool:
        """Send a photo by its Telegram file_id.

        Returns True if the API returns ok:true, False otherwise.
        """
        kwargs = {"chat_id": chat_id, "photo": file_id}
        if business_connection_id is not None:
            kwargs["business_connection_id"] = business_connection_id
        try:
            await self.call("sendPhoto", **kwargs)
            return True
        except TelegramError:
            return False



    async def send_rich_message_draft(self, chat_id: int, draft_id: int, text: str):
        return await self.call("sendRichMessageDraft",
                                chat_id=chat_id,
                                draft_id=draft_id,
                                rich_message={"markdown": text})

    async def set_webhook(self, url: str, secret_token: str) -> object:
        return await self.call("setWebhook", url=url, secret_token=secret_token,
                                allowed_updates=["guest_message", "message",
                                                 "business_connection", "business_message"])

    async def close(self) -> None:
        await self._http_client.aclose()
