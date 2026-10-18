"""Favorites section sorting: most recently favorited first.

favorited_at (migration 4) records when a favorite was set; both
/api/items and /api/series sort their favorites section by it, falling
back to the addition date for favorites predating the column.
"""

import os
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
from m3u_library import main


API_KEY = "fav-sort-test-key"

M3U = "\n".join([
    "#EXTM3U",
    '#EXTINF:-1 tvg-name="Alpha Movie (2020)" group-title="Movie: German",Alpha Movie (2020)',
    "http://x/movies/alpha.mp4",
    '#EXTINF:-1 tvg-name="Beta Movie (2021)" group-title="Movie: German",Beta Movie (2021)',
    "http://x/movies/beta.mp4",
    '#EXTINF:-1 tvg-name="First Show S01 E01" group-title="Series",First Show S01 E01',
    "http://x/series/first/1/1.mp4",
    '#EXTINF:-1 tvg-name="Second Show S01 E01" group-title="Series",Second Show S01 E01',
    "http://x/series/second/1/1.mp4",
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


@pytest.fixture(scope="module", autouse=True)
def seeded(client, tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("m3u")
    m3u = tmp_path / "source.m3u"
    m3u.write_text(M3U, encoding="utf-8")
    old = os.environ.get("M3U_URL")
    os.environ["M3U_URL"] = m3u.as_uri()
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    if old is None:
        os.environ.pop("M3U_URL", None)
    else:
        os.environ["M3U_URL"] = old
    assert res.status_code == 200


def _movie_ids(client):
    res = client.get("/api/items?kind=movie&limit=100")
    assert res.status_code == 200
    return {i["title"].split(" (")[0]: i["id"] for i in res.json()["items"]}


def _series_ids(client):
    res = client.get("/api/items?kind=series&limit=100")
    assert res.status_code == 200
    return {i["title"].split(" (")[0]: i["id"] for i in res.json()["items"]}


def _favorite(client, kind, item_id):
    res = client.post(f"/api/items/{item_id}/favorite", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200, res.text
    return res.json()


def _favorite_series(client, series_id):
    res = client.post(f"/api/series/{series_id}/favorite", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200, res.text
    return res.json()


def test_items_section(client):
    """Favorites sort by most recently favorited, both orders."""
    ids = _movie_ids(client)
    _favorite(client, "movie", ids["Beta Movie"])
    time.sleep(1.1)  # favorited_at has second resolution
    _favorite(client, "movie", ids["Alpha Movie"])

    res = client.get("/api/items", params={"section": "favorites", "kind": "movie"})
    assert res.status_code == 200
    titles = [i["title"].split(" (")[0] for i in res.json()["items"]]
    assert titles == ["Alpha Movie", "Beta Movie"]

    # Re-favoriting Beta (toggle off, then on) makes it the most recent.
    time.sleep(1.1)  # keep favorited_at timestamps distinct (second resolution)
    _favorite(client, "movie", ids["Beta Movie"])  # off
    _favorite(client, "movie", ids["Beta Movie"])  # on
    res = client.get("/api/items", params={"section": "favorites", "kind": "movie"})
    titles = [i["title"].split(" (")[0] for i in res.json()["items"]]
    assert titles == ["Beta Movie", "Alpha Movie"]


def test_series_section(client):
    ids = _series_ids(client)
    _favorite_series(client, ids["First Show"])
    time.sleep(1.1)
    _favorite_series(client, ids["Second Show"])

    res = client.get("/api/series", params={"section": "favorites"})
    assert res.status_code == 200
    titles = [i["title"].split(" (")[0] for i in res.json()["items"]]
    assert titles.index("Second Show") < titles.index("First Show")


def test_favorited_at_persisted(client):
    conn = sqlite3.connect(str(db_mod.db.path))
    try:
        rows = conn.execute(
            "SELECT title, favorited_at FROM items WHERE is_favorite = 1"
        ).fetchall()
    finally:
        conn.close()
    assert rows, "expected favorited items"
    for title, favorited_at in rows:
        assert favorited_at, f"{title} missing favorited_at"
