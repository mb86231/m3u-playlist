"""Update ticker: show a chip when a newer release exists on GitHub.

Strictly informational, mirroring the kraken-dca-bot updater design:

- A small background thread polls the GitHub public API
  (``repos/<owner>/<repo>/releases/latest``; no token required) at the
  configured interval, compares the release tag with
  :data:`m3u_library.APP_VERSION` and persists what it saw in a JSON
  state file under ``DATA_DIR``.
- The library UI reads the persisted state through ``GET /api/update-status``
  and renders a dismissible chip next to the source-status chips. All
  rendering uses ``textContent``-style escaping — nothing from the
  network is injected as HTML.
- Every failure mode (offline, API error, malformed payload) is silent by
  design: the ticker must never disturb library serving, refresh or
  startup. stdlib ``urllib`` only — no new dependency.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from m3u_library import APP_VERSION
from m3u_library.settings import data_dir

logger = logging.getLogger(__name__)

GITHUB_RELEASES_LATEST_URL = (
    "https://api.github.com/repos/mb86231/m3u-playlist/releases/latest"
)
REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_CHECK_INTERVAL_HOURS = 24
DEFAULT_STATE_FILENAME = "update_state.json"

# Tags like "latest" or "nightly" must never compare as "newer".
def parse_version(tag: str) -> Optional[tuple[int, ...]]:
    """Parse a release tag like ``v1.1.3``/``1.1.3`` into a numeric tuple."""
    cleaned = tag.strip().lstrip("vV")
    if not cleaned or not all(part.isdigit() for part in cleaned.split(".")):
        return None
    return tuple(int(part) for part in cleaned.split("."))


def is_newer_version(latest: str, current: str) -> bool:
    """True when ``latest`` is a strictly newer plain version than ``current``."""
    latest_tuple = parse_version(latest)
    current_tuple = parse_version(current)
    if latest_tuple is None or current_tuple is None:
        return False
    length = max(len(latest_tuple), len(current_tuple))
    padded_latest = latest_tuple + (0,) * (length - len(latest_tuple))
    padded_current = current_tuple + (0,) * (length - len(current_tuple))
    return padded_latest > padded_current


def fetch_latest_release(
    url: str = GITHUB_RELEASES_LATEST_URL,
) -> Optional[dict[str, str]]:
    """Fetch the newest GitHub release; ``None`` on any failure.

    Only three fields are consumed and only ever rendered as text:
    tag name, publication time and the release-notes URL.
    """
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"m3u-library/{APP_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name") or "")
    if not tag:
        return None
    return {
        "tag": tag,
        "published_at": str(payload.get("published_at") or ""),
        "url": str(payload.get("html_url") or ""),
    }


class UpdateState:
    """Small JSON state: what we last saw, what the user dismissed."""

    def __init__(self, path: Path | str | None = None):
        if path is None:
            path = data_dir() / DEFAULT_STATE_FILENAME
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)


class UpdateChecker:
    """Periodic GitHub release check; results consumed via the API."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        interval_hours: int = DEFAULT_CHECK_INTERVAL_HOURS,
        retry_delay_seconds: int = 10,
        state: Optional[UpdateState] = None,
        current_version: str = APP_VERSION,
    ):
        self.enabled = enabled
        self.interval_seconds = max(1, int(interval_hours)) * 3600
        self.retry_delay_seconds = max(0, int(retry_delay_seconds))
        self.state = state or UpdateState()
        self.current_version = current_version
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- checking -----------------------------------------------------------

    def check_now(self) -> dict[str, Any]:
        """One check cycle: fetch, compare, persist. Never raises."""
        data = self.state.load()
        data["last_check_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        release = fetch_latest_release()
        if release is None:
            # Transient network races at boot are common; one short retry
            # before accepting the miss.
            self._stop.wait(self.retry_delay_seconds)
            release = fetch_latest_release()
        if release is not None:
            data["latest_seen_tag"] = release["tag"]
            data["latest_published_at"] = release["published_at"]
            data["latest_url"] = release["url"]
        self.state.save(data)
        return data

    def check_if_due(self) -> dict[str, Any]:
        """Check only when the configured interval has passed since the last one."""
        data = self.state.load()
        last = data.get("last_check_at")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if (
                    datetime.now(timezone.utc) - last_dt
                ).total_seconds() < self.interval_seconds:
                    return data
            except ValueError:
                pass
        return self.check_now()

    # -- background loop ------------------------------------------------------

    def start_background(self) -> None:
        """Start the daemon thread; no-op when disabled or already running."""
        if not self.enabled or self._thread is not None:
            return

        def _loop() -> None:
            # The first check runs a little after startup, not instantly: the
            # service can come up before the host network is fully routed
            # (seen in production: immediate check fails, next only in 24h).
            try:
                self._stop.wait(30)
                self.check_now()
            except Exception:
                logger.exception("update check failed")
            while not self._stop.wait(self.interval_seconds):
                try:
                    self.check_now()
                except Exception:
                    logger.exception("update check failed")

        self._thread = threading.Thread(
            target=_loop, name="update-checker", daemon=True
        )
        self._thread.start()

    def set_enabled(self, enabled: bool) -> None:
        """Apply a settings change live: start or stop the background loop."""
        self.enabled = enabled
        if enabled:
            self.start_background()
        else:
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
            self._thread = None
        self._stop.clear()


def status_payload(
    checker: Optional[UpdateChecker] = None, *, enabled: Optional[bool] = None
) -> dict[str, Any]:
    """What the UI chip needs; pure read of persisted state."""
    if enabled is None:
        enabled = checker.enabled if checker else True
    state = (checker.state if checker else UpdateState()).load()
    latest = state.get("latest_seen_tag") or ""
    dismissed = state.get("dismissed_tag") or ""
    return {
        "enabled": bool(enabled),
        "current_version": APP_VERSION,
        "latest_version": latest,
        "update_available": bool(
            enabled and latest and latest != dismissed
            and is_newer_version(latest, APP_VERSION)
        ),
        "release_url": state.get("latest_url") or "",
        "published_at": state.get("latest_published_at") or "",
        "last_check_at": state.get("last_check_at") or "",
        "dismissed": bool(latest) and latest == dismissed,
    }


def update_check_enabled() -> bool:
    """Settings/env switch; on unless explicitly disabled (``UPDATE_CHECK_ENABLED=0``)."""
    return os.getenv("UPDATE_CHECK_ENABLED", "1").strip().lower() not in ("0", "off", "false")


def dismiss_latest(checker: Optional[UpdateChecker] = None) -> dict[str, Any]:
    """Hide the currently-seen tag until a different one appears."""
    state = checker.state if checker else UpdateState()
    data = state.load()
    latest = data.get("latest_seen_tag") or ""
    if latest:
        data["dismissed_tag"] = latest
        state.save(data)
    return data
