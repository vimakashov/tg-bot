from __future__ import annotations
import asyncio
import httpx
import logging
import re

log = logging.getLogger("tgbot.images")

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


async def resolve_image_url(image_base_url: str | None, image_id: str,
                             http_client: httpx.AsyncClient | None = None) -> str | None:
    """Resolve an image URL from a JSON endpoint.

    GET {image_base_url}/{image_id}.json — returns the 'thumbnail' value
    or None on any failure (HTTP error, invalid JSON, missing key).
    """
    if not image_base_url:
        return None
    url = f"{image_base_url}/{image_id}.json"
    try:
        if http_client is not None:
            resp = await http_client.get(url)
        else:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
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


async def upload_images_to_telegram(api, chat_id: int, image_ids: list[str],
                                      business_connection_id: str | None = None,
                                      image_base_url: str | None = None,
                                      http_client: httpx.AsyncClient | None = None) -> list[str]:
    """Resolve image URLs and send them as separate text messages.

    For each image ID, resolves the thumbnail URL via the JSON endpoint,
    then sends it as a plain text message (not a photo upload).
    Failed resolutions are logged and skipped.
    """
    if not image_ids:
        return []

    semaphore = asyncio.Semaphore(5)

    async def send_one(image_id: str) -> bool:
        url = await resolve_image_url(image_base_url, image_id, http_client=http_client)
        if url is None:
            log.warning("resolve_image_url returned None for %s", image_id)
            return False
        try:
            kwargs = {"chat_id": chat_id, "text": url}
            if business_connection_id is not None:
                kwargs["business_connection_id"] = business_connection_id
            await api.call("sendMessage", **kwargs)
            log.info("Sent image URL for %s to chat %s", image_id, chat_id)
            return True
        except Exception:
            log.warning("sendMessage failed for image %s", image_id)
            return False

    results = await asyncio.gather(*(send_one(id_) for id_ in image_ids))
    return [image_ids[i] for i, ok in enumerate(results) if ok]
