"""Tests for the same-origin TMDB poster proxy (/api/poster)."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
from m3u_library import main


API_KEY = "poster-test-key"

TMDB_URL = "https://image.tmdb.org/t/p/w342/bc6XIKP1TrnugYMzIIUz9YCL8VM.jpg"


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
        db_mod.db.path = db_path
        tmpdir_path.mkdir(parents=True, exist_ok=True)
        with TestClient(main.app) as c:
            yield c
    mp.undo()


@pytest.fixture(autouse=True)
def clear_poster_cache():
    main._poster_cache.clear()
    yield
    main._poster_cache.clear()


def test_poster_proxy_fetches_and_caches(client, monkeypatch):
    calls = []

    def fake_fetch(url, timeout=15):
        calls.append(url)
        return b"\xff\xd8fake-jpeg\xff\xd9", "image/jpeg"

    monkeypatch.setattr(main, "fetch_image_bytes", fake_fetch)
    res = client.get("/api/poster", params={"u": TMDB_URL})
    assert res.status_code == 200
    assert res.content == b"\xff\xd8fake-jpeg\xff\xd9"
    assert res.headers["content-type"].startswith("image/jpeg")
    assert "max-age=86400" in res.headers.get("cache-control", "")

    # Second request is served from the in-memory cache: no second upstream call.
    res2 = client.get("/api/poster", params={"u": TMDB_URL})
    assert res2.status_code == 200
    assert calls == [TMDB_URL]


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/pic.jpg",
        "http://image.tmdb.org/t/p/w342/x.jpg",
        "https://sub.image.tmdb.org.evil.com/pic.jpg",
        "https://image.tmdb.org.evil.com/pic.jpg",
    ],
)
def test_poster_proxy_rejects_non_tmdb_hosts(client, url):
    res = client.get("/api/poster", params={"u": url})
    assert res.status_code == 400
    assert not main._poster_cache


def test_poster_proxy_upstream_failure_is_502(client, monkeypatch):
    def boom(url, timeout=15):
        raise OSError("network down")

    monkeypatch.setattr(main, "fetch_image_bytes", boom)
    res = client.get("/api/poster", params={"u": TMDB_URL})
    assert res.status_code == 502
    # Failed fetches must not poison the cache.
    assert not main._poster_cache


def test_poster_proxy_requires_url_param(client):
    assert client.get("/api/poster").status_code == 422


def test_poster_proxy_is_public(client, monkeypatch):
    """No API key / session needed: the browser <img> tags call it directly."""
    monkeypatch.setattr(main, "fetch_image_bytes", lambda url, timeout=15: (b"x", "image/jpeg"))
    res = client.get("/api/poster", params={"u": TMDB_URL})
    assert res.status_code == 200
