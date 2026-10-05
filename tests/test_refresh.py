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
