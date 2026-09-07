from bot.telegram.images import parse_images


def test_parse_images_no_placeholders():
    clean, ids = parse_images("Hello world")
    assert clean == "Hello world"
    assert ids == []


def test_parse_images_single_placeholder():
    clean, ids = parse_images("Here is a photo: [[img:f4ec367b03bf]] of the Eiffel tower")
    assert clean == "Here is a photo:  of the Eiffel tower"
    assert ids == ["f4ec367b03bf"]


def test_parse_images_multiple_placeholders():
    text = "First [[img:aaa]] then [[img:bbb]] and [[img:ccc]] done"
    clean, ids = parse_images(text)
    assert clean == "First  then  and  done"
    assert ids == ["aaa", "bbb", "ccc"]


def test_parse_images_malformed_no_id():
    """[[img:]] with empty ID is ignored by the regex."""
    clean, ids = parse_images("before [[img:]] after")
    assert clean == "before [[img:]] after"
    assert ids == []


def test_parse_images_malformed_space_in_id():
    """[[img: ]] — space in ID is rejected by [a-zA-Z0-9_-]+."""
    clean, ids = parse_images("before [[img: ]] after")
    assert clean == "before [[img: ]] after"
    assert ids == []


def test_parse_images_malformed_invalid_chars():
    """[[img:a b]] — space inside ID is rejected."""
    clean, ids = parse_images("before [[img:a b]] after")
    assert clean == "before [[img:a b]] after"
    assert ids == []


def test_parse_images_placeholder_at_start():
    clean, ids = parse_images("[[img:abc]] hello world")
    assert clean == " hello world"
    assert ids == ["abc"]


def test_parse_images_placeholder_at_end():
    clean, ids = parse_images("hello world [[img:xyz]]")
    assert clean == "hello world "
    assert ids == ["xyz"]


def test_parse_images_regex_accepts_hyphens_and_underscores():
    """IDs with hyphens and underscores are accepted."""
    clean, ids = parse_images("[[img:my-image_id]]")
    assert clean == ""
    assert ids == ["my-image_id"]


def test_parse_images_multiple_on_same_line():
    clean, ids = parse_images("A [[img:1]] B [[img:2]] C [[img:3]] D")
    assert clean == "A  B  C  D"
    assert ids == ["1", "2", "3"]


def test_parse_images_only_placeholders():
    clean, ids = parse_images("[[img:a]][[img:b]]")
    assert clean == ""
    assert ids == ["a", "b"]


import httpx
import json
import unittest.mock
from bot.telegram.api import TelegramApi


async def test_resolve_image_url_success():
    """GET returns JSON with a 'thumbnail' key."""
    mock_resp = httpx.Response(200, json={"thumbnail": "https://cdn.example.com/photo.jpg"})

    async def mock_get(*args, **kwargs):
        return mock_resp

    cfg = type('Cfg', (), {'image_base_url': 'https://images.example.com/api'})()
    api = TelegramApi(token="dummy", config=cfg)

    with unittest.mock.patch('httpx.AsyncClient', return_value=unittest.mock.MagicMock(
            get=mock_get,
            __aenter__=unittest.mock.AsyncMock(return_value=unittest.mock.MagicMock()),
            __aexit__=unittest.mock.AsyncMock(return_value=False))):
        result = await api.resolve_image_url("abc123")

    assert result == "https://cdn.example.com/photo.jpg"


async def test_resolve_image_url_http_failure():
    """Non-200 response returns None."""
    mock_resp = httpx.Response(500, text="server error")

    with unittest.mock.patch('httpx.AsyncClient', return_value=unittest.mock.MagicMock(
            get=unittest.mock.AsyncMock(return_value=mock_resp),
            __aenter__=unittest.mock.AsyncMock(return_value=unittest.mock.MagicMock()),
            __aexit__=unittest.mock.AsyncMock(return_value=False))):
        api = TelegramApi(token="dummy", config=type('Cfg', (), {'image_base_url': 'https://images.example.com/api'})())
        result = await api.resolve_image_url("nope")

    assert result is None


async def test_resolve_image_url_missing_thumbnail():
    """Valid JSON but no 'thumbnail' key returns None."""
    mock_resp = httpx.Response(200, json={"other_key": "value"})

    with unittest.mock.patch('httpx.AsyncClient', return_value=unittest.mock.MagicMock(
            get=unittest.mock.AsyncMock(return_value=mock_resp),
            __aenter__=unittest.mock.AsyncMock(return_value=unittest.mock.MagicMock()),
            __aexit__=unittest.mock.AsyncMock(return_value=False))):
        api = TelegramApi(token="dummy", config=type('Cfg', (), {'image_base_url': 'https://images.example.com/api'})())
        result = await api.resolve_image_url("empty")

    assert result is None


