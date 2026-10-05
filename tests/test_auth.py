import os
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
        m3u_path = tmpdir_path / "test.m3u"
        m3u_path.write_text(
            '#EXTM3U\n#EXTINF:-1 tvg-name="Test",Test\nhttp://example.com/test.mp4\n',
            encoding="utf-8",
        )
        mp.setenv("DATA_DIR", str(tmpdir_path))
        mp.setenv("DATABASE_PATH", str(db_path))
        mp.setenv("API_KEY", API_KEY)
        mp.setenv("M3U_URL", m3u_path.as_uri())
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


def test_admin_endpoints_require_api_key(client):
    for path in ("/api/refresh", "/api/metadata/enrich", "/api/metadata/warmup"):
        res = client.post(path)
        assert res.status_code == 403, f"{path} should require API key"

    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200

    res = client.post("/api/metadata/warmup", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200


def test_admin_endpoints_reject_same_origin_browser_requests_without_login(client):
    # The old same-origin exemption is gone: browsers must log in on the
    # settings page (session cookie) or send the API key.
    res = client.post("/api/refresh", headers={"Sec-Fetch-Site": "same-origin"})
    assert res.status_code == 403

    res = client.post(
        "/api/refresh",
        headers={"Origin": "http://testserver", "Host": "testserver"},
    )
    assert res.status_code == 403


def test_admin_endpoints_open_when_no_key_configured(client):
    old_key = os.environ.pop("API_KEY", None)
    try:
        res = client.post("/api/refresh")
        assert res.status_code == 200
    finally:
        if old_key is not None:
            os.environ["API_KEY"] = old_key
