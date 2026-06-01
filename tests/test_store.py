import time
import pytest
from bot.memory.store import MemoryStore


@pytest.fixture
async def store(tmp_path):
    s = MemoryStore(str(tmp_path / "m.db"))
    await s.init()
    yield s
    await s.close()


async def test_append_and_get_history_in_order(store):
    await store.append(1, 100, "user", "hello")
    await store.append(1, 100, "assistant", "hi there")
    await store.append(1, 100, "user", "how are you")
    hist = await store.get_history(1, 100, limit=10)
    assert hist == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
        {"role": "user", "content": "how are you"},
    ]


async def test_history_is_scoped_per_user_and_chat(store):
    await store.append(1, 100, "user", "a")
    await store.append(1, 200, "user", "b")
    await store.append(2, 100, "user", "c")
    assert await store.get_history(1, 100, 10) == [{"role": "user", "content": "a"}]
    assert await store.get_history(1, 200, 10) == [{"role": "user", "content": "b"}]


async def test_get_history_returns_last_n(store):
    for i in range(5):
        await store.append(1, 100, "user", f"m{i}")
    hist = await store.get_history(1, 100, limit=2)
    assert hist == [{"role": "user", "content": "m3"}, {"role": "user", "content": "m4"}]


async def test_prune_removes_expired(store):
    old = time.time() - 10_000
    await store.append(1, 100, "user", "old", created_at=old)
    await store.append(1, 100, "user", "new")
    await store.prune(ttl_seconds=5000)
    hist = await store.get_history(1, 100, 10)
    assert hist == [{"role": "user", "content": "new"}]


async def test_clear_removes_only_caller_scope(store):
    await store.append(1, 100, "user", "a")
    await store.append(1, 200, "user", "b")   # same chat, other user
    await store.append(2, 100, "user", "c")   # other chat, same user
    await store.clear(1, 100)
    assert await store.get_history(1, 100, 10) == []
    assert await store.get_history(1, 200, 10) == [{"role": "user", "content": "b"}]
    assert await store.get_history(2, 100, 10) == [{"role": "user", "content": "c"}]
