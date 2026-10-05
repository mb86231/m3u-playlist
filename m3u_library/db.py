from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

import aiosqlite

from m3u_library import migrations


APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/lib/apps/m3u-library"))
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "app.db"))

T = TypeVar("T")


def _sync_init(path: Path) -> None:
    """Run schema migrations through a synchronous sqlite3 connection."""
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    migrations.run_migrations(conn)
    conn.commit()
    conn.close()


class _WriteJob:
    __slots__ = ("fn", "future")

    def __init__(self, fn: Callable[[aiosqlite.Connection], Awaitable[Any]], future: asyncio.Future[Any]) -> None:
        self.fn = fn
        self.future = future


class _StopJob:
    pass


_STOP_JOB = _StopJob()


class Database:
    """Async single-writer SQLite layer backed by aiosqlite.

    Writes are serialised through a dedicated asyncio task that owns one
    connection. Reads use independent short-lived connections so WAL mode can
    keep them concurrent with writes.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._write_queue: asyncio.Queue[_WriteJob | _StopJob] = asyncio.Queue()
        self._writer_task: asyncio.Task[None] | None = None
        self._initialized_path: Path | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        # The queue is bound to the loop that created it; recreate it if the
        # event loop has changed (e.g. across TestClient instances in tests).
        try:
            queue_loop = self._write_queue._loop  # type: ignore[attr-defined]
        except AttributeError:
            queue_loop = None
        if queue_loop is not loop:
            self._write_queue = asyncio.Queue()
        if self._writer_task is not None:
            if self._writer_task.done():
                self._writer_task = None
            elif self._writer_task.get_loop() is not loop:
                self._writer_task = None
        if self._writer_task is None:
            self._writer_task = asyncio.create_task(self._writer_loop(), name="sqlite-writer")

    async def stop(self) -> None:
        if self._writer_task is not None and not self._writer_task.done():
            await self._write_queue.put(_STOP_JOB)
            await self._writer_task
            self._writer_task = None

    async def _writer_loop(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path, timeout=30.0) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA busy_timeout=10000")
            while True:
                job = await self._write_queue.get()
                if isinstance(job, _StopJob):
                    break
                try:
                    result = await job.fn(conn)
                    await conn.commit()
                    job.future.set_result(result)
                except Exception as exc:
                    try:
                        await conn.rollback()
                    except Exception:
                        pass
                    job.future.set_exception(exc)

    @asynccontextmanager
    async def read(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path, timeout=10.0) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA busy_timeout=5000")
            yield conn

    async def write(self, fn: Callable[[aiosqlite.Connection], Awaitable[T]]) -> T:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        await self._write_queue.put(_WriteJob(fn, future))
        return await future

    async def init(self) -> None:
        """Create the schema if it does not already exist."""
        if self._initialized_path == self.path:
            return
        # If the path has changed (e.g. in tests), discard the old writer so the
        # next start() opens the new database file.  Only await the old writer if
        # it belongs to the current event loop; otherwise it will be cancelled
        # when its loop is torn down.
        if self._writer_task is not None:
            if self._writer_task.get_loop() is asyncio.get_running_loop():
                await self.stop()
            else:
                self._writer_task = None
        self._initialized_path = self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_sync_init, self.path)


# Module-level singleton used by the application.
db = Database(DB_PATH)


async def init_db() -> None:
    await db.init()


@asynccontextmanager
async def read_db():
    async with db.read() as conn:
        yield conn


async def write_db(fn: Callable[[aiosqlite.Connection], Awaitable[T]]) -> T:
    return await db.write(fn)


async def get_state(conn: aiosqlite.Connection, key: str, default: Any = None) -> Any:
    cursor = await conn.execute("SELECT value FROM app_state WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return json.loads(row[0]) if row else default


async def set_state(conn: aiosqlite.Connection, key: str, value: Any) -> None:
    await conn.execute(
        "INSERT INTO app_state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )
