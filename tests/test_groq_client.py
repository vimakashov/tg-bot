import httpx
import pytest
from bot.ai.groq_client import parse_sse_line, GroqClient, AIError


def test_parse_sse_line_extracts_content():
    line = 'data: {"choices":[{"delta":{"content":"Hel"}}]}'
    assert parse_sse_line(line) == "Hel"


def test_parse_sse_line_done_returns_none():
    assert parse_sse_line("data: [DONE]") is None


def test_parse_sse_line_blank_or_no_content_returns_none():
    assert parse_sse_line("") is None
    assert parse_sse_line('data: {"choices":[{"delta":{}}]}') is None


async def test_stream_completion_yields_chunks():
    sse_body = (
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        'data: [DONE]\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer gsk_test"
        payload = request.read()
        assert b'"stream": true' in payload or b'"stream":true' in payload
        return httpx.Response(200, text=sse_body)

    transport = httpx.MockTransport(handler)
    client = GroqClient("gsk_test", "llama-3.3-70b-versatile",
                        http_client=httpx.AsyncClient(transport=transport))
    chunks = [c async for c in client.stream_completion([{"role": "user", "content": "hi"}])]
    assert "".join(chunks) == "Hello world"
    await client.close()


async def test_stream_completion_posts_to_custom_base_url():
    sse_body = 'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'
    seen_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200, text=sse_body)

    transport = httpx.MockTransport(handler)
    client = GroqClient("any-key", "local-model",
                        base_url="http://my-llama.example.com:8080/v1/chat/completions",
                        http_client=httpx.AsyncClient(transport=transport))
    chunks = [c async for c in client.stream_completion([{"role": "user", "content": "hi"}])]
    assert "".join(chunks) == "hi"
    assert seen_urls == ["http://my-llama.example.com:8080/v1/chat/completions"]
    await client.close()


async def test_stream_completion_raises_on_http_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    client = GroqClient("gsk_test", "m", http_client=httpx.AsyncClient(transport=transport))
    with pytest.raises(AIError):
        async for _ in client.stream_completion([{"role": "user", "content": "hi"}]):
            pass
    await client.close()
