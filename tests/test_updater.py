"""Tests for the GitHub release update ticker (informational, stdlib-only)."""

import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
import m3u_library.settings as settings
import m3u_library.updater as updater
from m3u_library import main


# ---------------------------------------------------------------------------
# Version parsing / comparison
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "tag,expected",
    [
        ("v1.1.3", (1, 1, 3)),
        ("1.1.3", (1, 1, 3)),
        ("V2.0", (2, 0)),
        ("latest", None),
        ("v1.1.3-beta", None),
        ("", None),
        ("v1.x", None),
    ],
)
def test_parse_version(tag, expected):
    assert updater.parse_version(tag) == expected


@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("v1.1.3", "1.1.2", True),
        ("1.1.3", "v1.1.3", False),  # equal is not newer
        ("v1.2", "1.1.9", True),
        ("v2.0.0", "1.1.2", True),
        ("latest", "1.1.2", False),  # rolling tags never count
        ("v1.1.2", "1.1.2", False),
        ("v0.9", "1.1.2", False),
    ],
)
def test_is_newer_version(latest, current, expected):
    assert updater.is_newer_version(latest, current) is expected


# ---------------------------------------------------------------------------
# fetch_latest_release (urllib mocked)
# ---------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, payload, status=200):
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers = {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_latest_release_parses_payload(monkeypatch):
    payload = {
        "tag_name": "v9.9.9",
        "published_at": "2026-10-25T12:00:00Z",
        "html_url": "https://github.com/mb86231/m3u-playlist/releases/tag/v9.9.9",
    }
    monkeypatch.setattr(
        updater.urllib.request, "urlopen", lambda req, timeout: FakeResponse(payload)
    )
    release = updater.fetch_latest_release()
    assert release == {
        "tag": "v9.9.9",
        "published_at": "2026-10-25T12:00:00Z",
        "url": "https://github.com/mb86231/m3u-playlist/releases/tag/v9.9.9",
    }


def test_fetch_latest_release_returns_none_on_error(monkeypatch):
    def _boom(req, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(updater.urllib.request, "urlopen", _boom)
    assert updater.fetch_latest_release() is None


def test_fetch_latest_release_returns_none_on_malformed_json(monkeypatch):
    class BadJson(FakeResponse):
        def __init__(self):
            self.status = 200
            self.headers = {}
            self._body = b"not json"

    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout: BadJson())
    assert updater.fetch_latest_release() is None


def test_fetch_latest_release_returns_none_without_tag(monkeypatch):
    monkeypatch.setattr(
        updater.urllib.request, "urlopen", lambda req, timeout: FakeResponse({"name": "x"})
    )
    assert updater.fetch_latest_release() is None


# ---------------------------------------------------------------------------
# UpdateState / UpdateChecker
# ---------------------------------------------------------------------------

def test_update_state_roundtrip(tmp_path):
    state = updater.UpdateState(tmp_path / "state.json")
    assert state.load() == {}
    state.save({"latest_seen_tag": "v1.1.3", "dismissed_tag": "v1.1.2"})
    assert state.load()["latest_seen_tag"] == "v1.1.3"


def test_update_state_tolerates_corrupt_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json", encoding="utf-8")
    assert updater.UpdateState(path).load() == {}


def test_check_now_persists_release(monkeypatch, tmp_path):
    monkeypatch.setattr(
        updater,
        "fetch_latest_release",
        lambda: {"tag": "v9.9.9", "published_at": "2026-10-25T12:00:00Z", "url": "https://example/r"},
    )
    checker = updater.UpdateChecker(state=updater.UpdateState(tmp_path / "s.json"))
    data = checker.check_now()
    assert data["latest_seen_tag"] == "v9.9.9"
    assert data["last_check_at"]
    # Saved for the API to read afterwards
    assert updater.UpdateState(tmp_path / "s.json").load()["latest_url"] == "https://example/r"


def test_check_now_retries_once_after_failure(monkeypatch, tmp_path):
    attempts = []
    def _flaky():
        attempts.append(1)
        if len(attempts) == 1:
            return None  # first attempt fails, retry succeeds
        return {"tag": "v2.0.0", "published_at": "", "url": ""}
    monkeypatch.setattr(updater, "fetch_latest_release", _flaky)
    checker = updater.UpdateChecker(
        state=updater.UpdateState(tmp_path / "s.json"), retry_delay_seconds=0
    )
    assert checker.check_now()["latest_seen_tag"] == "v2.0.0"
    assert len(attempts) == 2


def test_check_now_survives_fetch_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "fetch_latest_release", lambda: None)
    checker = updater.UpdateChecker(
        state=updater.UpdateState(tmp_path / "s.json"), retry_delay_seconds=0
    )
    data = checker.check_now()
    assert data["last_check_at"]  # check time is still recorded
    assert "latest_seen_tag" not in data


def test_check_if_due_skips_within_interval(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        updater, "fetch_latest_release", lambda: calls.append(1) or None
    )
    checker = updater.UpdateChecker(
        state=updater.UpdateState(tmp_path / "s.json"),
        interval_hours=24,
        retry_delay_seconds=0,
    )
    checker.check_now()
    checker.check_if_due()
    assert len(calls) == 2  # one check with one retry; second call skipped


def test_set_enabled_starts_and_stops_background(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, "fetch_latest_release", lambda: None)
    checker = updater.UpdateChecker(
        enabled=False, state=updater.UpdateState(tmp_path / "s.json")
    )
    checker.start_background()
    assert checker._thread is None  # disabled: no thread
    checker.set_enabled(True)
    assert checker._thread is not None and checker._thread.is_alive()
    checker.set_enabled(False)
    assert checker._thread is None
    checker.stop()


