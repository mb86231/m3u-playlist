import sqlite3
import tempfile
from pathlib import Path

from m3u_library import migrations


def test_run_migrations_creates_schema_and_records_version():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "app.db"
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        migrations.run_migrations(conn)

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "items" in tables
        assert "metadata" in tables
        assert "app_state" in tables
        assert "metadata_attempts" in tables
        assert "series_groups" in tables
        assert "migrations" in tables

        version = conn.execute("SELECT MAX(version) FROM migrations").fetchone()[0]
        assert version == 2

        # Re-running on an already-migrated DB should be a no-op.
        migrations.run_migrations(conn)
        version2 = conn.execute("SELECT MAX(version) FROM migrations").fetchone()[0]
        assert version2 == 2

        conn.close()


def test_run_migrations_adds_missing_columns():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "app.db"
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        # Create an old-style items table missing additive columns.
        conn.execute(
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
              available INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE series_groups (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              query TEXT NOT NULL
            )
            """
        )

        migrations.run_migrations(conn)

        item_columns = {row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
        assert "is_favorite" in item_columns
        assert "is_watched" in item_columns
        assert "series_id" in item_columns

        series_columns = {row[1] for row in conn.execute("PRAGMA table_info(series_groups)").fetchall()}
        assert "episode_count" in series_columns
        assert "group_name" in series_columns

        version = conn.execute("SELECT MAX(version) FROM migrations").fetchone()[0]
        assert version == 2

        conn.close()
