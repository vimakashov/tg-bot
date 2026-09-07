# Image Support Design Specification

**Date:** 2026-09-07
**Status:** Draft
**Mode:** Guest + Secretary (Business)

## Overview

Add support for displaying images in bot responses. When the LLM includes `[[img:<id>]]` placeholders in its response text, the bot parses them, resolves image URLs from a JSON endpoint, downloads the images, and sends them as separate Telegram photo messages after the text reply.

### User Request

- Model outputs: `"@Вот как выглядит Эйфелева башня:\n\n[[img:f4ec367b03bf]]"`
- `f4ec367b03bf` — image ID
- Image URL obtained from: `IMAGE_BASE_URL/<id>.json` → parse `thumbnail` key
- `[[img:...]]` placeholders must NOT appear in displayed text

## Architecture

### New Module: `bot/telegram/images.py`

Single responsibility module for image parsing and upload orchestration. Two public functions (resolution and photo upload live in `api.py`):

#### 1. `parse_images(text: str) -> tuple[str, list[str]]`

Finds all `[[img:<id>]]` patterns in text using the regex pattern `r'\[\[img:([a-zA-Z0-9_-]+)\]\]'`. Returns:
- Cleaned text with all placeholders removed
- List of extracted image IDs (preserving order)

Edge cases:
- No placeholders → returns `(text, [])`
- Multiple placeholders → returns all IDs in order
- Malformed `[[img:]]` (no ID) → ignored by regex
- `[[img: ]]` (space in ID) → ignored by regex (`[a-zA-Z0-9_-]+` requires at least one valid char)

#### 2. `upload_images_to_telegram(api: TelegramApi, chat_id: int, image_ids: list[str], business_connection_id: str | None = None) -> list[str]`

Orchestrates upload of multiple images by calling `api.resolve_image_url()` and `api.upload_photo_from_url()`. Uses `asyncio.gather` with a semaphore (concurrency=5) to process images concurrently rather than sequentially, avoiding excessive latency for responses with many images.

For each image ID:
1. Call `api.resolve_image_url(image_id)` → if `None`, log warning and skip
2. Call `api.upload_photo_from_url(chat_id, url, business_connection_id=business_connection_id)` → if `None`, log warning and skip
3. Collect successful `file_id` values

Returns list of Telegram `file_id` strings for successfully uploaded photos. Failed uploads are silently skipped (logged as warnings). Concurrency is bounded by a semaphore (`asyncio.Semaphore(5)`) to avoid hitting Telegram flood control limits.

### Modified Files

#### `bot/config.py`

Add new config field and env var loading:
```python
# In Config dataclass fields:
image_base_url: str = ""  # env var IMAGE_BASE_URL, empty means no image support

# In Config.from_env():
image_base_url=env.get("IMAGE_BASE_URL", ""),
```

#### `bot/telegram/api.py`

Add three new methods to `TelegramApi`:

1. `async resolve_image_url(image_id: str) -> str | None`
   - GET `{self._config.image_base_url}/{image_id}.json` via httpx with 10s timeout
   - Parse JSON response, return `thumbnail` value or `None` if request fails, response is not valid JSON, or key is missing/empty

2. `async upload_photo_from_url(chat_id: int, url: str, business_connection_id: str | None = None) -> str | None`
   - Download image bytes via httpx GET with 30s timeout
   - Call `self.call("sendPhoto", chat_id=chat_id, photo=httpx.ContentFile(bytes_data), business_connection_id=business_connection_id)` (passing `business_connection_id` only if not `None`)
   - Return `file_id` from response's `result` dict or `None` on any failure

3. `async send_photo(chat_id: int, file_id: str, business_connection_id: str | None = None) -> bool`
   - Convenience wrapper: calls `self.call("sendPhoto", chat_id=chat_id, photo=file_id, business_connection_id=business_connection_id)`
   - Returns `True` if API returns `ok:true`, `False` otherwise

