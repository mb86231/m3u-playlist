import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
from m3u_library import main


API_KEY = "test-api-key"


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
        # Disable background metadata warmup so tests don't hang on network timeouts.
        mp.setattr(main, "run_metadata_warmup", lambda last_refresh=None: None)
        db_mod.db.path = db_path
        tmpdir_path.mkdir(parents=True, exist_ok=True)
        with TestClient(main.app) as c:
            yield c
    mp.undo()


def _m3u(urls):
    lines = ["#EXTM3U"]
    for title, url in urls:
        lines.append(f'#EXTINF:-1 tvg-name="{title}",{title}')
        lines.append(url)
    return "\n".join(lines)


def _write_m3u_file(path: Path, urls):
    path.write_text(_m3u(urls), encoding="utf-8")


def test_refresh_requires_api_key(client, tmp_path):
    m3u_path = tmp_path / "test.m3u"
    _write_m3u_file(m3u_path, [("Test Movie", "http://example.com/movie/1.mp4")])
    os.environ["M3U_URL"] = m3u_path.as_uri()

    res = client.post("/api/refresh")
    assert res.status_code == 403


def test_refresh_inserts_new_items(client, tmp_path):
    m3u_path = tmp_path / "test.m3u"
    _write_m3u_file(m3u_path, [
        ("Test Movie", "http://example.com/movie/1.mp4"),
        ("My Show S01 E01", "http://example.com/series/1/1/1.mp4"),
    ])
    os.environ["M3U_URL"] = m3u_path.as_uri()

    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    data = res.json()
    assert data["added"] == 2
    assert data["updated"] == 0


def test_refresh_updates_url_without_orphaning_state(client, tmp_path):
    m3u_path = tmp_path / "test.m3u"
    _write_m3u_file(m3u_path, [
        ("Test Movie", "http://example.com/movie/1.mp4"),
    ])
    os.environ["M3U_URL"] = m3u_path.as_uri()
    client.post("/api/refresh", headers={"X-API-Key": API_KEY})

    movie_id = main.item_id(kind="movie", title="Test Movie", stream_url="http://example.com/movie/1.mp4")
    res = client.post(f"/api/items/{movie_id}/watched")
    assert res.status_code == 200
    assert res.json()["is_watched"] == 1

    _write_m3u_file(m3u_path, [
        ("Test Movie", "http://example.com/movie/1_NEW.mp4"),
    ])
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    data = res.json()
    assert data["added"] == 0
    assert data["updated"] >= 1

    conn = sqlite3.connect(str(main.DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT is_watched, stream_url FROM items WHERE id = ?", (movie_id,)).fetchone()
    assert row["is_watched"] == 1
    assert "_NEW" in row["stream_url"]


def test_refresh_dedupes_duplicate_ids_in_playlist(client, tmp_path):
    """Providers may list the same movie twice (quality variants). Item ids are
    content-derived, so both lines share one id — refresh must not crash with
    UNIQUE constraint failed: items.id."""
    m3u_path = tmp_path / "test.m3u"
    _write_m3u_file(m3u_path, [
        ("Dup Movie", "http://example.com/movie/dup_1080.mp4"),
        ("Dup Movie", "http://example.com/movie/dup_4k.mp4"),
        ("Other Movie", "http://example.com/movie/other.mp4"),
    ])
    os.environ["M3U_URL"] = m3u_path.as_uri()

    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    data = res.json()
    assert data["added"] == 2
    assert data["removed"] >= 0

    conn = sqlite3.connect(str(main.DB_PATH))
    rows = conn.execute("SELECT COUNT(*) AS n FROM items WHERE title = 'Dup Movie'").fetchone()
    conn.close()
    assert rows[0] == 1


def test_continue_watching_section(client, tmp_path):
    """Continue Watching = series started (>=1 episode watched) but not finished."""
    m3u_path = tmp_path / "test.m3u"
    _write_m3u_file(m3u_path, [
        ("Progress Show S01 E01", "http://example.com/series/progress/1/1.mp4"),
        ("Progress Show S01 E02", "http://example.com/series/progress/1/2.mp4"),
        ("Done Show S01 E01", "http://example.com/series/done/1/1.mp4"),
    ])
    os.environ["M3U_URL"] = m3u_path.as_uri()
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200

    # /api/items always consults TMDB trending/popular/upcoming; stub them
    # (no network, no TMDB key in the test environment).
    async def _empty_ids(conn):
        return {"movie_ids": set(), "series_ids": set()}

    async def _empty_upcoming(conn):
        return {"items": []}

    mp = pytest.MonkeyPatch()
    mp.setattr(main, "async_trending_library_ids", _empty_ids)
    mp.setattr(main, "async_popular_library_ids", _empty_ids)
    mp.setattr(main, "async_get_upcoming_snapshot", _empty_upcoming)

    conn = sqlite3.connect(str(main.DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, title FROM items WHERE kind = 'series'").fetchall()
    ids = {row["title"]: row["id"] for row in rows}
    conn.close()

    # Start Progress Show (1 of 2), finish Done Show (1 of 1).
    client.post(f"/api/items/{ids['Progress Show S01 E01']}/watched", headers={"X-API-Key": API_KEY})
    client.post(f"/api/items/{ids['Done Show S01 E01']}/watched", headers={"X-API-Key": API_KEY})

    res = client.get("/api/items", params={"section": "continue"})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] == 1
    assert data["items"][0]["title"] == "Progress Show"
    assert data["section_counts"]["continue"] == 1

    res = client.get("/api/series", params={"section": "continue"})
    assert res.status_code == 200
    assert res.json()["matched"] == 1

    # Watched = abgeschlossen: nur die komplett gesehene Serie, die angefangene
    # Serie darf hier nicht auftauchen (Regression: frueher zaehlte jede
    # gesehene Folge als "watched").
    res = client.get("/api/series", params={"section": "watched"})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] == 1
    assert data["items"][0]["title"] == "Done Show"
    assert data["section_counts"]["watched"] == 1

    # Gemischte Items-Ansicht wendet dieselbe Abgeschlossen-Regel an.
    res = client.get("/api/items", params={"section": "watched", "kind": "series"})
    assert res.status_code == 200
    data = res.json()
    assert data["matched"] == 1
    assert data["items"][0]["title"] == "Done Show"
    assert data["section_counts"]["watched"] == 1
    mp.undo()
