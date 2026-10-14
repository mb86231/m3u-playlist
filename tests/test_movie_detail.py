"""Tests for the movie detail page: group detail API and group-wide watched toggle."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
from m3u_library import main


API_KEY = "movie-detail-test-key"


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


def _write_m3u(path: Path, entries):
    lines = ["#EXTM3U"]
    for title, group, url in entries:
        lines.append(f'#EXTINF:-1 tvg-name="{title}" group-title="{group}",{title}')
        lines.append(url)
    path.write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture(scope="module")
def seeded(client, tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("m3u")
    m3u = tmp_path / "source.m3u"
    _write_m3u(m3u, [
        ("Juliet, Naked [DE] [2018]", "Movie: German", "http://x/movie/juliet-de"),
        ("Juliet, Naked [Multi-Subs] [2018]", "Movie: Multi Subtitles/Audio", "http://x/movie/juliet-multi"),
        ("Juliet, Naked [Multi-Subs] [2018] 4K", "Movie: 4K", "http://x/movie/juliet-4k"),
        ("Solo Trip (2020)", "Movie: German", "http://x/movie/solo"),
        ("Sport Channel HD", "Live TV", "http://x/live/sport"),
    ])
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


def _library_ids(client):
    res = client.get("/api/items?kind=movie&limit=100")
    assert res.status_code == 200
    items = res.json()["items"]
    juliet = next(i for i in items if i["title"].startswith("Juliet, Naked"))
    solo = next(i for i in items if i["title"].startswith("Solo Trip"))
    return juliet, solo


def test_movie_page_route_serves_library_html(client, seeded):
    juliet, _ = _library_ids(client)
    res = client.get(f"/movie/{juliet['id']}")
    assert res.status_code == 200
    assert 'id="library"' in res.text


def test_movie_detail_groups_versions(client, seeded):
    juliet, _ = _library_ids(client)
    res = client.get(f"/api/movies/{juliet['id']}")
    assert res.status_code == 200
    data = res.json()
    assert data["movie"]["version_count"] == 3
    assert len(data["versions"]) == 3
    # Best quality first (4K variant leads).
    assert "4K" in data["versions"][0]["title"]
    # Group state is aggregated over all versions.
    assert data["movie"]["is_watched"] == 0
    assert data["movie"]["is_favorite"] == 0


def test_movie_detail_unknown_id_is_404(client, seeded):
    res = client.get("/api/movies/no-such-id")
    assert res.status_code == 404


def test_movie_watched_toggle_sets_whole_group(client, seeded):
    juliet, _ = _library_ids(client)
    res = client.post(f"/api/movies/{juliet['id']}/watched")
    assert res.status_code == 200
    assert res.json()["is_watched"] == 1
    assert res.json()["updated"] == 3

    detail = client.get(f"/api/movies/{juliet['id']}").json()
    assert detail["movie"]["is_watched"] == 1
    assert all(v["is_watched"] == 1 for v in detail["versions"])

    # Toggling again clears the whole group.
    res = client.post(f"/api/movies/{juliet['id']}/watched")
    assert res.json()["is_watched"] == 0
    detail = client.get(f"/api/movies/{juliet['id']}").json()
    assert all(v["is_watched"] == 0 for v in detail["versions"])


def test_movie_watched_toggle_single_version_movie(client, seeded):
    _, solo = _library_ids(client)
    res = client.post(f"/api/movies/{solo['id']}/watched")
    assert res.status_code == 200
    assert res.json()["updated"] == 1
    detail = client.get(f"/api/movies/{solo['id']}").json()
    assert detail["movie"]["version_count"] == 1
    assert detail["movie"]["is_watched"] == 1


def test_movie_watched_toggle_live_item_affects_only_itself(client, seeded):
    res = client.get("/api/items?kind=live&limit=100")
    live = res.json()["items"][0]
    res = client.post(f"/api/movies/{live['id']}/watched")
    assert res.status_code == 200
    assert res.json()["updated"] == 1
