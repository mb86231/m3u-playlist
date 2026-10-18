"""Regression test: series_detail must persist fetched metadata.

The detail endpoint used to call async_ensure_series_group_metadata on a
read_db connection, which never commits — the poster/description update was
silently lost, so the library card stayed empty until the next refresh
(affects e.g. "Nemesis" 2026-10-18). The ensure must run via write_db.
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
from m3u_library import main


API_KEY = "series-detail-meta-test-key"


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

        async def _fake_series_record(series_row):
            return {
                "title": "Nemesis",
                "release_date": "2026-05-14",
                "rating": 7.0,
                "description": "A relentless LAPD cop...",
                "poster_url": "https://image.tmdb.org/t/p/w342/fake-nemesis.jpg",
                "provider_url": "https://www.themoviedb.org/tv/12345",
                "cached_at": main.now_iso(),
            }

        mp.setattr(main, "async_build_series_group_record", _fake_series_record)

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


@pytest.fixture(scope="module")
def seeded(client, tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("m3u")
    m3u = tmp_path / "source.m3u"
    m3u.write_text("\n".join([
        "#EXTM3U",
        '#EXTINF:-1 tvg-name="Nemesis S01 E01" group-title="Series",Nemesis S01 E01',
        "http://x/series/nemesis/1/1.mp4",
    ]), encoding="utf-8")
    import os
    old = os.environ.get("M3U_URL")
    os.environ["M3U_URL"] = m3u.as_uri()
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    if old is None:
        os.environ.pop("M3U_URL", None)
    else:
        os.environ["M3U_URL"] = old
    assert res.status_code == 200
    return res.json()


def _series_id(client):
    res = client.get("/api/items?kind=series&limit=100")
    assert res.status_code == 200
    items = res.json()["items"]
    return next(i["id"] for i in items if i["title"].startswith("Nemesis"))


def test_series_detail_persists_metadata(client, seeded):
    series_id = _series_id(client)

    # Library card has no poster yet (metadata never warmed).
    res = client.get("/api/items?kind=series&limit=100")
    card = next(i for i in res.json()["items"] if i["id"] == series_id)
    assert not card["poster_url"]

    # Opening the detail page fetches metadata and must persist it.
    res = client.get(f"/api/series/{series_id}")
    assert res.status_code == 200
    assert res.json()["series"]["poster_url"] == "https://image.tmdb.org/t/p/w342/fake-nemesis.jpg"

    # The library card now shows the poster too (written via write_db).
    res = client.get("/api/items?kind=series&limit=100")
    card = next(i for i in res.json()["items"] if i["id"] == series_id)
    assert card["poster_url"] == "https://image.tmdb.org/t/p/w342/fake-nemesis.jpg"


def test_series_detail_keeps_existing_metadata(client, seeded):
    """A second detail call must not corrupt data (early-return path)."""
    series_id = _series_id(client)
    res = client.get(f"/api/series/{series_id}")
    assert res.status_code == 200
    assert res.json()["series"]["poster_url"] == "https://image.tmdb.org/t/p/w342/fake-nemesis.jpg"
