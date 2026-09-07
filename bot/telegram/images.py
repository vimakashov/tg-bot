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


async def resolve_image_urls(image_ids: list[str], image_base_url: str | None = None,
                              http_client: httpx.AsyncClient | None = None) -> list[str]:
    """Resolve image IDs to thumbnail URLs.

    Returns list of successful URL strings in the same order as input IDs.
    Failed resolutions are logged and skipped.
    """
    if not image_ids:
        return []

    semaphore = asyncio.Semaphore(5)

    async def resolve_one(image_id: str) -> str | None:
        url = await resolve_image_url(image_base_url, image_id, http_client=http_client)
        if url is None:
            log.warning("resolve_image_url returned None for %s", image_id)
            return None
        return url

    results = await asyncio.gather(*(resolve_one(id_) for id_ in image_ids))
    return [url for url in results if url is not None]