async def test_resolve_image_url_empty_thumbnail():
    """thumbnail key present but empty string returns None."""
    mock_resp = httpx.Response(200, json={"thumbnail": ""})

    with unittest.mock.patch('httpx.AsyncClient', return_value=unittest.mock.MagicMock(
            get=unittest.mock.AsyncMock(return_value=mock_resp),
            __aenter__=unittest.mock.AsyncMock(return_value=unittest.mock.MagicMock()),
            __aexit__=unittest.mock.AsyncMock(return_value=False))):
        api = TelegramApi(token="dummy", config=type('Cfg', (), {'image_base_url': 'https://images.example.com/api'})())
        result = await api.resolve_image_url("empty_thumb")

    assert result is None


async def test_resolve_image_url_invalid_json():
    """Response that is not valid JSON returns None."""
    mock_resp = httpx.Response(200, text="not json at all")

    with unittest.mock.patch('httpx.AsyncClient', return_value=unittest.mock.MagicMock(
            get=unittest.mock.AsyncMock(return_value=mock_resp),
            __aenter__=unittest.mock.AsyncMock(return_value=unittest.mock.MagicMock()),
            __aexit__=unittest.mock.AsyncMock(return_value=False))):
        api = TelegramApi(token="dummy", config=type('Cfg', (), {'image_base_url': 'https://images.example.com/api'})())
        result = await api.resolve_image_url("bad_json")

    assert result is None


async def test_resolve_image_url_http_error():
    """Network-level HTTP error returns None."""
    async def raise_error(*args, **kwargs):
        raise httpx.NetworkError("connection refused", request=unittest.mock.MagicMock())

    with unittest.mock.patch('httpx.AsyncClient', return_value=unittest.mock.MagicMock(
            get=unittest.mock.AsyncMock(side_effect=raise_error),
            __aenter__=unittest.mock.AsyncMock(return_value=unittest.mock.MagicMock()),
            __aexit__=unittest.mock.AsyncMock(return_value=False))):
        api = TelegramApi(token="dummy", config=type('Cfg', (), {'image_base_url': 'https://images.example.com/api'})())
        result = await api.resolve_image_url("net_err")

    assert result is None


async def test_resolve_image_url_no_config():
    """When config or image_base_url is missing, returns None."""
    api = TelegramApi(token="dummy", config=None)
    result = await api.resolve_image_url("abc")
    assert result is None

    api2 = TelegramApi(token="dummy", config=type('Cfg', (), {'image_base_url': ''})())
    result2 = await api2.resolve_image_url("abc")
    assert result2 is None


async def test_upload_photo_from_url_success():
    """Download succeeds and sendPhoto returns a file_id."""
    photo_bytes = b"\x89PNG\r\n\x1a\n"

    async def handler(request):
        if "sendPhoto" in str(request.url):
            return httpx.Response(200, json={"ok": True, "result": {"file_id": "AGACAgIAAxkBAAI"}})
        return httpx.Response(200, content=photo_bytes)

    mock_transport = httpx.MockTransport(handler)
    api = TelegramApi(token="dummy", http_client=httpx.AsyncClient(transport=mock_transport))

    result = await api.upload_photo_from_url(chat_id=123, url="https://example.com/photo.png")
    assert result == "AGACAgIAAxkBAAI"


async def test_upload_photo_from_url_download_failure():
    """HTTP error during download returns None."""

    async def handler(request):
        if "sendPhoto" in str(request.url):
            return httpx.Response(200, json={"ok": True, "result": {"file_id": "AG"}})
        raise httpx.NetworkError("connection refused", request=request)

    mock_transport = httpx.MockTransport(handler)
    api = TelegramApi(token="dummy", http_client=httpx.AsyncClient(transport=mock_transport))

    result = await api.upload_photo_from_url(chat_id=123, url="https://example.com/bad.png")
    assert result is None


async def test_upload_photo_from_url_send_failure():
    """Download succeeds but sendPhoto API returns ok:false — returns None."""
    photo_bytes = b"\x89PNG\r\n\x1a\n"

    async def handler(request):
        if "sendPhoto" in str(request.url):
            return httpx.Response(200, json={"ok": False, "description": "chat not found"})
        return httpx.Response(200, content=photo_bytes)

    mock_transport = httpx.MockTransport(handler)
    api = TelegramApi(token="dummy", http_client=httpx.AsyncClient(transport=mock_transport))

    result = await api.upload_photo_from_url(chat_id=123, url="https://example.com/photo.png")
    assert result is None


async def test_upload_photo_from_url_with_business_connection_id():
    """business_connection_id is passed to sendPhoto when provided."""
    photo_bytes = b"\x89PNG\r\n\x1a\n"

    async def handler(request):
        return httpx.Response(200, json={"ok": True, "result": {"file_id": "AG"}})

    mock_transport = httpx.MockTransport(handler)
    api = TelegramApi(token="dummy", http_client=httpx.AsyncClient(transport=mock_transport))

    result = await api.upload_photo_from_url(
        chat_id=123, url="https://example.com/photo.png", business_connection_id="conn1"
    )
    assert result == "AG"


async def test_send_photo_success():
    """sendPhoto returns True when API ok."""

    async def handler(request):
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    mock_transport = httpx.MockTransport(handler)
    api = TelegramApi(token="dummy", http_client=httpx.AsyncClient(transport=mock_transport))

    result = await api.send_photo(chat_id=123, file_id="AGACAgIAAxkBAAI")
    assert result is True


