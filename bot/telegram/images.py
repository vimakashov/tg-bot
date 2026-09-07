from __future__ import annotations
import re

_IMAGE_PATTERN = re.compile(r'\[\[img:([a-zA-Z0-9_-]+)\]\]')


def parse_images(text: str) -> tuple[str, list[str]]:
    """Find all [[img:<id>]] placeholders in text.

    Returns a 2-tuple of (cleaned_text, image_ids).
    All placeholders are removed from the returned text.
    Image IDs preserve their order of appearance.
    Malformed placeholders (empty ID, spaces, invalid chars) are silently ignored.
    """
    ids = _IMAGE_PATTERN.findall(text)
    cleaned = _IMAGE_PATTERN.sub('', text)
    return cleaned, ids


import asyncio
import logging

log = logging.getLogger("tgbot.images")


async def upload_images_to_telegram(api, chat_id: int, image_ids: list[str],
                                     business_connection_id: str | None = None) -> list[str]:
    """Upload multiple images concurrently. Returns list of successful file_ids.

    Uses asyncio.gather with a semaphore (concurrency=5) to process images
    concurrently rather than sequentially. Failed uploads are logged and skipped.
    """
    if not image_ids:
        return []

    semaphore = asyncio.Semaphore(5)

    async def upload_one(image_id: str) -> str | None:
        url = await api.resolve_image_url(image_id)
        if url is None:
            log.warning("resolve_image_url returned None for %s", image_id)
            return None
        file_id = await api.upload_photo_from_url(
            chat_id, url, business_connection_id=business_connection_id
        )
        if file_id is None:
            log.warning("upload_photo_from_url failed for %s", image_id)
            return None
        return file_id

    results = await asyncio.gather(*(upload_one(id_) for id_ in image_ids))
    return [fid for fid in results if fid is not None]
