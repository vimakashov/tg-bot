from __future__ import annotations
import time
from typing import AsyncIterator, Awaitable, Callable


async def stream_with_throttle(
    chunks: AsyncIterator[str],
    on_update: Callable[[str], Awaitable[None]],
    min_interval: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Consume `chunks`, calling `on_update(accumulated_text)` at most once per
    `min_interval` seconds (the first chunk always emits). Returns the full text.
    on_update errors are swallowed so a failed draft never aborts generation."""
    buffer = ""
    last_emit: float | None = None
    async for chunk in chunks:
        buffer += chunk
        now = clock()
        if last_emit is None or (now - last_emit) >= min_interval:
            try:
                await on_update(buffer)
            except Exception:
                pass
            last_emit = now
    return buffer