#### `bot/telegram/guest.py`

In `stream_guest_reply()`:
1. After accumulating full text from Groq stream:
2. Call `parse_images(full_text) → (clean_text, image_ids)`
3. Send `clean_text` via `answer_guest_query(rich=True)` (existing behavior)
4. If `image_ids` is non-empty:
   - Call `upload_images_to_telegram(api, chat_id, image_ids)` (no business_connection_id in guest mode)
   - The function handles concurrent resolve + upload for all IDs

#### `bot/telegram/business.py`

In `handle_business_message()`:
1. After accumulating full text from Groq stream:
2. Call `parse_images(full_text) → (clean_text, image_ids)`
3. Send `clean_text` via `send_rich_business_message()` (existing behavior)
4. If `image_ids` is non-empty:
   - Call `upload_images_to_telegram(api, chat_id, image_ids, business_connection_id=connection.connection_id)`

### Error Handling

- **Parse failures:** `parse_images` never raises; malformed placeholders are silently ignored by regex
- **Resolve failures:** `resolve_image_url` returns `None`; the calling function logs a warning and skips that image
- **Upload failures:** `upload_photo_from_url` catches all exceptions, logs them, returns `None`; failed images are skipped
- **Text send failure:** existing fallback behavior unchanged (plain text fallback for rich messages)
- **Partial uploads:** if some images fail but others succeed, the successful ones are still sent
- **Business mode partial state:** if text is sent but image upload fails in secretary mode, no notification is sent — silent skip is consistent with business mode's existing "stay silent on AI failure" policy

### Testing

New test file: `tests/test_images.py`

Test cases:
- `test_parse_images_no_placeholders` — returns (text, [])
- `test_parse_images_single_placeholder` — extracts one ID, cleans text
- `test_parse_images_multiple_placeholders` — extracts all IDs in order
- `test_parse_images_malformed_placeholder` — ignores `[[img:]]`, `[[img: ]]`, `[[img:a b]]`
- `test_parse_images_placeholder_at_boundaries` — start, middle, end of text
- `test_parse_images_regex_valid_chars` — IDs with hyphens, underscores accepted; spaces rejected
- `test_resolve_image_url_success` — mock HTTP 200 with valid JSON containing thumbnail
- `test_resolve_image_url_http_failure` — returns None on non-200
- `test_resolve_image_url_missing_thumbnail` — returns None when key absent
- `test_upload_photo_from_url_success` — mock download + sendPhoto call
- `test_upload_photo_from_url_download_failure` — returns None on httpx exception
- `test_upload_images_to_telegram_partial_failure` — some succeed, some fail, only successes returned
- `test_upload_images_to_telegram_empty_list` — returns [] immediately

Integration tests in existing files:
- `tests/test_guest.py` — test that guest response with images sends text then triggers upload
- `tests/test_business.py` — test that business response with images sends text then triggers upload with business_connection_id

### Dependencies

No new Python dependencies required. Uses existing httpx for HTTP requests and asyncio primitives (Semaphore, gather) from the standard library.

## Data Flow

```
Groq stream → full_text → parse_images() → (clean_text, image_ids)
    │
    ├─→ send clean_text via answerGuestQuery / sendRichMessage
    │
    └─→ for each image_id (concurrent via asyncio.gather):
            api.resolve_image_url(id) → thumbnail_url
                ↓ (if None, skip + log)
            api.upload_photo_from_url(chat_id, url) → file_id
                ↓ (if None, skip + log)
            photo message sent to chat
```

## YAGNI — Out of Scope

- Image caching / deduplication (same ID sent twice = uploaded twice)
- Image size validation before upload (Telegram has 10 MB limit; failures handled gracefully at API level)
- Animated GIFs / video support
- Inline keyboard buttons with images
- Retry logic for failed uploads
- Configurable max images per response (env var `MAX_IMAGES_PER_RESPONSE`)
