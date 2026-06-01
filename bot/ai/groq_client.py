from __future__ import annotations
import json
from typing import AsyncIterator
import httpx

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_BASE_URL = GROQ_URL


class AIError(Exception):
    pass


def parse_sse_line(line: str) -> str | None:
    line = line.strip()
    if not line or not line.startswith("data:"):
        return None
    data = line[len("data:"):].strip()
    if data == "[DONE]":
        return None
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return None
    try:
        return obj["choices"][0]["delta"].get("content") or None
    except (KeyError, IndexError):
        return None


class GroqClient:
    def __init__(self, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL,
                 http_client: httpx.AsyncClient | None = None):
        self._api_key = api_key
        self._model = model
        self._url = base_url
        self._client = http_client or httpx.AsyncClient(timeout=60)

    async def stream_completion(self, messages: list[dict]) -> AsyncIterator[str]:
        payload = {"model": self._model, "messages": messages, "stream": True}
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with self._client.stream("POST", self._url, json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise AIError(f"Groq HTTP {resp.status_code}: {body[:200]!r}")
                async for line in resp.aiter_lines():
                    content = parse_sse_line(line)
                    if content:
                        yield content
        except httpx.HTTPError as e:
            raise AIError(f"Groq request failed: {e}") from e

    async def close(self) -> None:
        await self._client.aclose()
