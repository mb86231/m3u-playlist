#!/usr/bin/env python3
"""One-off migration from URL-derived item IDs to stable IDs.

Run with the service stopped and a verified backup.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/lib/apps/m3u-library"))
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "app.db"))


def stable_id(row: sqlite3.Row) -> str:
    """Compute the new stable ID for a row from the old items table."""
    kind: str = row["kind"]
    title: str = row["title"]
    stream_url: str = row["stream_url"]
    if kind == "series" and row["series_id"]:
        key = f"series\n{row['series_id']}\n{row['season_number']}\n{row['episode_number']}"
    elif kind == "movie":
        key = f"movie\n{title.strip().lower()}"
    else:
        key = f"{title}\n{stream_url}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _better_metadata(a: sqlite3.Row, b: sqlite3.Row) -> bool:
    """Return True if metadata row a should be preferred over row b."""
    a_poster = a["poster_url"] if a["poster_url"] else ""
    a_desc = a["description"] if a["description"] else ""
    b_poster = b["poster_url"] if b["poster_url"] else ""
    b_desc = b["description"] if b["description"] else ""
    a_score = (a["cached_at"] or "", bool(a_poster), bool(a_desc))
    b_score = (b["cached_at"] or "", bool(b_poster), bool(b_desc))
    return a_score > b_score


def _merge_rows(rows: list[sqlite3.Row]) -> dict[str, Any]:
    """Merge colliding old rows into a single new row."""
    # Prefer a representative that is currently available and was seen most recently.
    rows_sorted = sorted(
        rows,
        key=lambda r: (r["available"] or 0, r["last_seen_at"] or ""),
        reverse=True,
    )
    rep = rows_sorted[0]
    return {
        "id": stable_id(rep),
        "title": rep["title"],
        "group_name": rep["group_name"],
        "kind": rep["kind"],
        "logo": rep["logo"],
        "stream_url": rep["stream_url"],
        "added_at": min((r["added_at"] or "") for r in rows) or None,
        "first_seen_at": min((r["first_seen_at"] or "") for r in rows) or None,
        "last_seen_at": max((r["last_seen_at"] or "") for r in rows) or None,
        "available": max((r["available"] or 0) for r in rows),
        "is_favorite": max((r["is_favorite"] or 0) for r in rows),
        "is_watched": max((r["is_watched"] or 0) for r in rows),
        "watched_at": max((r["watched_at"] or "") for r in rows) or None,
        "series_id": rep["series_id"],
        "series_title": rep["series_title"],
        "season_number": rep["season_number"],
        "episode_number": rep["episode_number"],
        "episode_label": rep["episode_label"],
    }


def _copy_wal_and_shm(source: Path, destination: Path) -> None:
    for suffix in ("-wal", "-shm"):
        src = Path(f"{source}{suffix}")
        if src.exists():
            shutil.copy2(str(src), str(Path(f"{destination}{suffix}")))


def _create_table_like(conn: sqlite3.Connection, old_name: str, new_name: str) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (old_name,),
    ).fetchone()
    if not row or not row["sql"]:
        raise RuntimeError(f"Could not find CREATE TABLE sql for {old_name}")
    sql: str = row["sql"]
    sql = sql.replace(f"CREATE TABLE {old_name}", f"CREATE TABLE {new_name}", 1)
    # Metadata references items (now named items_old); keep the reference correct.
    sql = sql.replace(old_name, new_name)
    # After the renames the copied schema can still reference the renamed-away
    # sibling tables (e.g. metadata's FK ends up as REFERENCES "items_old").
    sql = sql.replace("items_old", "items").replace("metadata_old", "metadata")
    conn.execute(sql)


def main() -> int:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        return 1

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = Path(f"{DB_PATH}.pre-stable-ids-{timestamp}")

    print(f"Backing up {DB_PATH} -> {backup_path}")
    shutil.copy2(str(DB_PATH), str(backup_path))
    _copy_wal_and_shm(DB_PATH, backup_path)

    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")

    items = conn.execute("SELECT * FROM items").fetchall()
    old_item_count = len(items)

    old_to_new: dict[str, str] = {}
    merge_groups: dict[str, list[sqlite3.Row]] = {}
    for row in items:
        new_id = stable_id(row)
        old_to_new[row["id"]] = new_id
        merge_groups.setdefault(new_id, []).append(row)

    merged_rows = [_merge_rows(group) for group in merge_groups.values()]
    collisions = sum(max(0, len(group) - 1) for group in merge_groups.values())

    metadata_rows = conn.execute("SELECT * FROM metadata").fetchall()
    old_meta_count = len(metadata_rows)
    chosen_meta: dict[str, sqlite3.Row] = {}
    for row in metadata_rows:
        new_id = old_to_new.get(row["item_id"])
        if not new_id:
            continue
        existing = chosen_meta.get(new_id)
        if existing is None or _better_metadata(row, existing):
            chosen_meta[new_id] = row

    # Move old tables aside so the new tables can keep the canonical names.
    # Clean up any leftover temporary tables from a previous aborted run first.
    conn.execute("DROP TABLE IF EXISTS items_old")
    conn.execute("DROP TABLE IF EXISTS metadata_old")
    conn.execute("ALTER TABLE items RENAME TO items_old")
    conn.execute("ALTER TABLE metadata RENAME TO metadata_old")

    _create_table_like(conn, "items_old", "items")
    _create_table_like(conn, "metadata_old", "metadata")

    conn.executemany(
        """
        INSERT INTO items(
          id, title, group_name, kind, logo, stream_url, added_at, first_seen_at, last_seen_at, available,
          is_favorite, is_watched, watched_at,
          series_id, series_title, season_number, episode_number, episode_label
        ) VALUES(
          :id, :title, :group_name, :kind, :logo, :stream_url, :added_at, :first_seen_at, :last_seen_at, :available,
          :is_favorite, :is_watched, :watched_at,
          :series_id, :series_title, :season_number, :episode_number, :episode_label
        )
        """,
        merged_rows,
    )

    new_meta_rows: list[dict[str, Any]] = []
    for new_id, row in chosen_meta.items():
        new_meta_rows.append(
            {
                "item_id": new_id,
                "provider": row["provider"],
                "media_type": row["media_type"],
                "provider_id": row["provider_id"],
                "query": row["query"],
                "title": row["title"],
                "release_date": row["release_date"],
                "rating": row["rating"],
                "votes": row["votes"],
                "description": row["description"],
                "poster_url": row["poster_url"],
                "provider_url": row["provider_url"],
                "cached_at": row["cached_at"],
            }
        )
    if new_meta_rows:
        conn.executemany(
            """
            INSERT INTO metadata(
              item_id, provider, media_type, provider_id, query, title, release_date, rating, votes,
              description, poster_url, provider_url, cached_at
            ) VALUES(
              :item_id, :provider, :media_type, :provider_id, :query, :title, :release_date, :rating, :votes,
              :description, :poster_url, :provider_url, :cached_at
            )
            """,
            new_meta_rows,
        )

    # Drop the old tables (and their indexes).
    conn.execute("DROP TABLE items_old")
    conn.execute("DROP TABLE metadata_old")

    # Recreate the indexes that were dropped with the old tables.
    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_items_kind ON items(kind)",
        "CREATE INDEX IF NOT EXISTS idx_items_available ON items(available)",
        "CREATE INDEX IF NOT EXISTS idx_items_title ON items(title)",
        "CREATE INDEX IF NOT EXISTS idx_items_favorite ON items(is_favorite)",
        "CREATE INDEX IF NOT EXISTS idx_items_watched ON items(is_watched)",
        "CREATE INDEX IF NOT EXISTS idx_items_series_id ON items(series_id)",
        "CREATE INDEX IF NOT EXISTS idx_items_series_available ON items(series_id, available)",
        "CREATE INDEX IF NOT EXISTS idx_items_available_kind ON items(available, kind)",
        "CREATE INDEX IF NOT EXISTS idx_series_title ON series_groups(title)",
    ]
    for sql in index_statements:
        conn.execute(sql)

    conn.execute(
        """
        WITH agg AS (
          SELECT
            series_id,
            COUNT(*) AS episode_count,
            COUNT(DISTINCT COALESCE(season_number, 0)) AS season_count,
            COALESCE(SUM(is_watched), 0) AS watched_episode_count,
            COALESCE(MAX(added_at), '') AS latest_added_at,
            COALESCE(MAX(is_watched), 0) AS any_watched,
            COALESCE(MAX(group_name), '') AS group_name
          FROM items
          WHERE available = 1 AND series_id IS NOT NULL
          GROUP BY series_id
        )
        UPDATE series_groups
        SET
          episode_count = COALESCE((SELECT episode_count FROM agg WHERE agg.series_id = series_groups.id), 0),
          season_count = COALESCE((SELECT season_count FROM agg WHERE agg.series_id = series_groups.id), 0),
          watched_episode_count = COALESCE((SELECT watched_episode_count FROM agg WHERE agg.series_id = series_groups.id), 0),
          latest_added_at = COALESCE((SELECT latest_added_at FROM agg WHERE agg.series_id = series_groups.id), ''),
          is_watched = COALESCE((SELECT any_watched FROM agg WHERE agg.series_id = series_groups.id), 0),
          watched_at = CASE WHEN COALESCE((SELECT any_watched FROM agg WHERE agg.series_id = series_groups.id), 0) = 1 THEN ? ELSE NULL END,
          group_name = COALESCE((SELECT group_name FROM agg WHERE agg.series_id = series_groups.id), '')
        """,
        (now_iso(),),
    )

    conn.commit()
    conn.close()

    new_item_count = len(merged_rows)
    print("Migration to stable item IDs complete.")
    print(f"  Backup path: {backup_path}")
    print(f"  Items before: {old_item_count}, after: {new_item_count} (merged {collisions} collisions)")
    print(f"  Metadata before: {old_meta_count}, after dedup: {len(new_meta_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
