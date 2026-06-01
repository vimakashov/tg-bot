from __future__ import annotations
import time
import aiosqlite


class MemoryStore:
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_scope ON messages (chat_id, user_id, id)"
        )
        await self._db.commit()

    async def append(self, chat_id: int, user_id: int, role: str, content: str,
                     created_at: float | None = None) -> None:
        ts = time.time() if created_at is None else created_at
        await self._db.execute(
            "INSERT INTO messages (chat_id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, user_id, role, content, ts),
        )
        await self._db.commit()

    async def get_history(self, chat_id: int, user_id: int, limit: int) -> list[dict]:
        cur = await self._db.execute(
            "SELECT role, content FROM messages WHERE chat_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, user_id, limit),
        )
        rows = await cur.fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    async def prune(self, ttl_seconds: int) -> None:
        cutoff = time.time() - ttl_seconds
        await self._db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
