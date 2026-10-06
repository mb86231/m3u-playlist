from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Callable

MigrationFn = Callable[[sqlite3.Connection], None]

# Current canonical schema.  CREATE ... IF NOT EXISTS makes migration 1
# idempotent, so it can be safely re-applied to older databases that are
# missing some columns or indexes.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
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
CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind);
CREATE INDEX IF NOT EXISTS idx_items_available ON items(available);
CREATE INDEX IF NOT EXISTS idx_items_title ON items(title);

CREATE TABLE IF NOT EXISTS metadata (
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

CREATE TABLE IF NOT EXISTS app_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metadata_attempts (
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  last_attempted_at TEXT NOT NULL,
  last_error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS series_groups (
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
CREATE INDEX IF NOT EXISTS idx_series_title ON series_groups(title);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations (
          version INTEGER PRIMARY KEY,
          name TEXT NOT NULL,
          applied_at TEXT NOT NULL
        )
        """
    )


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM migrations").fetchone()
    return row[0] if row and row[0] is not None else 0


def _migration_01_initial_schema(conn: sqlite3.Connection) -> None:
    """Create the canonical schema and additive columns/indexes."""
    conn.executescript(_SCHEMA)

    # Back-fill columns that were added incrementally in older deployments.
    item_columns = {row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
    for column, dtype in (
        ("is_favorite", "INTEGER NOT NULL DEFAULT 0"),
        ("is_watched", "INTEGER NOT NULL DEFAULT 0"),
        ("watched_at", "TEXT"),
        ("series_id", "TEXT"),
        ("series_title", "TEXT"),
        ("season_number", "INTEGER"),
        ("episode_number", "INTEGER"),
        ("episode_label", "TEXT"),
    ):
        if column not in item_columns:
            conn.execute(f"ALTER TABLE items ADD COLUMN {column} {dtype}")

    series_columns = {row[1] for row in conn.execute("PRAGMA table_info(series_groups)").fetchall()}
    for column, dtype in (
        ("watched_at", "TEXT"),
        ("episode_count", "INTEGER"),
        ("season_count", "INTEGER"),
        ("watched_episode_count", "INTEGER"),
        ("latest_added_at", "TEXT"),
        ("group_name", "TEXT"),
    ):
        if column not in series_columns:
            conn.execute(f"ALTER TABLE series_groups ADD COLUMN {column} {dtype}")

    # Additional indexes added after the initial schema.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_favorite ON items(is_favorite)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_watched ON items(is_watched)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_series_id ON items(series_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_series_available ON items(series_id, available)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_items_available_kind ON items(available, kind)")


_MIGRATIONS: list[tuple[int, str, MigrationFn]] = [
    (1, "initial schema", _migration_01_initial_schema),
]


_METADATA_COLUMNS = (
    "item_id", "provider", "media_type", "provider_id", "query", "title",
    "release_date", "rating", "votes", "description", "poster_url",
    "provider_url", "cached_at",
)


def _metadata_fk_target(conn: sqlite3.Connection) -> str | None:
    """Return the table the metadata FK points to, or None if there is no FK."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'metadata'"
    ).fetchone()
    if not row or not row[0]:
        return None
    match = re.search(r'REFERENCES\s+"?([A-Za-z_]\w*)"', row[0], re.IGNORECASE)
    return match.group(1) if match else None


def _migration_02_fix_metadata_foreign_key(conn: sqlite3.Connection) -> None:
    """Repair the metadata FK left pointing at items_old.

    The one-off stable-ids migration renamed items to items_old and rebuilt
    metadata from the renamed table, so the new metadata table ended up with
    ``REFERENCES items_old(id)``. items_old was then dropped, which makes
    every metadata INSERT/UPDATE fail with ``no such table: main.items_old``
    as soon as PRAGMA foreign_keys is enabled. Rebuild the table with the
    canonical FK; rows whose item_id no longer exists are dropped.
    """
    target = _metadata_fk_target(conn)
    if target is None:
        conn.executescript(_SCHEMA)
        return
    if target == "items":
        return

    conn.execute("DROP TABLE IF EXISTS metadata_broken_fk")
    conn.execute("ALTER TABLE metadata RENAME TO metadata_broken_fk")
    conn.execute(
        """
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
        )
        """
    )
    columns = ", ".join(_METADATA_COLUMNS)
    orphans = conn.execute(
        """
        SELECT COUNT(*) FROM metadata_broken_fk AS b
        WHERE NOT EXISTS (SELECT 1 FROM items AS i WHERE i.id = b.item_id)
        """
    ).fetchone()[0]
    conn.execute(
        f"""
        INSERT INTO metadata({columns})
        SELECT {columns} FROM metadata_broken_fk AS b
        WHERE EXISTS (SELECT 1 FROM items AS i WHERE i.id = b.item_id)
        """
    )
    conn.execute("DROP TABLE metadata_broken_fk")
    if orphans:
        print(f"dropped {orphans} metadata rows with missing items during FK repair")


_MIGRATIONS: list[tuple[int, str, MigrationFn]] = [
    (1, "initial schema", _migration_01_initial_schema),
    (2, "fix metadata foreign key target", _migration_02_fix_metadata_foreign_key),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """Run all pending migrations and record them in the migrations table."""
    _ensure_migrations_table(conn)
    current = _current_version(conn)
    for version, name, fn in _MIGRATIONS:
        if version <= current:
            continue
        fn(conn)
        conn.execute(
            "INSERT INTO migrations(version, name, applied_at) VALUES(?, ?, ?)",
            (version, name, _now_iso()),
        )
        conn.commit()
