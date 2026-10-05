import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


def _create_old_db(path: Path):
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
          item_id TEXT PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
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
        CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE series_groups (
          id TEXT PRIMARY KEY,
          title TEXT NOT NULL,
          query TEXT NOT NULL,
          release_date TEXT,
          rating REAL,
          description TEXT,
          poster_url TEXT,
          provider_url TEXT,
          cached_at TEXT,
          is_favorite INTEGER NOT NULL DEFAULT 0,
          is_watched INTEGER NOT NULL DEFAULT 0,
          watched_at TEXT,
          episode_count INTEGER,
          season_count INTEGER,
          watched_episode_count INTEGER,
          latest_added_at TEXT,
          group_name TEXT
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO items(id, title, group_name, kind, logo, stream_url, added_at, first_seen_at, last_seen_at,
                          available, is_favorite, is_watched, watched_at)
        VALUES(?, ?, 'Movies', 'movie', '', ?, '2024-01-01T00:00:00', '2024-01-01T00:00:00', '2024-01-02T00:00:00',
               ?, 0, ?, ?)
        """,
        [
            ("old1", "Test Movie", "http://old1.example.com/movie.mp4", 0, 1, "2024-01-01T00:00:00"),
            ("old2", "Test Movie", "http://old2.example.com/movie.mp4", 1, 0, None),
        ],
    )
    conn.executemany(
        "INSERT INTO metadata(item_id, provider, media_type, provider_id, query, title, cached_at, poster_url, description) VALUES(?, 'tmdb', 'movie', '', '', 'Test Movie', ?, ?, ?)",
        [
            ("old1", "2024-01-01T00:00:00", "", ""),
            ("old2", "2024-01-02T00:00:00", "http://poster.jpg", "A movie"),
        ],
    )
    conn.execute("INSERT INTO series_groups(id, title, query) VALUES('series1', 'Test Movie', 'Test Movie')")
    conn.commit()
    conn.close()


@pytest.fixture
def tmp_env(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "app.db"
        monkeypatch.setenv("DATA_DIR", tmpdir)
        monkeypatch.setenv("DATABASE_PATH", str(db_path))
        _create_old_db(db_path)
        yield db_path


def test_migration_merges_collisions_and_preserves_watched(tmp_env):
    db_path = tmp_env
    # Import after env vars are patched.
    from scripts.migrate_to_stable_ids import main as migrate_main

    assert migrate_main() == 0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM items").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["is_watched"] == 1
    assert row["is_favorite"] == 0
    assert row["available"] == 1
    assert "old2" in row["stream_url"]

    meta = conn.execute("SELECT * FROM metadata").fetchone()
    assert meta["poster_url"] == "http://poster.jpg"
    assert meta["description"] == "A movie"

    sg = conn.execute("SELECT * FROM series_groups WHERE id = 'series1'").fetchone()
    assert sg["episode_count"] == 0