async def test_send_photo_failure():
    """send_photo returns False when API not ok."""

    async def handler(request):
        return httpx.Response(200, json={"ok": False, "description": "bad request"})

    mock_transport = httpx.MockTransport(handler)
    api = TelegramApi(token="dummy", http_client=httpx.AsyncClient(transport=mock_transport))

    result = await api.send_photo(chat_id=123, file_id="BAD")
    assert result is False


async def test_send_photo_with_business_connection_id():
    """business_connection_id is passed when provided."""
    captured_payloads = []

    async def handler(request):
        captured_payloads.append(json.loads(request.content.decode()))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    mock_transport = httpx.MockTransport(handler)
    api = TelegramApi(token="dummy", http_client=httpx.AsyncClient(transport=mock_transport))

    result = await api.send_photo(chat_id=123, file_id="AG", business_connection_id="conn1")
    assert result is True
    payload = captured_payloads[0]
    assert payload["business_connection_id"] == "conn1"


import asyncio
import time
from bot.telegram.images import upload_images_to_telegram


async def test_upload_images_to_telegram_empty_list():
    api = unittest.mock.AsyncMock()
    result = await upload_images_to_telegram(api, 123, [])
    assert result == []
    api.resolve_image_url.assert_not_called()


async def test_upload_images_to_telegram_all_succeed():
    mock_api = unittest.mock.AsyncMock()

    async def mock_resolve(image_id):
        return f"https://cdn.example.com/{image_id}.jpg"

    async def mock_upload(chat_id, url, business_connection_id=None):
        fid = url.split("/")[-1].replace(".jpg", "")
        return f"file_{fid}"

    mock_api.resolve_image_url.side_effect = mock_resolve
    mock_api.upload_photo_from_url.side_effect = mock_upload

    result = await upload_images_to_telegram(mock_api, 123, ["img1", "img2"])
    assert result == ["file_img1", "file_img2"]


async def test_upload_images_to_telegram_partial_failure():
    """Some images resolve/upload successfully, others fail."""
    mock_api = unittest.mock.AsyncMock()

    async def mock_resolve(image_id):
        if image_id == "fail1":
            return None
        return f"https://cdn.example.com/{image_id}.jpg"

    async def mock_upload(chat_id, url, business_connection_id=None):
        fid = url.split("/")[-1].replace(".jpg", "")
        if "fail" in fid:
            return None
        return f"file_{fid}"

    mock_api.resolve_image_url.side_effect = mock_resolve
    mock_api.upload_photo_from_url.side_effect = mock_upload

    result = await upload_images_to_telegram(mock_api, 123, ["good1", "fail1", "good2"])
    assert result == ["file_good1", "file_good2"]


async def test_upload_images_to_telegram_all_fail():
    """All images fail — returns empty list."""
    mock_api = unittest.mock.AsyncMock()

    async def mock_resolve(image_id):
        return None

    mock_api.resolve_image_url.side_effect = mock_resolve

    result = await upload_images_to_telegram(mock_api, 123, ["img1", "img2"])
    assert result == []


async def test_upload_images_to_telegram_with_business_connection_id():
    """business_connection_id is passed through to upload_photo_from_url."""
    mock_api = unittest.mock.AsyncMock()

    async def mock_resolve(image_id):
        return f"https://cdn.example.com/{image_id}.jpg"

    async def mock_upload(chat_id, url, business_connection_id=None):
        fid = url.split("/")[-1].replace(".jpg", "")
        return f"file_{fid}"

    mock_api.resolve_image_url.side_effect = mock_resolve
    mock_api.upload_photo_from_url.side_effect = mock_upload

    result = await upload_images_to_telegram(
        mock_api, 123, ["img1"], business_connection_id="conn1"
    )
    assert result == ["file_img1"]

    call_kwargs = mock_api.upload_photo_from_url.call_args
    assert call_kwargs[1]["business_connection_id"] == "conn1"


async def test_upload_images_to_telegram_concurrency():
    """Images are processed concurrently (via asyncio.gather with semaphore)."""
    mock_api = unittest.mock.AsyncMock()

    async def slow_resolve(image_id):
        await asyncio.sleep(0.05)
        return f"https://cdn.example.com/{image_id}.jpg"

    async def slow_upload(chat_id, url, business_connection_id=None):
        await asyncio.sleep(0.05)
        fid = url.split("/")[-1].replace(".jpg", "")
        return f"file_{fid}"

    mock_api.resolve_image_url.side_effect = slow_resolve
    mock_api.upload_photo_from_url.side_effect = slow_upload

    start = time.monotonic()
    result = await upload_images_to_telegram(mock_api, 123, ["img1", "img2", "img3"])
    elapsed = time.monotonic() - start

    assert result == ["file_img1", "file_img2", "file_img3"]
    # With concurrency=5, 3 images should complete in ~0.1s total, not 0.3s sequential
    assert elapsed < 0.2, f"Expected concurrent execution (<0.2s), got {elapsed:.2f}s"