# ---------------------------------------------------------------------------
# status_payload / dismiss / env switch
# ---------------------------------------------------------------------------

def _checker_with(tmp_path, **state):
    s = updater.UpdateState(tmp_path / "s.json")
    s.save(state)
    return updater.UpdateChecker(state=s)


def test_status_payload_flags_newer_release(tmp_path):
    checker = _checker_with(
        tmp_path, latest_seen_tag="v9.9.9", latest_url="https://example/r"
    )
    payload = updater.status_payload(checker)
    assert payload["current_version"] == updater.APP_VERSION
    assert payload["latest_version"] == "v9.9.9"
    assert payload["update_available"] is True
    assert payload["release_url"] == "https://example/r"


def test_status_payload_respects_dismissal(tmp_path):
    checker = _checker_with(tmp_path, latest_seen_tag="v9.9.9", dismissed_tag="v9.9.9")
    payload = updater.status_payload(checker)
    assert payload["update_available"] is False
    assert payload["dismissed"] is True


def test_status_payload_ignores_older_release(tmp_path):
    checker = _checker_with(tmp_path, latest_seen_tag="v1.0.0")
    assert updater.status_payload(checker)["update_available"] is False


def test_status_payload_disabled_via_env(monkeypatch, tmp_path):
    monkeypatch.setenv("UPDATE_CHECK_ENABLED", "0")
    checker = _checker_with(tmp_path, latest_seen_tag="v9.9.9")
    payload = updater.status_payload(checker, enabled=updater.update_check_enabled())
    assert payload["update_available"] is False


def test_dismiss_latest_hides_current_tag(tmp_path):
    checker = _checker_with(tmp_path, latest_seen_tag="v9.9.9")
    updater.dismiss_latest(checker)
    payload = updater.status_payload(checker)
    assert payload["update_available"] is False
    # A newer different tag must surface again
    updater.UpdateState(checker.state.path).save({"latest_seen_tag": "v9.9.10"})
    assert updater.status_payload(checker)["update_available"] is True


@pytest.mark.parametrize("value,expected", [("0", False), ("off", False), ("FALSE", False), ("1", True), ("", True)])
def test_update_check_enabled_env(monkeypatch, value, expected):
    monkeypatch.setenv("UPDATE_CHECK_ENABLED", value)
    assert updater.update_check_enabled() is expected


def test_update_check_enabled_defaults_on(monkeypatch):
    monkeypatch.delenv("UPDATE_CHECK_ENABLED", raising=False)
    assert updater.update_check_enabled() is True


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "app.db"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.delenv("UPDATE_CHECK_ENABLED", raising=False)
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "DB_PATH", db_path)
    monkeypatch.setattr(main, "DATA_DIR", data_dir)
    monkeypatch.setattr(main, "run_metadata_warmup", lambda last_refresh=None: None)
    monkeypatch.setattr(updater, "fetch_latest_release", lambda: None)
    db_mod.db.path = db_path
    with TestClient(main.app) as c:
        yield c


def test_update_status_endpoint_public(client, tmp_path):
    res = client.get("/api/update-status")
    assert res.status_code == 200
    data = res.json()
    assert data["current_version"] == updater.APP_VERSION
    assert data["update_available"] is False
    # Before the first background check ran, no timestamp is reported yet
    assert data["last_check_at"] == ""


def test_startup_checker_uses_data_dir_state(client, tmp_path, monkeypatch):
    # The checker built at startup persists into DATA_DIR, where the API
    # reads it back.
    monkeypatch.setattr(
        updater,
        "fetch_latest_release",
        lambda: {"tag": "v0.0.1", "published_at": "", "url": ""},  # older: no chip
    )
    assert main.UPDATE_CHECKER is not None
    main.UPDATE_CHECKER.check_now()
    state_file = tmp_path / "data" / "update_state.json"
    assert json.loads(state_file.read_text(encoding="utf-8"))["last_check_at"]
    data = client.get("/api/update-status").json()
    assert data["latest_version"] == "v0.0.1"
    assert data["update_available"] is False


def test_update_status_endpoint_reflects_newer_release(client, tmp_path):
    state_file = tmp_path / "data" / "update_state.json"
    state_file.write_text(
        json.dumps(
            {
                "latest_seen_tag": "v9.9.9",
                "latest_url": "https://example/release",
                "latest_published_at": "2026-10-25T12:00:00Z",
                "last_check_at": "2026-10-25T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    data = client.get("/api/update-status").json()
    assert data["update_available"] is True
    assert data["latest_version"] == "v9.9.9"
    res = client.post("/api/update-status/dismiss")
    assert res.status_code == 200
    assert res.json()["update_available"] is False
    # Persistent: a fresh read still shows the dismissal
    assert client.get("/api/update-status").json()["dismissed"] is True


# ---------------------------------------------------------------------------
# Settings round-trip for the toggle
# ---------------------------------------------------------------------------

def test_settings_ui_keys_contain_toggle():
    assert "UPDATE_CHECK_ENABLED" in settings.UI_KEYS
    assert "UPDATE_CHECK_ENABLED" in settings.NON_SECRET_KEYS


def test_admin_settings_returns_toggle_as_plain_value(client):
    client.post("/api/auth/setup", json={"password": "top-secret-pw"})
    data = client.get("/api/admin/settings").json()
    info = data["keys"]["UPDATE_CHECK_ENABLED"]
    assert info["value"] in ("1", "0", "")  # plain value, never masked
    assert info["value"] is None or "•" not in str(info["value"])
