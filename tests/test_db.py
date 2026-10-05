import asyncio
import tempfile
from pathlib import Path

import pytest

from m3u_library.db import Database


@pytest.fixture
def tmp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.db"
        db = Database(path)
        yield db


@pytest.mark.asyncio
async def test_writer_serializes_concurrent_writes(tmp_db):
    db = tmp_db
    await db.init()
    await db.start()

    async def create_table(conn):
        await conn.execute("CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER)")
        await conn.execute("INSERT OR REPLACE INTO counters VALUES ('x', COALESCE((SELECT value FROM counters WHERE name='x'), 0) + 1)")

    await asyncio.gather(*[db.write(create_table) for _ in range(20)])

    async with db.read() as conn:
        row = await (await conn.execute("SELECT value FROM counters WHERE name='x'")).fetchone()
        assert row[0] == 20

    await db.stop()


@pytest.mark.asyncio
async def test_read_does_not_block_write_queue(tmp_db):
    db = tmp_db
    await db.init()
    await db.start()

    # Pre-create table so concurrent reads don't fail before first write lands.
    async def init_schema(conn):
        await conn.execute("CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER)")

    await db.write(init_schema)

    async def slow_write(conn):
        await conn.execute("INSERT INTO counters VALUES ('y', 1) ON CONFLICT(name) DO UPDATE SET value=value+1")
        await asyncio.sleep(0.1)

    write_futures = [asyncio.create_task(db.write(slow_write)) for _ in range(5)]
    read_tasks = [asyncio.create_task(_read_count(db)) for _ in range(5)]
    await asyncio.gather(*write_futures, *read_tasks)
    await db.stop()


async def _read_count(db: Database) -> int:
    async with db.read() as conn:
        row = await (await conn.execute("SELECT value FROM counters WHERE name='y'")).fetchone()
        return row[0] if row else 0
