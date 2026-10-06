"""Tests for the server-side M3U source check and the refresh failure guard."""

import os
import tempfile
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
from m3u_library import main


API_KEY = "source-test-key"


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
        # /api/items always resolves TMDB trending/popular/upcoming snapshots;
        # stub them so tests never need TMDB credentials.
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


def _m3u(urls):
    lines = ["#EXTM3U"]
    for title, url in urls:
        lines.append(f'#EXTINF:-1 tvg-name="{title}",{title}')
        lines.append(url)
    return "\n".join(lines)


def _write_m3u_file(path: Path, urls):
    path.write_text(_m3u(urls), encoding="utf-8")


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://example.test/list", code, "error", {}, None)


# ---------------------------------------------------------------------------
# check_source classification
# ---------------------------------------------------------------------------

def test_check_source_ok_counts_entries(monkeypatch):
    monkeypatch.setattr(main, "fetch_text", lambda *a, **k: _m3u([("A", "http://x/1.mp4"), ("B", "http://x/2.mp4")]))
    result = main.check_source("http://example.test/list")
    assert result["state"] == "ok"
    assert result["entry_count"] == 2
    assert result["checked_at"]


def test_check_source_empty_playlist(monkeypatch):
    monkeypatch.setattr(main, "fetch_text", lambda *a, **k: "#EXTM3U\n")
    assert main.check_source("http://example.test/list")["state"] == "empty"


def test_check_source_invalid_content(monkeypatch):
    monkeypatch.setattr(main, "fetch_text", lambda *a, **k: "<html>login page</html>")
    assert main.check_source("http://example.test/list")["state"] == "invalid"


@pytest.mark.parametrize("code", [401, 403])
def test_check_source_auth_failed(monkeypatch, code):
    def boom(*a, **k):
        raise _http_error(code)
    monkeypatch.setattr(main, "fetch_text", boom)
    result = main.check_source("http://example.test/list")
    assert result["state"] == "auth_failed"
    assert f"HTTP {code}" in result["detail"]


def test_check_source_other_http_error_is_unreachable(monkeypatch):
    def boom(*a, **k):
        raise _http_error(500)
    monkeypatch.setattr(main, "fetch_text", boom)
    assert main.check_source("http://example.test/list")["state"] == "unreachable"


