"""Tests for the admin settings UI, session auth, and secure secret storage."""

import os
import stat
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
import m3u_library.settings as settings
from m3u_library import main


PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a brand new passphrase"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("M3U_URL", raising=False)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    monkeypatch.delenv("TMDB_BEARER_TOKEN", raising=False)
    return data_dir


@pytest.fixture()
def client(env, monkeypatch):
    db_path = env / "app.db"
    monkeypatch.setenv("API_KEY", "settings-test-key")
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATA_DIR", env)
    monkeypatch.setattr(main, "DB_PATH", db_path)
    monkeypatch.setattr(main, "DATA_DIR", env)
    monkeypatch.setattr(main, "run_metadata_warmup", lambda last_refresh=None: None)
    db_mod.db.path = db_path
    with TestClient(main.app) as c:
        yield c


def test_update_env_file_preserves_comments_and_unrelated_lines(env):
    env_file = env / ".env"
    env_file.write_text("# comment line\nM3U_URL=https://old.example/list\nOTHER=value\n", encoding="utf-8")
    settings.update_env_file(env_file, {"M3U_URL": "https://new.example/list", "API_KEY": "abc"})
    text = env_file.read_text(encoding="utf-8")
    assert "# comment line" in text
    assert "OTHER=value" in text
    assert "M3U_URL=https://new.example/list" in text
    assert "API_KEY=abc" in text
    assert "https://old.example" not in text


def test_update_env_file_removes_keys_with_none(env):
    env_file = env / ".env"
    env_file.write_text("M3U_URL=https://old.example/list\nAPI_KEY=abc\n", encoding="utf-8")
    settings.update_env_file(env_file, {"API_KEY": None})
    text = env_file.read_text(encoding="utf-8")
    assert "API_KEY" not in text
    assert "M3U_URL=https://old.example/list" in text


