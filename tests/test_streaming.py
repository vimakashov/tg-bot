from bot.streaming import stream_with_throttle


async def _agen(items):
    for i in items:
        yield i


async def test_returns_full_concatenated_text():
    full = await stream_with_throttle(_agen(["a", "b", "c"]), on_update=lambda _t: _noop(),
                                      min_interval=0.0, clock=_fake_clock([0, 0, 0]))
    assert full == "abc"


async def _noop():
    return None


def _fake_clock(times):
    seq = iter(times)
    return lambda: next(seq)


async def test_throttles_updates_by_interval():
    calls = []

    async def on_update(text):
        calls.append(text)

    # clock returns one value per chunk; interval=1.0
    # times: chunk1 t=0 (first -> emit), chunk2 t=0.5 (skip), chunk3 t=1.0 (emit)
    full = await stream_with_throttle(
        _agen(["a", "b", "c"]), on_update=on_update,
        min_interval=1.0, clock=_fake_clock([0.0, 0.5, 1.0]),
    )
    assert full == "abc"
    assert calls == ["a", "abc"]  # accumulated text at each emit point


async def test_first_chunk_always_emits():
    calls = []

    async def on_update(text):
        calls.append(text)

    full = await stream_with_throttle(
        _agen(["x"]), on_update=on_update, min_interval=999.0, clock=_fake_clock([0.0]),
    )
    assert full == "x"
    assert calls == ["x"]
