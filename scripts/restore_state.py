#!/usr/bin/env python3
"""Restore watched/favorite state from a snapshot file.

Runs directly against the SQLite database; stop the service first:

    systemctl stop m3u-library
    python3 scripts/restore_state.py [snapshot-file]
    systemctl start m3u-library

Defaults to the latest snapshot in $DATA_DIR/state-snapshots/.
Only the state columns (is_watched, is_favorite, watched_at) are written;
content rows (stream URLs, titles, ...) are never touched.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "/var/lib/apps/m3u-library"))
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "app.db"))
SNAPSHOT_VERSION = 1


def main() -> int:
    snap_dir = DATA_DIR / "state-snapshots"
    snap_arg = sys.argv[1] if len(sys.argv) > 1 else "latest.json"
    snap_path = snap_dir / Path(snap_arg).name
    if not snap_path.exists():
        print(f"Snapshot not found: {snap_path}", file=sys.stderr)
        return 1

    payload = json.loads(snap_path.read_text(encoding="utf-8"))
    if payload.get("version") != SNAPSHOT_VERSION:
        print(f"Unsupported snapshot version: {payload.get('version')}", file=sys.stderr)
        return 1
    items: dict[str, dict] = payload.get("items") or {}
    series: dict[str, dict] = payload.get("series_groups") or {}

    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    try:
        item_rows = [
            (int(st.get("w") or 0), int(st.get("f") or 0), st.get("at"), item_id)
            for item_id, st in items.items()
        ]
        cursor = conn.executemany(
            "UPDATE items SET is_watched = ?, is_favorite = ?, watched_at = ? WHERE id = ?",
            item_rows,
        )
        items_updated = cursor.rowcount if cursor.rowcount is not None else -1
        series_rows = [
            (int(st.get("w") or 0), int(st.get("f") or 0), st.get("at"), gid)
            for gid, st in series.items()
        ]
        cursor = conn.executemany(
            "UPDATE series_groups SET is_watched = ?, is_favorite = ?, watched_at = ? WHERE id = ?",
            series_rows,
        )
        series_updated = cursor.rowcount if cursor.rowcount is not None else -1
        conn.commit()
    finally:
        conn.close()

    print(f"Restored from {snap_path}")
    print(f"  items: {items_updated} updated, {len(item_rows) - max(items_updated, 0)} missing")
    print(f"  series groups: {series_updated} updated, {len(series_rows) - max(series_updated, 0)} missing")
    print("Start the service; it recomputes series stats on the next refresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
