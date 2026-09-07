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