def test_check_source_timeout_is_unreachable(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(main, "fetch_text", boom)
    result = main.check_source("http://example.test/list")
    assert result["state"] == "unreachable"
    # The failing URL must never leak into the stored result.
    assert "example.test" not in str(result)


def test_mask_url_redacts_credentials():
    masked = main.mask_url("http://user:secret@provider.example:8080/get.php?username=u&password=p&type=m3u")
    assert masked == "http://provider.example:8080/get.php"
    assert "secret" not in masked and "password" not in masked


# ---------------------------------------------------------------------------
# API behaviour
# ---------------------------------------------------------------------------

def test_source_status_not_configured(client, monkeypatch):
    monkeypatch.delenv("M3U_URL", raising=False)
    res = client.get("/api/source-status")
    assert res.status_code == 200
    assert res.json()["state"] == "not_configured"


def test_source_status_unknown_before_check(client, tmp_path, monkeypatch):
    m3u_path = tmp_path / "source.m3u"
    _write_m3u_file(m3u_path, [("Film A", "http://example.com/movie/1.mp4")])
    monkeypatch.setenv("M3U_URL", m3u_path.as_uri())
    res = client.get("/api/source-status")
    assert res.json()["state"] == "unknown"


def test_admin_check_source_ok(client, tmp_path, monkeypatch):
    m3u_path = tmp_path / "source.m3u"
    _write_m3u_file(m3u_path, [("Film A", "http://example.com/movie/1.mp4")])
    monkeypatch.setenv("M3U_URL", m3u_path.as_uri())
    res = client.post("/api/admin/source-status/check", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    data = res.json()
    assert data["state"] == "ok"
    assert data["entry_count"] == 1
    # The library must stay untouched by a pure check.
    items = client.get("/api/items?limit=50").json()
    assert items["matched"] == 0


def test_admin_check_source_requires_auth(client, tmp_path, monkeypatch):
    m3u_path = tmp_path / "source.m3u"
    _write_m3u_file(m3u_path, [("Film A", "http://example.com/movie/1.mp4")])
    monkeypatch.setenv("M3U_URL", m3u_path.as_uri())
    res = client.post("/api/admin/source-status/check")
    assert res.status_code == 403


def test_source_status_reset_when_url_changes(client, tmp_path, monkeypatch):
    m3u_a = tmp_path / "a.m3u"
    m3u_b = tmp_path / "b.m3u"
    _write_m3u_file(m3u_a, [("Film A", "http://example.com/movie/1.mp4")])
    _write_m3u_file(m3u_b, [("Film B", "http://example.com/movie/2.mp4")])
    monkeypatch.setenv("M3U_URL", m3u_a.as_uri())
    res = client.post("/api/admin/source-status/check", headers={"X-API-Key": API_KEY})
    assert res.json()["state"] == "ok"

    monkeypatch.setenv("M3U_URL", m3u_b.as_uri())
    res = client.get("/api/source-status")
    assert res.json()["state"] == "unknown"


def test_settings_save_resets_source_status(client, tmp_path, monkeypatch):
    m3u_a = tmp_path / "a.m3u"
    _write_m3u_file(m3u_a, [("Film A", "http://example.com/movie/1.mp4")])
    monkeypatch.setenv("M3U_URL", m3u_a.as_uri())
    client.post("/api/admin/source-status/check", headers={"X-API-Key": API_KEY})
    assert client.get("/api/source-status").json()["state"] == "ok"

    # Simulate the settings UI saving a different URL.
    res = client.put("/api/admin/settings", headers={"X-API-Key": API_KEY}, json={"M3U_URL": "http://totally.different/playlist.m3u"})
    assert res.status_code == 200
    # The previous source's success must not be shown for the new URL.
    assert client.get("/api/source-status").json()["state"] == "unknown"


# ---------------------------------------------------------------------------
# Refresh failure guard: the library must survive a broken source
# ---------------------------------------------------------------------------

def test_refresh_failure_keeps_library_and_records_status(client, tmp_path, monkeypatch):
    m3u_path = tmp_path / "good.m3u"
    _write_m3u_file(m3u_path, [("Keep Me", "http://example.com/movie/9.mp4")])
    monkeypatch.setenv("M3U_URL", m3u_path.as_uri())
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    assert client.get("/api/items?limit=50").json()["matched"] == 1

    def boom(*a, **k):
        raise _http_error(401)
    monkeypatch.setattr(main, "fetch_text", boom)
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 502
    # Library unchanged.
    items = client.get("/api/items?limit=50").json()
    assert items["matched"] == 1
    assert items["items"][0]["title"] == "Keep Me"
    # Failure recorded for display.
    status = client.get("/api/source-status").json()
    assert status["state"] == "auth_failed"


def test_refresh_empty_playlist_keeps_library(client, tmp_path, monkeypatch):
    m3u_path = tmp_path / "good.m3u"
    _write_m3u_file(m3u_path, [("Keep Me", "http://example.com/movie/9.mp4")])
    monkeypatch.setenv("M3U_URL", m3u_path.as_uri())
    client.post("/api/refresh", headers={"X-API-Key": API_KEY})

    monkeypatch.setattr(main, "fetch_text", lambda *a, **k: "#EXTM3U\n")
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 422
    assert client.get("/api/items?limit=50").json()["matched"] == 1
    assert client.get("/api/source-status").json()["state"] == "empty"


def test_refresh_invalid_content_keeps_library(client, tmp_path, monkeypatch):
    m3u_path = tmp_path / "good.m3u"
    _write_m3u_file(m3u_path, [("Keep Me", "http://example.com/movie/9.mp4")])
    monkeypatch.setenv("M3U_URL", m3u_path.as_uri())
    client.post("/api/refresh", headers={"X-API-Key": API_KEY})

    monkeypatch.setattr(main, "fetch_text", lambda *a, **k: "not a playlist at all")
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 422
    assert client.get("/api/items?limit=50").json()["matched"] == 1
    assert client.get("/api/source-status").json()["state"] == "invalid"


def test_refresh_success_records_ok_status(client, tmp_path, monkeypatch):
    m3u_path = tmp_path / "good.m3u"
    _write_m3u_file(m3u_path, [("Film A", "http://example.com/movie/1.mp4")])
    monkeypatch.setenv("M3U_URL", m3u_path.as_uri())
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    status = client.get("/api/source-status").json()
    assert status["state"] == "ok"
    assert status["entry_count"] == 1
