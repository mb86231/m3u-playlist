"""Tests for watched/favorite state snapshots and restore."""

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
from m3u_library import main


API_KEY = "state-backup-key"


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


def _seed(client, tmp_path, monkeypatch):
    m3u = tmp_path / "source.m3u"
    m3u.write_text("\n".join([
        "#EXTM3U",
        '#EXTINF:-1 tvg-name="Some Movie [DE] [2020]",Some Movie [DE] [2020]',
        "http://x/movie/some",
        '#EXTINF:-1 tvg-name="Test Show S01E01",Test Show S01E01',
        "http://x/series/testshow/1-1",
        '#EXTINF:-1 tvg-name="Test Show S01E02",Test Show S01E02',
        "http://x/series/testshow/1-2",
    ]), encoding="utf-8")
    monkeypatch.setenv("M3U_URL", m3u.as_uri())
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    return res.json()


def test_snapshot_written_after_refresh(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    snap = main.state_snapshot_dir() / "latest.json"
    assert snap.exists(), "latest.json snapshot missing after refresh"
    payload = json.loads(snap.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert len(payload["items"]) == 3
    assert len(payload["series_groups"]) == 1
    assert all(st["w"] == 0 and st["f"] == 0 for st in payload["items"].values())


def test_restore_roundtrip(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    movie_res = client.get("/api/items?kind=movie&limit=10")
    movie_id = movie_res.json()["items"][0]["id"]

    # Change state away from the snapshot
    toggle = client.post(f"/api/items/{movie_id}/watched")
    assert toggle.status_code == 200
    assert toggle.json()["is_watched"] == 1
    client.post(f"/api/items/{movie_id}/favorite")

    res = client.post("/api/state/restore", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    data = res.json()
    assert data["items_updated"] == 3
    assert data["items_missing"] == 0
    assert data["series_updated"] == 1

    after = client.get("/api/items?kind=movie&limit=10").json()["items"][0]
    assert after["is_watched"] == 0
    assert after["is_favorite"] == 0

    status = client.get("/api/status").json()
    assert status["last_refresh"]


def test_restore_unknown_file_404(client):
    res = client.post("/api/state/restore?file=nope.json", headers={"X-API-Key": API_KEY})
    assert res.status_code == 404


def test_snapshot_listing(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    res = client.get("/api/state/snapshots", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    data = res.json()
    assert data["latest"] and data["latest"] > 0
    assert len(data["snapshots"]) >= 1
