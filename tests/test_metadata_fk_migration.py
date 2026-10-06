"""Migration 2 repairs the metadata FK left pointing at items_old."""

import sqlite3
from pathlib import Path

from m3u_library import migrations


def _make_broken_db(path: Path) -> None:
    """Recreate the state the stable-ids migration left behind on prod."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE items (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          group_name TEXT NOT NULL DEFAULT 'Uncategorized',
          kind TEXT NOT NULL,
          logo TEXT NOT NULL DEFAULT '',
          stream_url TEXT NOT NULL,
          added_at TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          available INTEGER NOT NULL DEFAULT 1,
          is_favorite INTEGER NOT NULL DEFAULT 0,
          is_watched INTEGER NOT NULL DEFAULT 0,
          watched_at TEXT,
          series_id TEXT,
          series_title TEXT,
          season_number INTEGER,
          episode_number INTEGER,
          episode_label TEXT
        );
        CREATE TABLE metadata (
          item_id TEXT PRIMARY KEY REFERENCES "items_old"(id) ON DELETE CASCADE,
          provider TEXT NOT NULL,
          media_type TEXT NOT NULL,
          provider_id TEXT,
          query TEXT NOT NULL,
          title TEXT,
          release_date TEXT,
          rating REAL,
          votes INTEGER,
          description TEXT,
          poster_url TEXT,
          provider_url TEXT,
          cached_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO items(id, title, kind, stream_url, added_at, first_seen_at, last_seen_at) "
        "VALUES('item-1', 'Fauda', 'series', 'http://x/s1.m3u8', '2026-01-01', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO metadata(item_id, provider, media_type, query, cached_at) "
        "VALUES('item-1', 'tmdb', 'series', 'Fauda', '2026-01-02')"
    )
    # Orphan row: references an item that no longer exists.
    conn.execute(
        "INSERT INTO metadata(item_id, provider, media_type, query, cached_at) "
        "VALUES('gone-item', 'tmdb', 'movie', 'Old', '2026-01-02')"
    )
    conn.commit()
    conn.close()


def test_metadata_fk_repair(tmp_path: Path):
    db_path = tmp_path / "app.db"
    _make_broken_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrations.run_migrations(conn)

    schema = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='metadata'"
    ).fetchone()[0]
    assert 'REFERENCES items(id)' in schema.replace('"', "")
    assert "items_old" not in schema

    # Valid row kept, orphan dropped.
    rows = conn.execute("SELECT item_id FROM metadata ORDER BY item_id").fetchall()
    assert [r["item_id"] for r in rows] == ["item-1"]

    # Inserts work again with foreign keys enabled (the prod failure mode).
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO metadata(item_id, provider, media_type, query, cached_at) "
        "VALUES('item-1', 'tmdb', 'series', 'Fauda', '2026-01-03') "
        "ON CONFLICT(item_id) DO UPDATE SET cached_at=excluded.cached_at"
    )
    conn.commit()
    conn.close()


def test_metadata_fk_repair_idempotent_on_healthy_db(tmp_path: Path):
    db_path = tmp_path / "app.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrations.run_migrations(conn)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO items(id, title, kind, stream_url, added_at, first_seen_at, last_seen_at) "
        "VALUES('i1', 'T', 'movie', 'http://x/m.m3u8', '2026-01-01', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO metadata(item_id, provider, media_type, query, cached_at) "
        "VALUES('i1', 'tmdb', 'movie', 'T', '2026-01-01')"
    )
    conn.commit()

    # Second run must not touch the healthy table.
    migrations.run_migrations(conn)
    count = conn.execute("SELECT COUNT(*) FROM metadata").fetchone()[0]
    assert count == 1
    conn.close()