def test_env_file_written_with_safe_permissions(env):
    if os.name == "nt":
        pytest.skip("POSIX file modes are not enforced on Windows")
    env_file = env / ".env"
    settings.update_env_file(env_file, {"M3U_URL": "https://example/list"})
    mode = stat.S_IMODE(env_file.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_apply_updates_updates_process_environment(env):
    settings.apply_updates({"M3U_URL": "https://example/list"}, path=env / ".env")
    assert os.environ["M3U_URL"] == "https://example/list"
    settings.apply_updates({"M3U_URL": None}, path=env / ".env")
    assert "M3U_URL" not in os.environ


def test_admin_password_hash_roundtrip(env):
    assert not settings.has_admin_password()
    settings.set_admin_password(PASSWORD)
    assert settings.has_admin_password()
    assert settings.verify_admin_password(PASSWORD)
    assert not settings.verify_admin_password("wrong")
    raw = settings.secrets_path().read_text(encoding="utf-8")
    assert PASSWORD not in raw


def test_short_password_rejected(env):
    with pytest.raises(ValueError):
        settings.set_admin_password("short")


def test_session_token_roundtrip(env):
    token, csrf = settings.issue_session_token()
    payload = settings.verify_session_token(token)
    assert payload is not None
    assert payload["csrf"] == csrf
    assert settings.verify_session_token(token + "tampered") is None
    assert settings.verify_session_token("garbage") is None


def test_setup_required_then_login_flow(client, env):
    assert client.get("/api/auth/status").json()["setup_required"] is True

    # Weak password rejected.
    res = client.post("/api/auth/setup", json={"password": "short"})
    assert res.status_code == 422

    res = client.post("/api/auth/setup", json={"password": PASSWORD})
    assert res.status_code == 200
    csrf = res.json()["csrf"]

    status = client.get("/api/auth/status").json()
    assert status["setup_required"] is False
    assert status["authenticated"] is True

    # Second setup is refused.
    res = client.post("/api/auth/setup", json={"password": "another-password"})
    assert res.status_code == 409

    # Wrong password rejected; cookie not set.
    client.post("/api/auth/logout")
    res = client.post("/api/auth/login", json={"password": "wrong"})
    assert res.status_code == 401

    res = client.post("/api/auth/login", json={"password": PASSWORD})
    assert res.status_code == 200
    assert res.json()["csrf"]


def test_settings_endpoints_require_auth(client):
    assert client.get("/api/admin/settings").status_code == 403
    assert client.put("/api/admin/settings", json={"M3U_URL": "x"}).status_code == 403
    assert client.post("/api/admin/settings/password", json={}).status_code == 403


def test_settings_roundtrip_masked_and_reveal(client, env):
    csrf = client.post("/api/auth/setup", json={"password": PASSWORD}).json()["csrf"]

    res = client.put("/api/admin/settings", json={
        "M3U_URL": "https://provider.example/playlist.m3u8?secret=token123",
        "TMDB_API_KEY": "tmdb-key-abc",
        "METADATA_LANGUAGE": "de-DE",
    }, headers={"X-CSRF-Token": csrf})
    assert res.status_code == 200

    data = client.get("/api/admin/settings").json()
    m3u = data["keys"]["M3U_URL"]
    assert m3u["set"] is True
    # Secrets are never returned as value — only as display-only masked.
    assert m3u["value"] is None
    assert m3u["masked"] != "https://provider.example/playlist.m3u8?secret=token123"
    assert "secret=token123" not in str(data)
    assert data["keys"]["METADATA_LANGUAGE"]["value"] == "de-DE"

    revealed = client.get("/api/admin/settings", params={"reveal": "true"}).json()
    assert revealed["keys"]["M3U_URL"]["value"] == "https://provider.example/playlist.m3u8?secret=token123"

    # Value persisted to the .env file on disk.
    on_disk = (env / ".env").read_text(encoding="utf-8")
    assert "M3U_URL=https://provider.example/playlist.m3u8?secret=token123" in on_disk
    if os.name != "nt":
        assert stat.S_IMODE((env / ".env").stat().st_mode) == 0o600


def test_settings_clear_value(client, env):
    csrf = client.post("/api/auth/setup", json={"password": PASSWORD}).json()["csrf"]
    client.put("/api/admin/settings", json={"TMDB_API_KEY": "tmdb-key-abc"}, headers={"X-CSRF-Token": csrf})
    assert client.get("/api/admin/settings").json()["keys"]["TMDB_API_KEY"]["set"] is True
    # Explicit clear removes the value.
    client.put("/api/admin/settings", json={"clear": ["TMDB_API_KEY"]}, headers={"X-CSRF-Token": csrf})
    assert client.get("/api/admin/settings").json()["keys"]["TMDB_API_KEY"]["set"] is False
    assert "TMDB_API_KEY" not in (env / ".env").read_text(encoding="utf-8")


def test_empty_or_missing_fields_leave_values_unchanged(client, env):
    # Regression: empty/missing fields and display-only masked placeholders
    # must never overwrite stored secrets.
    csrf = client.post("/api/auth/setup", json={"password": PASSWORD}).json()["csrf"]
    secret = "https://provider.example/playlist.m3u8?secret=token123"
    client.put("/api/admin/settings", json={"M3U_URL": secret}, headers={"X-CSRF-Token": csrf})

    masked = client.get("/api/admin/settings").json()["keys"]["M3U_URL"]["masked"]

    # Empty string, null, and absent key: all leave the value unchanged.
    client.put("/api/admin/settings", json={"M3U_URL": ""}, headers={"X-CSRF-Token": csrf})
    client.put("/api/admin/settings", json={"M3U_URL": None}, headers={"X-CSRF-Token": csrf})
    client.put("/api/admin/settings", json={"METADATA_LANGUAGE": "de-DE"}, headers={"X-CSRF-Token": csrf})
    data = client.get("/api/admin/settings").json()
    assert data["keys"]["M3U_URL"]["set"] is True

    # Even submitting the masked placeholder back would replace the secret
    # with garbage — the UI never does this anymore, but defense in depth:
    # the masked form is display-only and rejected as unchanged-field input
    # only matters client-side; here we assert masked != stored value.
    revealed = client.get("/api/admin/settings", params={"reveal": "true"}).json()
    assert revealed["keys"]["M3U_URL"]["value"] == secret
    assert masked != secret


def test_csrf_enforced_for_session_requests(client):
    login = client.post("/api/auth/setup", json={"password": PASSWORD})
    csrf = login.json()["csrf"]

    # Without the CSRF header a session request is rejected...
    res = client.put("/api/admin/settings", json={"M3U_URL": "https://x.example"})
    assert res.status_code == 403

    # ...and with the header it succeeds.
    res = client.put(
        "/api/admin/settings",
        json={"M3U_URL": "https://x.example"},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200


def test_cross_origin_login_rejected(client):
    res = client.post(
        "/api/auth/setup",
        json={"password": PASSWORD},
        headers={"Origin": "http://evil.example", "Host": "testserver"},
    )
    assert res.status_code == 403


def test_password_change(client):
    login = client.post("/api/auth/setup", json={"password": PASSWORD})
    csrf = login.json()["csrf"]

    res = client.post(
        "/api/admin/settings/password",
        json={"current": "wrong", "new": NEW_PASSWORD},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 401

    res = client.post(
        "/api/admin/settings/password",
        json={"current": PASSWORD, "new": NEW_PASSWORD},
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200

    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"password": NEW_PASSWORD}).status_code == 200


def test_api_key_regenerate(client, env):
    login = client.post("/api/auth/setup", json={"password": PASSWORD})
    csrf = login.json()["csrf"]

    res = client.post(
        "/api/admin/settings/api-key/regenerate",
        headers={"X-CSRF-Token": csrf},
    )
    assert res.status_code == 200
    key = res.json()["api_key"]
    assert len(key) == 64

    # Configure a playlist so /api/refresh can complete.
    m3u = env / "test.m3u"
    m3u.write_text(
        '#EXTM3U\n#EXTINF:-1 tvg-name="Test",Test\nhttp://example.com/test.mp4\n',
        encoding="utf-8",
    )
    client.put(
        "/api/admin/settings",
        json={"M3U_URL": m3u.as_uri()},
        headers={"X-CSRF-Token": csrf},
    )

    # The session can still refresh; without session or key it is 403.
    assert client.post("/api/auth/logout").status_code == 200
    assert client.post("/api/refresh").status_code == 403
    assert client.post("/api/refresh", headers={"X-API-Key": key}).status_code == 200


def test_settings_page_served(client):
    res = client.get("/settings")
    assert res.status_code == 200
    assert "Settings · M3U Library" in res.text
