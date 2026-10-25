"""Tests for the "watched - new episodes" section.

completed_at remembers when a series was fully watched; when new episodes
arrive afterwards, the series must surface in section "watched_new" (and no
longer in "continue", which is reserved for never-completed series).
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
from m3u_library import main


API_KEY = "watched-new-test-key"

SERIES_M3U = "\n".join([
    "#EXTM3U",
    '#EXTINF:-1 tvg-name="Galaxy Quest S01 E01" group-title="Series",Galaxy Quest S01 E01',
    "http://x/series/gq/1/1.mp4",
    '#EXTINF:-1 tvg-name="Galaxy Quest S01 E02" group-title="Series",Galaxy Quest S01 E02',
    "http://x/series/gq/1/2.mp4",
])

SERIES_M3U_WITH_S02 = SERIES_M3U + "\n" + "\n".join([
    '#EXTINF:-1 tvg-name="Galaxy Quest S02 E01" group-title="Series",Galaxy Quest S02 E01',
    "http://x/series/gq/2/1.mp4",
])


@pytest.fixture(scope="module")
def client():
    mp = pytest.MonkeyPatch()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        db_path = tmpdir_path / "app.db"
        mp.setenv("DATA_DIR", str(tmpdir_path))
        mp.setenv("DATABASE_PATH", str(db_path))
        mp.setenv("API_KEY", API_KEY)
        mp.setattr(db_mod, "DB_PATH", db_path)
        mp.setattr(db_mod, "DATA_DIR", tmpdir_path)
        mp.setattr(main, "DB_PATH", db_path)
        mp.setattr(main, "DATA_DIR", tmpdir_path)
        mp.setattr(main, "run_metadata_warmup", lambda last_refresh=None: None)

        async def _empty_ids(conn):
            return {"movie_ids": set(), "series_ids": set()}

        async def _empty_snapshot(conn):
            return {"items": []}

        mp.setattr(main, "async_trending_library_ids", _empty_ids)
        mp.setattr(main, "async_popular_library_ids", _empty_ids)
        mp.setattr(main, "async_get_upcoming_snapshot", _empty_snapshot)
        db_mod.db.path = db_path
        tmpdir_path.mkdir(parents=True, exist_ok=True)
        with TestClient(main.app) as c:
            yield c
    mp.undo()


def _refresh(client, tmp_path, content):
    m3u = tmp_path / "source.m3u"
    m3u.write_text(content, encoding="utf-8")
    old = os.environ.get("M3U_URL")
    os.environ["M3U_URL"] = m3u.as_uri()
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    if old is None:
        os.environ.pop("M3U_URL", None)
    else:
        os.environ["M3U_URL"] = old
    assert res.status_code == 200


def _episode_ids(client):
    """Episode item ids from the DB (/api/items returns series group ids)."""
    conn = sqlite3.connect(str(db_mod.db.path))
    try:
        rows = conn.execute(
            "SELECT id, title FROM items WHERE kind = 'series'"
        ).fetchall()
        return {title: row_id for row_id, title in rows}
    finally:
        conn.close()


def _counts(client):
    res = client.get("/api/series?limit=1")
    assert res.status_code == 200
    return res.json()["section_counts"]


def test_watched_new_section(client, tmp_path):
    _refresh(client, tmp_path, SERIES_M3U)
    ids = _episode_ids(client)

    counts = _counts(client)
    assert counts["watched_new"] == 0
    assert counts["continue"] == 0

    # Watch both episodes -> series completed.
    for title, ep_id in ids.items():
        res = client.post(f"/api/items/{ep_id}/watched", headers={"X-API-Key": API_KEY})
        assert res.status_code == 200
    counts = _counts(client)
    assert counts["watched"] == 1
    assert counts["watched_new"] == 0
    assert counts["continue"] == 0

    # New season arrives -> completed series shows in watched_new, not continue.
    _refresh(client, tmp_path, SERIES_M3U_WITH_S02)
    counts = _counts(client)
    assert counts["watched_new"] == 1
    assert counts["continue"] == 0

    res = client.get("/api/series", params={"section": "watched_new"})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] == 1
    assert data["items"][0]["title"].startswith("Galaxy Quest")

    res = client.get("/api/items", params={"section": "watched_new", "kind": "series"})
    assert res.status_code == 200
    assert res.json()["matched"] == 1


def test_series_wide_unwatch_clears_completion(client, tmp_path):
    _refresh(client, tmp_path, SERIES_M3U_WITH_S02)
    ids = _episode_ids(client)
    series_card = next(
        i for i in client.get("/api/items?kind=series&limit=100").json()["items"]
        if i["title"].startswith("Galaxy Quest")
    )
    series_id = series_card["id"]

    # Reset: un-watch any episode a previous test left watched (toggle semantics!).
    conn = sqlite3.connect(str(db_mod.db.path))
    try:
        watched_rows = conn.execute(
            "SELECT id FROM items WHERE kind = 'series' AND is_watched = 1"
        ).fetchall()
    finally:
        conn.close()
    for (ep_id,) in watched_rows:
        client.post(f"/api/items/{ep_id}/watched", headers={"X-API-Key": API_KEY})

    # Complete everything, then explicitly un-watch the whole series.
    for title, ep_id in ids.items():
        client.post(f"/api/items/{ep_id}/watched", headers={"X-API-Key": API_KEY})
    assert _counts(client)["watched_new"] == 0

    res = client.post(f"/api/series/{series_id}/watched", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    assert res.json()["is_watched"] == 0

    counts = _counts(client)
    assert counts["watched_new"] == 0
    assert counts["continue"] == 0  # nothing watched anymore


RIDGE_M3U = "\n".join([
    "#EXTM3U",
    '#EXTINF:-1 tvg-name="Ridge Patrol S01 E01" group-title="Series",Ridge Patrol S01 E01',
    "http://x/series/rp/1/1.mp4",
    '#EXTINF:-1 tvg-name="Ridge Patrol S01 E02" group-title="Series",Ridge Patrol S01 E02',
    "http://x/series/rp/1/2.mp4",
])

RIDGE_M3U_WITH_S02 = RIDGE_M3U + "\n" + "\n".join([
    '#EXTINF:-1 tvg-name="Ridge Patrol S02 E01" group-title="Series",Ridge Patrol S02 E01',
    "http://x/series/rp/2/1.mp4",
])


def test_completed_season_surfaces_in_watched_new(client, tmp_path):
    """Season-based rule: a fully watched earlier season plus unwatched
    episodes in a newer season qualifies for watched_new even when the
    series as a whole was never completed (the Marshals case: S01 finished
    while S02 E01 was already sitting unwatched in the catalog)."""
    # Season 2 already exists before season 1 is completed - that is what
    # keeps completed_at NULL here (all watched != series completed).
    _refresh(client, tmp_path, RIDGE_M3U_WITH_S02)
    ids = _episode_ids(client)
    s01 = {t: i for t, i in ids.items() if t.startswith("Ridge Patrol") and "S01" in t}
    assert len(s01) == 2

    for title, ep_id in s01.items():
        res = client.post(f"/api/items/{ep_id}/watched", headers={"X-API-Key": API_KEY})
        assert res.status_code == 200

    counts = _counts(client)
    assert counts["watched_new"] == 1
    assert counts["continue"] == 0  # not in both sections

    res = client.get("/api/series", params={"section": "watched_new"})
    assert res.status_code == 200
    titles = [i["title"] for i in res.json()["items"]]
    assert any(t.startswith("Ridge Patrol") for t in titles)

    # The series itself was never fully completed; the season flag drives it.
    conn = sqlite3.connect(str(db_mod.db.path))
    try:
        row = conn.execute(
            "SELECT completed_at, has_completed_season FROM series_groups WHERE title LIKE 'Ridge Patrol%'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] is None
    assert row[1] == 1

    # Watching the last open episode clears the flag again via the stats recompute.
    s02 = next(i for t, i in _episode_ids(client).items() if "S02" in t and "Ridge" in t)
    client.post(f"/api/items/{s02}/watched", headers={"X-API-Key": API_KEY})
    counts = _counts(client)
    assert counts["watched_new"] == 0
