from __future__ import annotations

import hashlib
import hmac
import html as html_lib
import json
import os
import re
import time
import sqlite3
import aiosqlite
import asyncio
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security, status
from fastapi.responses import HTMLResponse, Response
from fastapi.security import APIKeyHeader

from m3u_library import migrations
from m3u_library import settings
from m3u_library.pages import LIBRARY_HTML, SETTINGS_HTML
from m3u_library.db import db as ASYNC_DB, init_db as async_init_db, read_db, write_db, get_state as async_get_state, set_state as async_set_state


APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/lib/apps/m3u-library"))
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "app.db"))
ENV_PATHS = [DATA_DIR / ".env", APP_DIR / ".env"]

MAX_WARMUP_PER_RUN = 100
WARMUP_REQUEST_DELAY = 0.25  # seconds between TMDB requests to avoid DNS rate-limits
WARMUP_MIN_INTERVAL_SECONDS = 3600  # skip auto-startup warmup if it ran recently


def load_dotenv() -> None:
    for path in ENV_PATHS:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()
app = FastAPI(title="M3U Library")


@app.on_event("startup")
async def startup() -> None:
    await async_init_db()
    await ASYNC_DB.start()
    async with read_db() as conn:
        last_warmup = await async_get_state(conn, "metadata_warmup_finished_at")
    if not last_warmup:
        run_metadata_warmup()
        return
    try:
        last_warmup_dt = datetime.fromisoformat(last_warmup)
    except ValueError:
        run_metadata_warmup()
        return
    if (datetime.now(timezone.utc) - last_warmup_dt).total_seconds() > WARMUP_MIN_INTERVAL_SECONDS:
        async with read_db() as conn:
            last_refresh = await async_get_state(conn, "last_refresh")
        run_metadata_warmup(last_refresh=last_refresh)


METADATA_WARMUP_TASK: asyncio.Task | None = None
@app.middleware("http")
async def disable_cache(request: Request, call_next):
    response = await call_next(request)
    if "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@contextmanager
def db() -> Any:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_since_for_window(conn: sqlite3.Connection, new_window: str) -> str:
    """Return the ISO timestamp for the start of the requested 'new' window.

    - "refresh" uses the last playlist refresh timestamp.
    - A positive integer uses that many days back from now.
    - Anything else falls back to the last refresh.
    """
    window = (new_window or "refresh").strip().lower()
    if window == "refresh":
        return get_state(conn, "last_refresh") or ""
    try:
        days = int(window)
        if days <= 0:
            return get_state(conn, "last_refresh") or ""
    except ValueError:
        return get_state(conn, "last_refresh") or ""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


async def async_new_since_for_window(conn: aiosqlite.Connection, new_window: str) -> str:
    window = (new_window or "refresh").strip().lower()
    if window == "refresh":
        return await async_get_state(conn, "last_refresh") or ""
    try:
        days = int(window)
        if days <= 0:
            return await async_get_state(conn, "last_refresh") or ""
    except ValueError:
        return await async_get_state(conn, "last_refresh") or ""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def cooldown_before_retry(error_text: str) -> timedelta:
    message = (error_text or "").lower()
    if "no tmdb match found" in message or "404" in message:
        return timedelta(days=7)
    if "temporary failure in name resolution" in message or "timed out" in message:
        return timedelta(hours=6)
    return timedelta(hours=6)


def retry_after_iso(error_text: str) -> str:
    return (datetime.now(timezone.utc) + cooldown_before_retry(error_text)).isoformat(timespec="seconds")


def record_metadata_attempt(conn: sqlite3.Connection, entity_type: str, entity_id: str, error_text: str | None) -> None:
    conn.execute(
        """
        INSERT INTO metadata_attempts(entity_type, entity_id, last_attempted_at, last_error, attempts)
        VALUES(?, ?, ?, ?, 1)
        ON CONFLICT(entity_type, entity_id) DO UPDATE SET
          last_attempted_at = excluded.last_attempted_at,
          last_error = excluded.last_error,
          attempts = metadata_attempts.attempts + 1
        """,
        (entity_type, entity_id, retry_after_iso(error_text or ""), error_text),
    )


def clear_metadata_attempt(conn: sqlite3.Connection, entity_type: str, entity_id: str) -> None:
    conn.execute(
        "DELETE FROM metadata_attempts WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    )


_DB_INITIALIZED = False

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

SESSION_COOKIE = "m3u_admin"
SESSION_TTL_SECONDS = 7 * 86400
# Simple in-memory brute-force brake for the login endpoint:
# client IP -> [fail_count, first_fail_timestamp]
_LOGIN_FAILURES: dict[str, list[float]] = {}
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 30.0


def _secure_cookies() -> bool:
    return os.getenv("SECURE_COOKIES", "").strip().lower() in ("1", "true", "yes")


def _set_session_cookie(response: Response) -> str:
    """Start an admin session on ``response``; returns the CSRF token."""
    token, csrf = settings.issue_session_token()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
        path="/",
    )
    return csrf


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def _login_throttled(client_host: str) -> bool:
    entry = _LOGIN_FAILURES.get(client_host)
    if not entry:
        return False
    count, first = entry
    if count < LOGIN_MAX_FAILURES:
        return False
    if time.time() - first > LOGIN_LOCKOUT_SECONDS:
        _LOGIN_FAILURES.pop(client_host, None)
        return False
    return True


def _record_login_failure(client_host: str) -> None:
    entry = _LOGIN_FAILURES.get(client_host)
    if not entry or time.time() - entry[1] > LOGIN_LOCKOUT_SECONDS:
        _LOGIN_FAILURES[client_host] = [1, time.time()]
    else:
        entry[0] += 1


def _clear_login_failures(client_host: str) -> None:
    _LOGIN_FAILURES.pop(client_host, None)


def session_from_request(request: Request) -> dict[str, Any] | None:
    """Return the verified admin session payload, or ``None``."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return settings.verify_session_token(token)


def _check_api_key(request: Request, api_key: str | None) -> bool:
    """Return True when the request may access admin endpoints."""
    if session_from_request(request) is not None:
        return True
    expected = settings.effective_value("API_KEY")
    if not expected:
        return True
    return bool(api_key) and hmac.compare_digest(api_key, expected)


def require_api_key(request: Request, api_key: str | None = Security(api_key_header)) -> None:
    """Protect admin endpoints.

    Access is granted by a valid admin session (browser, after login on the
    settings page) or by the ``X-API-Key`` header (scripts such as the
    systemd refresh timer). When no API key is configured and no admin
    password is set, the app is unprotected and every request passes —
    enabling the first-run setup.
    """
    if _check_api_key(request, api_key):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid or missing API key",
    )


def require_admin(request: Request) -> dict[str, Any]:
    """Like :func:`require_api_key` plus CSRF enforcement for sessions.

    State-changing requests made with a session must carry the
    ``X-CSRF-Token`` header matching the token issued at login.
    """
    session = session_from_request(request)
    if session is not None:
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            supplied = request.headers.get("x-csrf-token", "")
            if not hmac.compare_digest(supplied, str(session.get("csrf", ""))):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Missing or invalid CSRF token",
                )
        return session
    if not _check_api_key(request, request.headers.get("x-api-key")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key",
        )
    return {}


def init_db() -> None:
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    _DB_INITIALIZED = True
    with db() as conn:
        migrations.run_migrations(conn)


def update_series_group_stats(conn: sqlite3.Connection, series_id: str) -> None:
    """Recompute pre-aggregated stats for a single series group."""
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS episode_count,
          COUNT(DISTINCT COALESCE(season_number, 0)) AS season_count,
          COALESCE(SUM(is_watched), 0) AS watched_episode_count,
          COALESCE(MAX(added_at), '') AS latest_added_at,
          MAX(is_watched) AS any_watched,
          COALESCE(MAX(group_name), '') AS group_name
        FROM items
        WHERE series_id = ? AND available = 1
        """,
        (series_id,),
    ).fetchone()
    is_watched = 1 if row["any_watched"] else 0
    watched_at = now_iso() if is_watched else None
    conn.execute(
        """
        UPDATE series_groups
        SET episode_count = ?,
            season_count = ?,
            watched_episode_count = ?,
            latest_added_at = ?,
            is_watched = ?,
            watched_at = ?,
            group_name = ?
        WHERE id = ?
        """,
        (
            row["episode_count"],
            row["season_count"],
            row["watched_episode_count"],
            row["latest_added_at"],
            is_watched,
            watched_at,
            row["group_name"],
            series_id,
        ),
    )


async def _async_update_series_group_stats(conn: aiosqlite.Connection, series_id: str) -> None:
    row = await (
        await conn.execute(
            """
            SELECT
              COUNT(*) AS episode_count,
              COUNT(DISTINCT COALESCE(season_number, 0)) AS season_count,
              COALESCE(SUM(is_watched), 0) AS watched_episode_count,
              COALESCE(MAX(added_at), '') AS latest_added_at,
              MAX(is_watched) AS any_watched,
              COALESCE(MAX(group_name), '') AS group_name
            FROM items
            WHERE series_id = ? AND available = 1
            """,
            (series_id,),
        )
    ).fetchone()
    is_watched = 1 if row["any_watched"] else 0
    watched_at = now_iso() if is_watched else None
    await conn.execute(
        """
        UPDATE series_groups
        SET episode_count = ?,
            season_count = ?,
            watched_episode_count = ?,
            latest_added_at = ?,
            is_watched = ?,
            watched_at = ?,
            group_name = ?
        WHERE id = ?
        """,
        (
            row["episode_count"],
            row["season_count"],
            row["watched_episode_count"],
            row["latest_added_at"],
            is_watched,
            watched_at,
            row["group_name"],
            series_id,
        ),
    )


def refresh_all_series_group_stats(conn: sqlite3.Connection) -> None:
    """Recompute pre-aggregated stats for every series group."""
    conn.execute(
        """
        WITH agg AS (
          SELECT
            series_id,
            COUNT(*) AS episode_count,
            COUNT(DISTINCT COALESCE(season_number, 0)) AS season_count,
            COALESCE(SUM(is_watched), 0) AS watched_episode_count,
            COALESCE(MAX(added_at), '') AS latest_added_at,
            COALESCE(MAX(is_watched), 0) AS any_watched,
            COALESCE(MAX(group_name), '') AS group_name
          FROM items
          WHERE available = 1 AND series_id IS NOT NULL
          GROUP BY series_id
        )
        UPDATE series_groups
        SET
          episode_count = COALESCE((SELECT episode_count FROM agg WHERE agg.series_id = series_groups.id), 0),
          season_count = COALESCE((SELECT season_count FROM agg WHERE agg.series_id = series_groups.id), 0),
          watched_episode_count = COALESCE((SELECT watched_episode_count FROM agg WHERE agg.series_id = series_groups.id), 0),
          latest_added_at = COALESCE((SELECT latest_added_at FROM agg WHERE agg.series_id = series_groups.id), ''),
          is_watched = COALESCE((SELECT any_watched FROM agg WHERE agg.series_id = series_groups.id), 0),
          watched_at = CASE WHEN COALESCE((SELECT any_watched FROM agg WHERE agg.series_id = series_groups.id), 0) = 1 THEN ? ELSE NULL END,
          group_name = COALESCE((SELECT group_name FROM agg WHERE agg.series_id = series_groups.id), '')
        """,
        (now_iso(),),
    )


def item_id(
    kind: str,
    title: str,
    stream_url: str,
    series_id: str | None = None,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> str:
    if kind == "series" and series_id is not None:
        key = f"series\n{series_id}\n{season_number}\n{episode_number}"
    elif kind == "movie":
        key = f"movie\n{title.strip().lower()}"
    else:
        key = f"{title}\n{stream_url}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def parse_attrs(line: str) -> dict[str, str]:
    return {m.group(1).lower(): m.group(2).strip() for m in re.finditer(r'([\w-]+)="([^"]*)"', line)}


def clean_title(extinf_line: str, attrs: dict[str, str]) -> str:
    raw = extinf_line.rsplit(",", 1)[-1].strip() if "," in extinf_line else ""
    title = attrs.get("tvg-name") or raw or "Untitled"
    return re.sub(r"\s+", " ", title).strip() or "Untitled"


def kind_from_url(group: str, title: str, url: str) -> str:
    if "/live/" in url:
        return "live"
    if "/movie/" in url:
        return "movie"
    if "/series/" in url:
        return "series"
    text = f"{group} {title}".lower()
    if re.search(r"series|serie|season|staffel|episode|\bs\d{1,2}\b", text):
        return "series"
    return "movie"


def series_group_id(series_title: str) -> str:
    return hashlib.sha256(series_title.lower().encode("utf-8")).hexdigest()[:20]


def parse_series_fields(title: str) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", title).strip()
    patterns = [
        re.compile(r"^(?P<name>.+?)\s+[Ss](?P<season>\d{1,2})\s*[Ee](?P<episode>\d{1,3})(?:\s*[-:]\s*(?P<label>.*))?$"),
        re.compile(r"^(?P<name>.+?)\s+(?P<season>\d{1,2})x(?P<episode>\d{1,3})(?:\s*[-:]\s*(?P<label>.*))?$", re.I),
    ]
    for pattern in patterns:
        match = pattern.match(normalized)
        if not match:
            continue
        name = match.group("name").strip(" -:_")
        label = (match.groupdict().get("label") or "").strip()
        series_title = clean_metadata_query(name, "series") or name
        return {
            "series_id": series_group_id(series_title),
            "series_title": series_title,
            "season_number": int(match.group("season")),
            "episode_number": int(match.group("episode")),
            "episode_label": label or None,
        }
    cleaned = clean_metadata_query(normalized, "series")
    if cleaned:
        return {
            "series_id": series_group_id(cleaned),
            "series_title": cleaned,
            "season_number": None,
            "episode_number": None,
            "episode_label": None,
        }
    return {
        "series_id": None,
        "series_title": None,
        "season_number": None,
        "episode_number": None,
        "episode_label": None,
    }


def parse_m3u(content: str) -> list[dict[str, str]]:
    pending: dict[str, str] | None = None
    items: list[dict[str, str]] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attrs = parse_attrs(line)
            group = attrs.get("group-title") or "Uncategorized"
            pending = {
                "title": clean_title(line, attrs),
                "group": group,
                "logo": attrs.get("tvg-logo", ""),
            }
            continue
        if line.startswith("#"):
            continue
        if pending:
            title = pending["title"]
            group = pending["group"]
            kind = kind_from_url(group, title, line)
            series_fields = parse_series_fields(title) if kind == "series" else {
                "series_id": None,
                "series_title": None,
                "season_number": None,
                "episode_number": None,
                "episode_label": None,
            }
            items.append(
                {
                    "id": item_id(
                        kind=kind,
                        title=title,
                        stream_url=line,
                        series_id=series_fields["series_id"],
                        season_number=series_fields["season_number"],
                        episode_number=series_fields["episode_number"],
                    ),
                    "title": title,
                    "group_name": group,
                    "kind": kind,
                    "logo": pending["logo"],
                    "stream_url": line,
                    **series_fields,
                }
            )
            pending = None
    return items


def fetch_text(url: str, headers: dict[str, str] | None = None, timeout: int = 60, bust_cache: bool = True) -> str:
    parsed = urllib.parse.urlparse(url)
    if bust_cache and parsed.scheme in {"http", "https"}:
        qs = urllib.parse.parse_qs(parsed.query)
        qs["_"] = [str(int(time.time()))]
        parsed = parsed._replace(query=urllib.parse.urlencode(qs, doseq=True))
    url = urllib.parse.urlunparse(parsed)
    req_headers = headers or {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
        "Accept": "application/vnd.apple.mpegurl, audio/mpegurl, application/x-mpegurl, text/plain, */*",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
    }
    req = urllib.request.Request(url, headers=req_headers)
    delays = [0.0, 1.0, 3.0]
    last_error: Exception | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
            encoding = response.headers.get("Content-Encoding", "").lower()
            if encoding == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            elif encoding == "deflate":
                import zlib
                raw = zlib.decompress(raw)
            print(f"M3U fetch: status={response.status}, bytes={len(raw)}, url={mask_url(url)}")
            return raw.decode("utf-8-sig", errors="replace")
        except urllib.error.URLError as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError("fetch_text failed without a captured error")


def set_state(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO app_state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


def get_state(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


SOURCE_STATUS_KEY = "source_status"


def mask_url(url: str) -> str:
    """Redact credentials and query parameters for logs and status messages."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return "<unparseable-url>"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path or "", "", ""))


def url_fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _resolve_m3u_url() -> str:
    m3u_url = settings.effective_value("M3U_URL")
    if not m3u_url:
        config_path = APP_DIR / "config.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                m3u_url = (config.get("m3u_url") or "").strip()
            except (json.JSONDecodeError, OSError):
                pass
    return m3u_url


def check_source(url: str, timeout: int = 30) -> dict[str, Any]:
    """Fetch and validate the M3U source without touching the library."""
    result: dict[str, Any] = {"state": "unknown", "checked_at": now_iso(), "entry_count": None, "detail": None}
    try:
        raw_text = fetch_text(url, None, timeout, True)
    except urllib.error.HTTPError as exc:
        result["state"] = "auth_failed" if exc.code in (401, 403) else "unreachable"
        result["detail"] = f"HTTP {exc.code}"
        return result
    except Exception as exc:
        result["state"] = "unreachable"
        result["detail"] = type(exc).__name__
        return result
    parsed = parse_m3u(raw_text)
    if parsed:
        result["state"] = "ok"
        result["entry_count"] = len(parsed)
    elif "#EXTM3U" in raw_text[:4096].upper() or "#EXTINF" in raw_text:
        result["state"] = "empty"
    else:
        result["state"] = "invalid"
    return result


def record_source_status(url: str, result: dict[str, Any]) -> None:
    stored = dict(result)
    stored["fingerprint"] = url_fingerprint(url)
    with db() as conn:
        set_state(conn, SOURCE_STATUS_KEY, stored)


# ---------------------------------------------------------------------------
# Movie version grouping: the same film often appears several times in a
# source playlist (German / Multi-Subs / 4K). These helpers derive a stable
# group key, a quality rank (for the representative card) and human-friendly
# version tags, so the UI can show one card per title with a version picker.
# ---------------------------------------------------------------------------

_GROUP_BRACKETS = re.compile(r"\[[^\]]*\]")
_GROUP_QUALITY_WORDS = re.compile(r"\b(4k|uhd|2160p|1080p|720p|fhd|hd)\b", re.IGNORECASE)
_GROUP_LANG_WORDS = re.compile(
    r"\b(german|deutsch|englisch|english|ger|eng|de|en|subbed|sub|dl)\b"
    r"|multi[-\s]?(subs?|audio|lang)?\b|untertitel(t)?",
    re.IGNORECASE,
)


def movie_group_key(source_title: str, metadata_title: str | None) -> str:
    """Stable identity for one film: TMDB title if known, else the source
    title with version markers ([DE], [Multi-Subs], 4K, year brackets, …)
    stripped."""
    if metadata_title and metadata_title.strip():
        return "meta:" + re.sub(r"\s+", " ", metadata_title.strip().lower())
    title = _GROUP_BRACKETS.sub(" ", source_title or "")
    title = _GROUP_QUALITY_WORDS.sub(" ", title)
    title = _GROUP_LANG_WORDS.sub(" ", title)
    title = re.sub(r"[^a-z0-9]+", " ", title.lower())
    return "src:" + title.strip()


def movie_quality_rank(source_title: str) -> int:
    text = source_title or ""
    if re.search(r"\b(4k|uhd|2160p)\b", text, re.IGNORECASE):
        return 3
    if re.search(r"\b(1080p|fhd)\b", text, re.IGNORECASE):
        return 2
    if re.search(r"\b720p\b", text, re.IGNORECASE):
        return 1
    return 0


_TAG_QUALITY = (
    (re.compile(r"\b(4k|uhd|2160p)\b", re.IGNORECASE), "4K"),
    (re.compile(r"\b(1080p|fhd)\b", re.IGNORECASE), "1080p"),
    (re.compile(r"\b720p\b", re.IGNORECASE), "720p"),
)
_TAG_LANG = (
    (re.compile(r"\b(german|deutsch|ger)\b|\[\s*de\s*\]", re.IGNORECASE), "DE"),
    (re.compile(r"\b(english|englisch|eng)\b|\[\s*en\s*\]", re.IGNORECASE), "EN"),
    (re.compile(r"multi\b|multi[-\s](subs?|audio|lang)|multi subtitles", re.IGNORECASE), "Multi"),
)
_TAG_SUBS = re.compile(r"\b(subbed|subs?|untertitel(t)?)\b", re.IGNORECASE)


def version_tags(source_title: str, group_name: str) -> list[str]:
    """Human-friendly version badges, e.g. ["4K", "Multi"] or ["DE"]."""
    text = f"{source_title or ''} {group_name or ''}"
    tags: list[str] = []
    for rx, label in _TAG_QUALITY:
        if rx.search(text):
            tags.append(label)
            break
    for rx, label in _TAG_LANG:
        if rx.search(text):
            tags.append(label)
    if "Multi" not in tags and _TAG_SUBS.search(text):
        tags.append("Subs")
    return tags


_FLAG_DE = 1
_FLAG_MULTI = 2
_FLAG_EN = 4
_FLAG_SUBS = 8
_FLAG_4K = 16


def version_flags(source_title: str, group_name: str) -> int:
    """Bitmask of version attributes for fast SQL filtering:
    DE=1, Multi=2, EN=4, Subs=8, 4K=16."""
    text = f"{source_title or ''} {group_name or ''}"
    flags = 0
    if re.search(r"\b(4k|uhd|2160p)\b", text, re.IGNORECASE):
        flags |= _FLAG_4K
    if any(rx.search(text) for rx, label in _TAG_LANG if label == "DE"):
        flags |= _FLAG_DE
    if any(rx.search(text) for rx, label in _TAG_LANG if label == "EN"):
        flags |= _FLAG_EN
    if any(rx.search(text) for rx, label in _TAG_LANG if label == "Multi"):
        flags |= _FLAG_MULTI
    elif _TAG_SUBS.search(text):
        flags |= _FLAG_SUBS
    return flags


def movie_has_tag(source_title: str, group_name: str, tag: str) -> int:
    """1 if the version tags for this row contain ``tag`` (case-insensitive).

    Registered as a SQLite function so language/quality filters can run
    inside the query.
    """
    wanted = (tag or "").strip().lower()
    if not wanted:
        return 1
    return 1 if any(t.lower() == wanted for t in version_tags(source_title, group_name)) else 0


def read_source_status(url: str) -> dict[str, Any]:
    """Latest check for the CURRENT url only; a new/changed URL starts as unknown."""
    if not url:
        return {"state": "not_configured", "checked_at": None, "entry_count": None, "detail": None}
    with db() as conn:
        stored = get_state(conn, SOURCE_STATUS_KEY)
    if not isinstance(stored, dict) or stored.get("fingerprint") != url_fingerprint(url):
        return {"state": "unknown", "checked_at": None, "entry_count": None, "detail": None}
    return {key: stored.get(key) for key in ("state", "checked_at", "entry_count", "detail")}


# ---------------------------------------------------------------------------
# Admin authentication and settings
# ---------------------------------------------------------------------------


@app.get("/api/auth/status")
async def auth_status(request: Request) -> dict[str, Any]:
    """Public: is a password configured, and is this client logged in?"""
    session = session_from_request(request)
    return {
        "setup_required": not settings.has_admin_password(),
        "authenticated": session is not None,
        "csrf": session.get("csrf") if session else None,
    }


def _reject_cross_origin_login(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.strip():
        try:
            parsed = urllib.parse.urlparse(origin)
        except ValueError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid Origin header")
        if parsed.netloc != request.headers.get("host"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Cross-origin login rejected")


@app.post("/api/auth/setup")
async def auth_setup(request: Request, response: Response, body: dict[str, Any]) -> dict[str, Any]:
    """First-run: choose the admin password (only while none is set)."""
    _reject_cross_origin_login(request)
    if settings.has_admin_password():
        raise HTTPException(status.HTTP_409_CONFLICT, "Admin password is already configured")
    password = str(body.get("password") or "")
    try:
        settings.set_admin_password(password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    csrf = _set_session_cookie(response)
    return {"ok": True, "csrf": csrf}


@app.post("/api/auth/login")
async def auth_login(request: Request, response: Response, body: dict[str, Any]) -> dict[str, Any]:
    _reject_cross_origin_login(request)
    client_host = request.client.host if request.client else "unknown"
    if _login_throttled(client_host):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts, try again shortly")
    password = str(body.get("password") or "")
    if not settings.verify_admin_password(password):
        _record_login_failure(client_host)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid password")
    _clear_login_failures(client_host)
    csrf = _set_session_cookie(response)
    return {"ok": True, "csrf": csrf}


@app.post("/api/auth/logout")
async def auth_logout(response: Response) -> dict[str, bool]:
    _clear_session_cookie(response)
    return {"ok": True}


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return value[0] + "•" * (len(value) - 2) + value[-1]


@app.get("/api/admin/settings")
async def admin_get_settings(
    request: Request,
    reveal: bool = Query(default=False),
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    """Return the effective settings.

    Secrets are never returned as ``value`` (``null`` unless revealed);
    ``masked`` is display-only and must never be submitted back — the
    settings form treats an empty field as "leave unchanged".
    """
    session = session_from_request(request)
    csrf = session.get("csrf") if session else None
    keys: dict[str, Any] = {}
    for key in settings.UI_KEYS:
        value = settings.effective_value(key)
        is_secret = key != "METADATA_LANGUAGE"
        keys[key] = {
            "set": bool(value),
            "value": value if (not is_secret or (reveal and value)) else None,
            "masked": _mask(value),
        }
    return {"keys": keys, "csrf": csrf}


@app.put("/api/admin/settings")
async def admin_put_settings(
    request: Request,
    body: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, bool]:
    """Apply settings updates.

    Keys absent from the body or sent empty are left unchanged; only
    non-empty values are written. To remove a value, pass its key in the
    ``clear`` array. This prevents accidentally persisting display-only
    masked placeholders (``h•••…n``) as real values.

    Updates land in ``DATA_DIR/.env`` (mode 0600) and the running process,
    so they take effect immediately; the systemd units pick them up at the
    next restart via the ``EnvironmentFile``.
    """
    updates: dict[str, str | None] = {}
    for key in settings.UI_KEYS:
        if key in (body.get("clear") or []):
            updates[key] = None
            continue
        if key not in body:
            continue
        raw = body.get(key)
        value = str(raw).strip() if raw is not None else ""
        if not value:
            continue
        try:
            value.encode("latin-1")
        except UnicodeEncodeError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{key} contains characters that cannot be sent in HTTP headers",
            )
        updates[key] = value
    old_m3u_url = settings.effective_value("M3U_URL")
    settings.apply_updates(updates)
    new_m3u_url = updates.get("M3U_URL", old_m3u_url) or ""
    if new_m3u_url != old_m3u_url:
        # A new or cleared source must not inherit the previous source's result.
        init_db()
        with db() as conn:
            conn.execute("DELETE FROM app_state WHERE key = ?", (SOURCE_STATUS_KEY,))
    return {"ok": True}


@app.post("/api/admin/settings/api-key/regenerate")
async def admin_regenerate_api_key(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """Generate a fresh API key for external clients (e.g. the refresh timer)."""
    import secrets as secrets_mod

    key = secrets_mod.token_hex(32)
    settings.apply_updates({"API_KEY": key})
    return {"ok": True, "api_key": key}


@app.post("/api/admin/settings/password")
async def admin_change_password(
    body: dict[str, Any], _: dict[str, Any] = Depends(require_admin)
) -> dict[str, bool]:
    current = str(body.get("current") or "")
    new = str(body.get("new") or "")
    if not settings.verify_admin_password(current):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect")
    try:
        settings.set_admin_password(new)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return {"ok": True}


@app.get("/api/source-status")
async def api_source_status() -> dict[str, Any]:
    """Public: last known check result for the configured M3U source."""
    init_db()
    return read_source_status(_resolve_m3u_url())


# ---------------------------------------------------------------------------
# TMDB image proxy: posters are served same-origin so the browser never talks
# to image.tmdb.org directly. This sidesteps client-side rate limiting,
# DNS/ad blocking and hidden-tab throttling, and lets the server cache each
# image once for all clients.
# ---------------------------------------------------------------------------

POSTER_PROXY_HOSTS = frozenset({"image.tmdb.org"})
_POSTER_CACHE_MAX = 500
_poster_cache: dict[str, tuple[bytes, str]] = {}


def fetch_image_bytes(url: str, timeout: int = 15) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "image/jpeg").split(";")[0].strip() or "image/jpeg"
        return response.read(), content_type


@app.get("/api/poster")
async def poster_proxy(u: str = Query(..., min_length=1)) -> Response:
    """Proxy (and cache) an image.tmdb.org poster; all other hosts are rejected."""
    parsed = urllib.parse.urlparse(u)
    if parsed.scheme != "https" or parsed.hostname not in POSTER_PROXY_HOSTS:
        raise HTTPException(400, "only https://image.tmdb.org/ images can be proxied")
    cached = _poster_cache.get(u)
    if cached is None:
        try:
            body, content_type = await asyncio.to_thread(fetch_image_bytes, u)
        except Exception:
            raise HTTPException(502, "upstream image fetch failed")
        if len(_poster_cache) >= _POSTER_CACHE_MAX:
            _poster_cache.pop(next(iter(_poster_cache)))
        _poster_cache[u] = (body, content_type)
        cached = (body, content_type)
    return Response(content=cached[0], media_type=cached[1], headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/admin/source-status/check")
async def admin_check_source(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """Admin: check the M3U source now without touching the library."""
    init_db()
    url = _resolve_m3u_url()
    if not url:
        raise HTTPException(400, "M3U_URL is not configured")
    result = await asyncio.to_thread(check_source, url, 30)
    record_source_status(url, result)
    return read_source_status(url)


@app.get("/settings", response_class=HTMLResponse)
def settings_page() -> str:
    return SETTINGS_HTML


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return LIBRARY_HTML


@app.get("/series/{series_id}", response_class=HTMLResponse)
def series_page(series_id: str) -> str:
    return LIBRARY_HTML


@app.get("/api/items")
async def list_items(
    q: str = "",
    kind: str = "",
    group: str = "",
    section: str = "all",
    sort: str = "added",
    new_window: str = "refresh",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    lang: str = "",
    uhd: int = 0,
) -> dict[str, Any]:
    await async_init_db()
    async with read_db() as conn:
        # Python-backed SQL helpers for movie version grouping (see below).
        await conn.create_function("movie_group_key", 2, movie_group_key)
        await conn.create_function("movie_quality_rank", 1, movie_quality_rank)
        await conn.create_function("version_flags", 2, version_flags)
        await conn.create_function("movie_has_tag", 3, movie_has_tag)
        last_refresh = await async_get_state(conn, "last_refresh")
        new_since = await async_new_since_for_window(conn, new_window)
        trending_ids = await async_trending_library_ids(conn)
        popular_ids = await async_popular_library_ids(conn)
        upcoming_snapshot = await async_get_upcoming_snapshot(conn)

        # Unified view: one row per non-series item and one row per series group.
        # Series aggregates are pre-computed in series_groups for speed.
        # Movies carrying the same group key (same title in different language /
        # quality variants) collapse into one card via the dedup window below.
        #
        # The grouping chain is materialised ONCE per request into TEMP tables:
        # the Python-backed key/flag helpers are far too expensive to re-run for
        # the ~10 count queries below (each would re-evaluate the whole CTE).
        cte_params = [new_since, new_since]
        await conn.execute("DROP TABLE IF EXISTS temp.temp_keyed_items")
        await conn.execute("DROP TABLE IF EXISTS temp.temp_visible_items")
        await conn.execute(f"""
            CREATE TEMP TABLE temp_keyed_items AS
            WITH base_items AS (
          SELECT
            items.id,
            COALESCE(metadata.title, items.title) AS title,
            items.title AS source_title,
            items.group_name,
            items.kind,
            items.logo,
            items.stream_url,
            items.added_at,
            items.last_seen_at,
            items.is_favorite,
            items.is_watched,
            items.watched_at,
            CASE WHEN items.added_at >= ? THEN 1 ELSE 0 END AS is_new,
            metadata.title AS metadata_title,
            metadata.release_date,
            metadata.rating,
            metadata.description,
            metadata.poster_url,
            NULL AS episode_count,
            NULL AS season_count,
            NULL AS watched_episode_count
          FROM items
          LEFT JOIN metadata ON metadata.item_id = items.id
          WHERE items.available = 1 AND items.kind != 'series'
          UNION ALL
          SELECT
            series_groups.id,
            series_groups.title,
            series_groups.title AS source_title,
            series_groups.group_name,
            'series' AS kind,
            series_groups.poster_url AS logo,
            '' AS stream_url,
            series_groups.latest_added_at AS added_at,
            '' AS last_seen_at,
            series_groups.is_favorite,
            CASE WHEN series_groups.episode_count > 0 AND series_groups.watched_episode_count >= series_groups.episode_count THEN 1 ELSE 0 END AS is_watched,
            series_groups.watched_at,
            CASE WHEN series_groups.latest_added_at >= ? THEN 1 ELSE 0 END AS is_new,
            NULL AS metadata_title,
            series_groups.release_date,
            series_groups.rating,
            series_groups.description,
            series_groups.poster_url,
            series_groups.episode_count,
            series_groups.season_count,
            series_groups.watched_episode_count
          FROM series_groups
          WHERE series_groups.episode_count > 0
            )
            SELECT
              *,
              CASE WHEN kind = 'movie'
                THEN movie_group_key(source_title, metadata_title)
                ELSE 'id:' || id
              END AS movie_key,
              movie_quality_rank(source_title) AS qrank,
              version_flags(source_title, group_name) AS ver_flags
            FROM base_items
        """, cte_params)
        await conn.execute("""
            CREATE TEMP TABLE temp_visible_items AS
            SELECT
              *,
              ROW_NUMBER() OVER (
                PARTITION BY movie_key
                ORDER BY qrank DESC,
                         metadata_title IS NOT NULL DESC,
                         added_at DESC, id
              ) AS rn,
              COUNT(*) OVER (PARTITION BY movie_key) AS version_count,
              MAX(is_watched) OVER (PARTITION BY movie_key) AS group_is_watched,
              MAX(is_favorite) OVER (PARTITION BY movie_key) AS group_is_favorite,
              MAX(is_new) OVER (PARTITION BY movie_key) AS group_is_new
            FROM temp_keyed_items
        """)
        await conn.execute("CREATE INDEX temp_idx_keyed_movie_key ON temp_keyed_items(movie_key)")
        await conn.execute("CREATE INDEX temp_idx_visible_rn ON temp_visible_items(rn, movie_key)")

        async def _count_visible(where: str = "1 = 1", params: list[Any] | None = None) -> int:
            row = await (await conn.execute(
                f"SELECT COUNT(*) AS count FROM temp_visible_items WHERE rn = 1 AND ({where})",
                params or [],
            )).fetchone()
            return row["count"]

        if section == "upcoming":
            upcoming_items = upcoming_snapshot.get("items", [])
            if kind and kind != "movie":
                upcoming_items = []
            if q:
                like = q.strip().lower()
                upcoming_items = [
                    item for item in upcoming_items
                    if like in item["title"].lower() or like in item["group_name"].lower()
                ]
            if sort == "title":
                upcoming_items = sorted(upcoming_items, key=lambda item: item["title"].lower())
            elif sort == "rating":
                upcoming_items = sorted(upcoming_items, key=lambda item: float(item["rating"] or 0), reverse=True)
            else:
                upcoming_items = sorted(upcoming_items, key=lambda item: item["release_date"] or "", reverse=True)
            total = await _count_visible()
            matched = len(upcoming_items)
            rows = upcoming_items[offset: offset + limit]
            groups = ["TMDB Upcoming"]
            kind_count_rows = await (await conn.execute(
                "SELECT kind, COUNT(*) AS count FROM temp_visible_items WHERE rn = 1 GROUP BY kind"
            )).fetchall()
            kind_counts = {row["kind"]: row["count"] for row in kind_count_rows}
            new_count = await _count_visible("group_is_new = 1")
            return {
                "items": rows,
                "total": total,
                "matched": matched,
                "limit": limit,
                "offset": offset,
                "groups": groups,
                "kind_counts": kind_counts,
                "last_refresh": last_refresh,
                "metadata_status": await async_metadata_warmup_status(conn),
                "section_counts": {
                    "all": total,
                    "favorites": await _count_visible("group_is_favorite = 1"),
                    "watched": await _count_visible("group_is_watched = 1"),
                    "continue": await _count_visible("kind = 'series' AND watched_episode_count > 0 AND watched_episode_count < episode_count"),
                    "new": new_count,
                    "trending": len(trending_ids["movie_ids"]),
                    "popular": len(popular_ids["movie_ids"]),
                    "upcoming": len(upcoming_snapshot.get("items", [])),
                },
            }

        clauses = ["1 = 1"]
        params: list[Any] = []
        if q:
            clauses.append(
                "EXISTS (SELECT 1 FROM temp_keyed_items k WHERE k.movie_key = temp_visible_items.movie_key"
                " AND (k.title LIKE ? OR k.source_title LIKE ? OR k.group_name LIKE ? OR k.metadata_title LIKE ?))"
            )
            like = f"%{q}%"
            params.extend([like, like, like, like])
        if kind:
            clauses.append("temp_visible_items.kind = ?")
            params.append(kind)
        if group:
            clauses.append(
                "EXISTS (SELECT 1 FROM temp_keyed_items k WHERE k.movie_key = temp_visible_items.movie_key AND k.group_name = ?)"
            )
            params.append(group)
        if lang:
            flag_bit = {"de": 1, "multi": 2, "en": 4}.get(lang.strip().lower())
            if flag_bit is None:
                raise HTTPException(400, "lang must be one of: de, multi, en")
            clauses.append(
                f"EXISTS (SELECT 1 FROM temp_keyed_items k WHERE k.movie_key = temp_visible_items.movie_key"
                f" AND (k.ver_flags & {flag_bit}) != 0)"
            )
        if uhd:
            clauses.append(
                "EXISTS (SELECT 1 FROM temp_keyed_items k WHERE k.movie_key = temp_visible_items.movie_key"
                " AND (k.ver_flags & 16) != 0)"
            )
        if section == "favorites":
            clauses.append("temp_visible_items.group_is_favorite = 1")
        elif section == "watched":
            clauses.append("temp_visible_items.group_is_watched = 1")
        elif section == "continue":
            clauses.append("temp_visible_items.kind = 'series' AND temp_visible_items.watched_episode_count > 0 AND temp_visible_items.watched_episode_count < temp_visible_items.episode_count")
        elif section == "new":
            clauses.append("temp_visible_items.group_is_new = 1")
        elif section == "trending":
            clauses.append("temp_visible_items.kind = 'movie'")
            if trending_ids["movie_ids"]:
                placeholders = ",".join("?" for _ in trending_ids["movie_ids"])
                clauses.append(
                    f"temp_visible_items.movie_key IN (SELECT movie_key FROM temp_keyed_items WHERE id IN ({placeholders}))"
                )
                params.extend(sorted(trending_ids["movie_ids"]))
            else:
                clauses.append("1 = 0")
        elif section == "popular":
            clauses.append("temp_visible_items.kind = 'movie'")
            if popular_ids["movie_ids"]:
                placeholders = ",".join("?" for _ in popular_ids["movie_ids"])
                clauses.append(
                    f"temp_visible_items.movie_key IN (SELECT movie_key FROM temp_keyed_items WHERE id IN ({placeholders}))"
                )
                params.extend(sorted(popular_ids["movie_ids"]))
            else:
                clauses.append("1 = 0")
        where = " AND ".join(clauses)

        order_by = "temp_visible_items.group_is_favorite DESC, temp_visible_items.added_at DESC, temp_visible_items.title COLLATE NOCASE"
        if sort == "title":
            order_by = "temp_visible_items.group_is_favorite DESC, temp_visible_items.title COLLATE NOCASE"
        elif sort == "rating":
            order_by = "temp_visible_items.group_is_favorite DESC, COALESCE(temp_visible_items.rating, 0) DESC, temp_visible_items.title COLLATE NOCASE"
        elif sort == "release":
            order_by = "temp_visible_items.group_is_favorite DESC, COALESCE(temp_visible_items.release_date, '') DESC, temp_visible_items.title COLLATE NOCASE"
        elif sort == "new":
            order_by = "temp_visible_items.group_is_new DESC, temp_visible_items.added_at DESC, temp_visible_items.title COLLATE NOCASE"
        elif section == "continue":
            order_by = "temp_visible_items.group_is_favorite DESC, COALESCE(temp_visible_items.watched_at, '') DESC, temp_visible_items.title COLLATE NOCASE"
        elif section == "watched" or sort == "watched":
            order_by = "temp_visible_items.group_is_favorite DESC, COALESCE(temp_visible_items.watched_at, '') DESC, temp_visible_items.title COLLATE NOCASE"

        total = await _count_visible()
        matched = await _count_visible(where, params)
        rows = await (await conn.execute(
            f"""
            SELECT
              id,
              title,
              source_title,
              group_name,
              kind,
              logo,
              stream_url,
              added_at,
              last_seen_at,
              group_is_favorite AS is_favorite,
              group_is_watched AS is_watched,
              watched_at,
              group_is_new AS is_new,
              metadata_title,
              release_date,
              rating,
              description,
              poster_url,
              episode_count,
              season_count,
              watched_episode_count,
              movie_key,
              version_count
            FROM temp_visible_items
            WHERE rn = 1 AND ({where})
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )).fetchall()
        items = [dict(row) for row in rows]

        # Version lists for every movie on this page (id, title, group, tags,
        # per-version watch/favorite state) power the badges and picker UI.
        page_keys = [item["movie_key"] for item in items if item["kind"] == "movie"]
        versions_map: dict[str, list[dict[str, Any]]] = {}
        if page_keys:
            key_placeholders = ",".join("?" for _ in page_keys)
            version_rows = await (await conn.execute(
                f"""
                SELECT id, source_title, group_name, movie_key, is_watched, is_favorite
                FROM temp_keyed_items
                WHERE movie_key IN ({key_placeholders})
                ORDER BY movie_quality_rank(source_title) DESC, source_title COLLATE NOCASE
                """,
                [*page_keys],
            )).fetchall()
            for vrow in version_rows:
                versions_map.setdefault(vrow["movie_key"], []).append({
                    "id": vrow["id"],
                    "title": vrow["source_title"],
                    "group_name": vrow["group_name"],
                    "tags": version_tags(vrow["source_title"], vrow["group_name"]),
                    "is_watched": vrow["is_watched"],
                    "is_favorite": vrow["is_favorite"],
                })
        for item in items:
            item["versions"] = versions_map.get(item["movie_key"], []) if item["kind"] == "movie" else []
            item.pop("movie_key", None)
        group_rows = await (await conn.execute(
            "SELECT DISTINCT group_name FROM temp_visible_items WHERE rn = 1 AND group_name != 'Uncategorized' AND group_name != '' ORDER BY group_name",
        )).fetchall()
        groups = [row["group_name"] for row in group_rows]
        kind_count_rows = await (await conn.execute(
            "SELECT kind, COUNT(*) AS count FROM temp_visible_items WHERE rn = 1 GROUP BY kind",
        )).fetchall()
        kind_counts = {row["kind"]: row["count"] for row in kind_count_rows}
        new_count = await _count_visible("group_is_new = 1")
        return {
            "items": items,
            "total": total,
            "matched": matched,
            "limit": limit,
            "offset": offset,
            "groups": groups,
            "kind_counts": kind_counts,
            "last_refresh": last_refresh,
            "metadata_status": await async_metadata_warmup_status(conn),
            "section_counts": {
                "all": total,
                "favorites": await _count_visible("group_is_favorite = 1"),
                "watched": await _count_visible("group_is_watched = 1"),
                "continue": await _count_visible("kind = 'series' AND watched_episode_count > 0 AND watched_episode_count < episode_count"),
                "new": new_count,
                "trending": await _count_visible(
                    f"kind = 'movie' AND movie_key IN (SELECT movie_key FROM temp_keyed_items WHERE id IN ({','.join('?' for _ in sorted(trending_ids['movie_ids'])) or 'NULL'}))",
                    sorted(trending_ids["movie_ids"]),
                ) if trending_ids["movie_ids"] else 0,
                "popular": await _count_visible(
                    f"kind = 'movie' AND movie_key IN (SELECT movie_key FROM temp_keyed_items WHERE id IN ({','.join('?' for _ in sorted(popular_ids['movie_ids'])) or 'NULL'}))",
                    sorted(popular_ids["movie_ids"]),
                ) if popular_ids["movie_ids"] else 0,
                "upcoming": len(upcoming_snapshot.get("items", [])),
            },
        }


STATE_SNAPSHOT_VERSION = 1
STATE_SNAPSHOT_KEEP = 30


def state_snapshot_dir() -> Path:
    return Path(DATA_DIR) / "state-snapshots"


def write_state_snapshot() -> dict[str, Any]:
    """Persist watched/favorite state to a JSON snapshot.

    Runs after every successful refresh so a provider-side rename or a bad
    migration can never silently wipe viewing state again. Timestamped file
    plus a latest.json copy; older snapshots are pruned.
    """
    snap_dir = state_snapshot_dir()
    snap_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        items = {
            row["id"]: {"w": row["is_watched"], "f": row["is_favorite"], "at": row["watched_at"]}
            for row in conn.execute("SELECT id, is_watched, is_favorite, watched_at FROM items")
        }
        series = {
            row["id"]: {"w": row["is_watched"], "f": row["is_favorite"], "at": row["watched_at"]}
            for row in conn.execute("SELECT id, is_watched, is_favorite, watched_at FROM series_groups")
        }
    finally:
        conn.close()
    payload = {
        "version": STATE_SNAPSHOT_VERSION,
        "created_at": now_iso(),
        "items": items,
        "series_groups": series,
    }
    text = json.dumps(payload, separators=(",", ":"))
    stamp = re.sub(r"[^0-9]", "", payload["created_at"])[:14]
    (snap_dir / f"snapshot-{stamp}.json").write_text(text, encoding="utf-8")
    (snap_dir / "latest.json").write_text(text, encoding="utf-8")
    snapshots = sorted(snap_dir.glob("snapshot-*.json"), key=lambda p: p.name)
    for old in snapshots[:-STATE_SNAPSHOT_KEEP]:
        old.unlink(missing_ok=True)
    return {"items": len(items), "series_groups": len(series)}


@app.post("/api/refresh", dependencies=[Depends(require_api_key)])
async def refresh() -> dict[str, Any]:
    await async_init_db()
    m3u_url = _resolve_m3u_url()
    if not m3u_url:
        raise HTTPException(400, "M3U_URL is missing in /var/lib/apps/m3u-library/.env and config.json")
    try:
        raw_text = await asyncio.to_thread(fetch_text, m3u_url, None, 120, True)
    except urllib.error.HTTPError as exc:
        state = "auth_failed" if exc.code in (401, 403) else "unreachable"
        record_source_status(m3u_url, {"state": state, "checked_at": now_iso(), "entry_count": None, "detail": f"HTTP {exc.code}"})
        raise HTTPException(502, f"M3U source request failed (HTTP {exc.code}); the existing library was left unchanged")
    except Exception as exc:
        record_source_status(m3u_url, {"state": "unreachable", "checked_at": now_iso(), "entry_count": None, "detail": type(exc).__name__})
        raise HTTPException(502, f"M3U source is unreachable ({type(exc).__name__}); the existing library was left unchanged")
    parsed = await asyncio.to_thread(parse_m3u, raw_text)
    if not parsed:
        looks_like_m3u = "#EXTM3U" in raw_text[:4096].upper() or "#EXTINF" in raw_text
        state = "empty" if looks_like_m3u else "invalid"
        record_source_status(m3u_url, {"state": state, "checked_at": now_iso(), "entry_count": 0 if state == "empty" else None, "detail": None})
        if state == "empty":
            raise HTTPException(422, "M3U source returned a valid but empty playlist; the existing library was left unchanged")
        raise HTTPException(422, "M3U source returned no valid M3U playlist; the existing library was left unchanged")
    record_source_status(m3u_url, {"state": "ok", "checked_at": now_iso(), "entry_count": len(parsed), "detail": None})
    # The provider playlist may list the same movie/episode twice (e.g. quality
    # variants). Item ids are content-derived, so duplicates share one id and
    # would violate the PRIMARY KEY on insert — keep the first occurrence.
    deduped: list[dict[str, Any]] = []
    _seen_ids: set[str] = set()
    for item in parsed:
        if item["id"] in _seen_ids:
            continue
        _seen_ids.add(item["id"])
        deduped.append(item)
    parsed = deduped
    print(f"M3U parse: #EXTINF={raw_text.count('#EXTINF')}, items={len(parsed)}")
    seen_ids = {item["id"] for item in parsed}
    timestamp = now_iso()

    async with read_db() as conn:
        existing_rows = await (await conn.execute(
            "SELECT id, stream_url, logo, group_name, title, added_at, first_seen_at, available, series_id FROM items"
        )).fetchall()
    existing = {row["id"]: row for row in existing_rows}

    to_insert: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []
    touched_series_ids: set[str] = set()

    for item in parsed:
        previous = existing.get(item["id"])
        if not previous:
            to_insert.append({
                **item,
                "added_at": timestamp,
                "first_seen_at": timestamp,
                "last_seen_at": timestamp,
                "available": 1,
                "is_watched": 0,
                "watched_at": None,
                "is_favorite": 0,
            })
        elif (
            previous["available"] == 0
            or previous["stream_url"] != item["stream_url"]
            or previous["logo"] != item["logo"]
            or previous["group_name"] != item["group_name"]
            or previous["title"] != item["title"]
        ):
            to_update.append({
                **item,
                "added_at": previous["added_at"],
                "first_seen_at": previous["first_seen_at"],
                "last_seen_at": timestamp,
            })
        if item["kind"] == "series" and item["series_id"]:
            touched_series_ids.add(item["series_id"])

    to_remove_ids = set(existing.keys()) - seen_ids
    for removed_id in to_remove_ids:
        row = existing[removed_id]
        if row["series_id"]:
            touched_series_ids.add(row["series_id"])

    async def _apply_refresh(conn: aiosqlite.Connection) -> tuple[int, int, int]:
        inserted = 0
        updated = 0
        removed = 0

        insert_sql = """
        INSERT INTO items(
          id, title, group_name, kind, logo, stream_url, added_at, first_seen_at, last_seen_at, available,
          is_watched, watched_at, is_favorite,
          series_id, series_title, season_number, episode_number, episode_label
        )
        VALUES(
          :id, :title, :group_name, :kind, :logo, :stream_url, :added_at, :first_seen_at, :last_seen_at, :available,
          :is_watched, :watched_at, :is_favorite,
          :series_id, :series_title, :season_number, :episode_number, :episode_label
        )
        """
        CHUNK = 5000
        for i in range(0, len(to_insert), CHUNK):
            await conn.executemany(insert_sql, to_insert[i : i + CHUNK])
            inserted += len(to_insert[i : i + CHUNK])

        update_sql = """
        UPDATE items
        SET stream_url = :stream_url,
            logo = :logo,
            group_name = :group_name,
            title = :title,
            last_seen_at = :last_seen_at,
            available = 1
        WHERE id = :id
        """
        for i in range(0, len(to_update), CHUNK):
            await conn.executemany(update_sql, to_update[i : i + CHUNK])
            updated += len(to_update[i : i + CHUNK])

        if to_remove_ids:
            placeholders = ",".join("?" for _ in to_remove_ids)
            await conn.execute(f"UPDATE items SET available = 0 WHERE id IN ({placeholders})", tuple(to_remove_ids))
            removed = len(to_remove_ids)

        for item in parsed:
            if item["kind"] == "series" and item["series_id"] and item["series_title"]:
                await conn.execute(
                    """
                    INSERT INTO series_groups(id, title, query)
                    VALUES(?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET title = excluded.title, query = excluded.query
                    """,
                    (item["series_id"], item["series_title"], clean_metadata_query(item["series_title"], "series")),
                )

        for series_id in touched_series_ids:
            await _async_update_series_group_stats(conn, series_id)

        await async_set_state(conn, "last_refresh", timestamp)
        await async_set_state(conn, "last_new_count", inserted)
        return inserted, updated, removed

    added, updated, removed = await write_db(_apply_refresh)
    try:
        snapshot_info = await asyncio.to_thread(write_state_snapshot)
        print(f"State snapshot written: {snapshot_info['items']} items, {snapshot_info['series_groups']} series groups")
    except Exception as exc:
        print(f"State snapshot failed (non-fatal): {exc}")
    run_metadata_warmup(last_refresh=timestamp)
    return {"ok": True, "added": added, "updated": updated, "removed": removed, "last_refresh": timestamp}


@app.get("/api/series")
async def list_series(
    q: str = "",
    section: str = "all",
    sort: str = "title",
    new_window: str = "refresh",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    lang: str = "",
    uhd: int = 0,
) -> dict[str, Any]:
    await async_init_db()
    async with read_db() as conn:
        await conn.create_function("movie_has_tag", 3, movie_has_tag)
        last_refresh = await async_get_state(conn, "last_refresh")
        new_since = await async_new_since_for_window(conn, new_window)
        trending_ids = await async_trending_library_ids(conn)
        popular_ids = await async_popular_library_ids(conn)
        base_clause = "episode_count > 0"
        clauses = [base_clause]
        params: list[Any] = []
        if q:
            clauses.append("(title LIKE ?)")
            like = f"%{q}%"
            params.append(like)
        if lang:
            clauses.append("movie_has_tag(title, group_name, ?) = 1")
            params.append(lang)
        if uhd:
            clauses.append("movie_has_tag(title, group_name, '4K') = 1")
        if section == "favorites":
            clauses.append("is_favorite = 1")
        elif section == "watched":
            clauses.append("episode_count > 0 AND watched_episode_count >= episode_count")
        elif section == "continue":
            clauses.append("watched_episode_count > 0 AND watched_episode_count < episode_count")
        elif section == "new":
            clauses.append("latest_added_at >= ?")
            params.append(new_since)
        elif section == "trending":
            if trending_ids["series_ids"]:
                placeholders = ",".join("?" for _ in trending_ids["series_ids"])
                clauses.append(f"id IN ({placeholders})")
                params.extend(sorted(trending_ids["series_ids"]))
            else:
                clauses.append("1 = 0")
        elif section == "popular":
            if popular_ids["series_ids"]:
                placeholders = ",".join("?" for _ in popular_ids["series_ids"])
                clauses.append(f"id IN ({placeholders})")
                params.extend(sorted(popular_ids["series_ids"]))
            else:
                clauses.append("1 = 0")
        elif section == "upcoming":
            clauses.append("1 = 0")
        where = " AND ".join(clauses)
        order_by = "title COLLATE NOCASE"
        if sort == "rating":
            order_by = "COALESCE(rating, 0) DESC, title COLLATE NOCASE"
        elif sort == "release":
            order_by = "COALESCE(release_date, '') DESC, title COLLATE NOCASE"
        elif sort == "new":
            order_by = "CASE WHEN latest_added_at >= ? THEN 1 ELSE 0 END DESC, latest_added_at DESC, title COLLATE NOCASE"
        elif section == "continue":
            order_by = "COALESCE(watched_at, '') DESC, title COLLATE NOCASE"
        elif section == "watched" or sort == "watched":
            order_by = "is_favorite DESC, COALESCE(watched_at, '') DESC, title COLLATE NOCASE"

        total = (await (await conn.execute("SELECT COUNT(*) AS count FROM series_groups")).fetchone())["count"]
        matched = (await (await conn.execute(
            f"SELECT COUNT(*) AS count FROM series_groups WHERE {where}",
            params,
        )).fetchone())["count"]
        order_params = [new_since] if sort == "new" else []
        rows = await (await conn.execute(
            f"""
            SELECT
              id,
              'series' AS kind,
              title,
              release_date,
              rating,
              description,
              poster_url,
              provider_url,
              is_favorite,
              CASE WHEN is_watched = 1 OR watched_episode_count > 0 THEN 1 ELSE 0 END AS is_watched,
              episode_count,
              season_count,
              watched_episode_count,
              latest_added_at,
              watched_at AS latest_watched_at,
              CASE WHEN latest_added_at >= ? THEN 1 ELSE 0 END AS is_new
            FROM series_groups
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            [new_since, *order_params, *params, limit, offset],
        )).fetchall()
        section_counts = {
            "all": total,
            "new": (await (await conn.execute(
                "SELECT COUNT(*) AS count FROM series_groups WHERE episode_count > 0 AND latest_added_at >= ?",
                (new_since,),
            )).fetchone())["count"],
            "favorites": (await (await conn.execute("SELECT COUNT(*) AS count FROM series_groups WHERE is_favorite = 1")).fetchone())["count"],
            "watched": (await (await conn.execute(
                "SELECT COUNT(*) AS count FROM series_groups WHERE episode_count > 0 AND watched_episode_count >= episode_count"
            )).fetchone())["count"],
            "continue": (await (await conn.execute(
                "SELECT COUNT(*) AS count FROM series_groups WHERE episode_count > 0 AND watched_episode_count > 0 AND watched_episode_count < episode_count"
            )).fetchone())["count"],
            "trending": len(trending_ids["series_ids"]),
            "popular": len(popular_ids["series_ids"]),
            "upcoming": 0,
        }
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "matched": matched,
            "limit": limit,
            "offset": offset,
            "last_refresh": last_refresh,
            "section_counts": section_counts,
            "metadata_status": await async_metadata_warmup_status(conn),
        }


@app.get("/api/series/{series_id}")
async def series_detail(
    series_id: str,
    new_window: str = "refresh",
) -> dict[str, Any]:
    await async_init_db()
    async with read_db() as conn:
        series_row = await (await conn.execute("SELECT * FROM series_groups WHERE id = ?", (series_id,))).fetchone()
        if not series_row:
            raise HTTPException(404, "Series not found")
        try:
            series_data = await async_ensure_series_group_metadata(conn, series_row)
        except Exception:
            series_data = dict(series_row)
        new_since = await async_new_since_for_window(conn, new_window)
        episode_rows = await (await conn.execute(
            """
            SELECT id, title, episode_label, season_number, episode_number, stream_url, added_at, is_watched,
                   CASE WHEN added_at >= ? THEN 1 ELSE 0 END AS is_new
            FROM items
            WHERE available = 1 AND series_id = ?
            ORDER BY COALESCE(season_number, 0), COALESCE(episode_number, 0), title COLLATE NOCASE
            """,
            (new_since, series_id),
        )).fetchall()
        episodes = [dict(row) for row in episode_rows]
        seasons: dict[str, list[dict[str, Any]]] = {}
        for episode in episodes:
            season_label = f"Season {episode['season_number']}" if episode["season_number"] else "Episodes"
            seasons.setdefault(season_label, []).append(episode)
        return {"series": series_data, "seasons": seasons, "episode_count": len(episodes)}


def clean_metadata_query(title: str, kind: str) -> str:
    query = title
    if kind == "series":
        query = re.sub(r"\bS\d{1,2}\s*E\d{1,3}\b.*$", "", query, flags=re.I)
        query = re.sub(r"\b\d{1,2}x\d{1,3}\b.*$", "", query, flags=re.I)
    query = re.sub(r"\[[^\]]*\]", " ", query)
    query = re.sub(r"\b(4k|uhd|fhd|hd|multi-subs|multi subs|subbed|dubbed)\b", " ", query, flags=re.I)
    # Strip release-year markers so they don't break TMDB search (the year is sent separately).
    query = re.sub(r"\s*[\[(](?:19|20)\d{2}[\])]\s*", " ", query)
    query = re.sub(r"\s+(?:19|20)\d{2}\s*$", "", query)
    return re.sub(r"\s+", " ", query).strip()


def title_year(title: str) -> str:
    match = re.search(r"[\[(]((?:19|20)\d{2})[\])]", title)
    return match.group(1) if match else ""


def fetch_tmdb_json(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    bearer = settings.effective_value("TMDB_BEARER_TOKEN")
    api_key = settings.effective_value("TMDB_API_KEY")
    if bearer.lower().startswith("bearer "):
        bearer = bearer[7:].strip()
    if not bearer and not api_key:
        raise HTTPException(400, "TMDB_BEARER_TOKEN or TMDB_API_KEY is missing")
    query_params = {key: str(value) for key, value in params.items() if value not in (None, "")}
    if api_key:
        query_params["api_key"] = api_key
    url = f"https://api.themoviedb.org/3/{endpoint}?{urllib.parse.urlencode(query_params)}"
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    return json.loads(fetch_text(url, headers=headers, timeout=30))


def get_tmdb_cache(conn: sqlite3.Connection, cache_key: str, max_age_hours: int = 6) -> dict[str, Any] | None:
    cache = get_state(conn, cache_key)
    if cache and cache.get("cached_at"):
        try:
            cached_at = datetime.fromisoformat(cache["cached_at"])
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            if cached_at >= datetime.now(timezone.utc) - timedelta(hours=max_age_hours):
                return cache
        except ValueError:
            pass
    return None


def build_tmdb_library_snapshot(movie_endpoint: str, series_endpoint: str, language: str) -> dict[str, Any]:
    movie_results = fetch_tmdb_json(movie_endpoint, {"language": language}).get("results") or []
    series_results = fetch_tmdb_json(series_endpoint, {"language": language}).get("results") or []
    return {
        "cached_at": now_iso(),
        "movies": [
            {
                "provider_id": str(result.get("id") or ""),
                "query": (clean_metadata_query(result.get("title") or "", "movie") or (result.get("title") or "")).lower(),
            }
            for result in movie_results
            if result.get("id") and result.get("title")
        ],
        "series": [
            {
                "query": (clean_metadata_query(result.get("name") or "", "series") or (result.get("name") or "")).lower(),
            }
            for result in series_results
            if result.get("name")
        ],
    }


def get_trending_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    cache = get_tmdb_cache(conn, "tmdb_trending_week_cache")
    if cache:
        return cache

    language = settings.effective_value("METADATA_LANGUAGE", "en-US")
    snapshot = build_tmdb_library_snapshot("trending/movie/week", "trending/tv/week", language)
    set_state(conn, "tmdb_trending_week_cache", snapshot)
    return snapshot


def get_popular_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    cache = get_tmdb_cache(conn, "tmdb_popular_cache")
    if cache:
        return cache

    language = settings.effective_value("METADATA_LANGUAGE", "en-US")
    snapshot = build_tmdb_library_snapshot("movie/popular", "tv/popular", language)
    set_state(conn, "tmdb_popular_cache", snapshot)
    return snapshot


def get_upcoming_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    cache = get_tmdb_cache(conn, "tmdb_upcoming_cache")
    if cache:
        return cache

    language = settings.effective_value("METADATA_LANGUAGE", "en-US")
    results = fetch_tmdb_json("movie/upcoming", {"language": language, "page": 1}).get("results") or []
    snapshot = {
        "cached_at": now_iso(),
        "items": [
            {
                "id": f"tmdb-upcoming-{result.get('id')}",
                "title": result.get("title") or "",
                "group_name": "TMDB Upcoming",
                "kind": "movie",
                "logo": "",
                "stream_url": "",
                "added_at": "",
                "last_seen_at": "",
                "is_favorite": 0,
                "is_watched": 0,
                "is_new": 0,
                "is_external": 1,
                "metadata_title": result.get("title") or "",
                "release_date": result.get("release_date") or "",
                "rating": result.get("vote_average"),
                "description": result.get("overview") or "",
                "poster_url": f"https://image.tmdb.org/t/p/w342{result['poster_path']}" if result.get("poster_path") else "",
                "provider_url": f"https://www.themoviedb.org/movie/{result.get('id') or ''}",
            }
            for result in results
            if result.get("id") and result.get("title")
        ],
    }
    set_state(conn, "tmdb_upcoming_cache", snapshot)
    return snapshot


def library_ids_for_snapshot(conn: sqlite3.Connection, snapshot: dict[str, Any]) -> dict[str, set[str]]:
    movie_provider_ids = {entry["provider_id"] for entry in snapshot.get("movies", []) if entry.get("provider_id")}
    movie_queries = {entry["query"] for entry in snapshot.get("movies", []) if entry.get("query")}
    series_queries = {entry["query"] for entry in snapshot.get("series", []) if entry.get("query")}

    movie_ids: set[str] = set()
    for row in conn.execute(
        """
        SELECT items.id, items.title, metadata.provider_id
        FROM items
        LEFT JOIN metadata ON metadata.item_id = items.id
        WHERE items.available = 1 AND items.kind = 'movie'
        """
    ).fetchall():
        query = (clean_metadata_query(row["title"], "movie") or row["title"]).lower()
        provider_id = str(row["provider_id"] or "")
        if (provider_id and provider_id in movie_provider_ids) or query in movie_queries:
            movie_ids.add(row["id"])

    series_ids = {
        row["id"]
        for row in conn.execute(
            "SELECT id, query FROM series_groups"
        ).fetchall()
        if (row["query"] or "").lower() in series_queries
    }
    return {"movie_ids": movie_ids, "series_ids": series_ids}


def trending_library_ids(conn: sqlite3.Connection) -> dict[str, set[str]]:
    return library_ids_for_snapshot(conn, get_trending_snapshot(conn))


def popular_library_ids(conn: sqlite3.Connection) -> dict[str, set[str]]:
    return library_ids_for_snapshot(conn, get_popular_snapshot(conn))


def build_tmdb_record(item: sqlite3.Row) -> dict[str, Any]:
    bearer = settings.effective_value("TMDB_BEARER_TOKEN")
    api_key = settings.effective_value("TMDB_API_KEY")
    if bearer.lower().startswith("bearer "):
        bearer = bearer[7:].strip()
    if not bearer and not api_key:
        raise HTTPException(400, "TMDB_BEARER_TOKEN or TMDB_API_KEY is missing")

    media_type = "tv" if item["kind"] == "series" else "movie"
    endpoint = "search/tv" if media_type == "tv" else "search/movie"
    query = clean_metadata_query(item["title"], item["kind"]) or item["title"]
    params = {
        "query": query,
        "language": settings.effective_value("METADATA_LANGUAGE", "en-US"),
        "page": "1",
        "include_adult": "false",
    }
    year = title_year(item["title"])
    if year:
        params["first_air_date_year" if media_type == "tv" else "year"] = year
    if api_key:
        params["api_key"] = api_key
    url = f"https://api.themoviedb.org/3/{endpoint}?{urllib.parse.urlencode(params)}"
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    data = json.loads(fetch_text(url, headers=headers, timeout=30))
    results = data.get("results") or []
    if not results:
        raise HTTPException(404, f"No TMDB match found for {query}")
    result = results[0]
    poster = f"https://image.tmdb.org/t/p/w342{result['poster_path']}" if result.get("poster_path") else ""
    title = result.get("name") if media_type == "tv" else result.get("title")
    date = result.get("first_air_date") if media_type == "tv" else result.get("release_date")
    provider_id = str(result.get("id") or "")
    return {
        "item_id": item["id"],
        "provider": "tmdb",
        "media_type": media_type,
        "provider_id": provider_id,
        "query": query,
        "title": title,
        "release_date": date,
        "rating": result.get("vote_average"),
        "votes": result.get("vote_count"),
        "description": result.get("overview"),
        "poster_url": poster,
        "provider_url": f"https://www.themoviedb.org/{media_type}/{provider_id}",
        "cached_at": now_iso(),
    }


def build_series_group_record(series_row: sqlite3.Row) -> dict[str, Any]:
    bearer = settings.effective_value("TMDB_BEARER_TOKEN")
    api_key = settings.effective_value("TMDB_API_KEY")
    if bearer.lower().startswith("bearer "):
        bearer = bearer[7:].strip()
    if not bearer and not api_key:
        raise HTTPException(400, "TMDB_BEARER_TOKEN or TMDB_API_KEY is missing")

    query = clean_metadata_query(series_row["query"] or series_row["title"], "series") or series_row["query"]
    params = {
        "query": query,
        "language": settings.effective_value("METADATA_LANGUAGE", "en-US"),
        "page": "1",
        "include_adult": "false",
    }
    year = title_year(series_row["title"])
    if year:
        params["first_air_date_year"] = year
    url = f"https://api.themoviedb.org/3/search/tv?{urllib.parse.urlencode(params)}"

    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    data = json.loads(fetch_text(url, headers=headers, timeout=30))
    results = data.get("results") or []
    if not results:
        raise HTTPException(404, f"No TMDB match found for {query}")
    result = results[0]
    poster = f"https://image.tmdb.org/t/p/w342{result['poster_path']}" if result.get("poster_path") else ""
    return {
        "id": series_row["id"],
        "title": result.get("name") or series_row["title"],
        "query": query,
        "release_date": result.get("first_air_date"),
        "rating": result.get("vote_average"),
        "description": result.get("overview"),
        "poster_url": poster,
        "provider_url": f"https://www.themoviedb.org/tv/{result.get('id') or ''}",
        "cached_at": now_iso(),
    }


def upsert_metadata_record(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO metadata(item_id, provider, media_type, provider_id, query, title, release_date, rating, votes, description, poster_url, provider_url, cached_at)
        VALUES(:item_id, :provider, :media_type, :provider_id, :query, :title, :release_date, :rating, :votes, :description, :poster_url, :provider_url, :cached_at)
        ON CONFLICT(item_id) DO UPDATE SET
          provider=excluded.provider,
          media_type=excluded.media_type,
          provider_id=excluded.provider_id,
          query=excluded.query,
          title=excluded.title,
          release_date=excluded.release_date,
          rating=excluded.rating,
          votes=excluded.votes,
          description=excluded.description,
          poster_url=excluded.poster_url,
          provider_url=excluded.provider_url,
          cached_at=excluded.cached_at
        """,
        record,
    )


def ensure_metadata_for_item(conn: sqlite3.Connection, item: sqlite3.Row) -> dict[str, Any]:
    cached = conn.execute("SELECT * FROM metadata WHERE item_id = ?", (item["id"],)).fetchone()
    if cached:
        clear_metadata_attempt(conn, "item", item["id"])
        return dict(cached)

    media_type = "tv" if item["kind"] == "series" else "movie"
    query = clean_metadata_query(item["title"], item["kind"]) or item["title"]
    reused = conn.execute(
        """
        SELECT * FROM metadata
        WHERE media_type = ? AND query = ?
        ORDER BY cached_at DESC
        LIMIT 1
        """,
        (media_type, query),
    ).fetchone()
    if reused:
        record = dict(reused)
        record["item_id"] = item["id"]
        record["cached_at"] = now_iso()
        upsert_metadata_record(conn, record)
        clear_metadata_attempt(conn, "item", item["id"])
        return record

    record = build_tmdb_record(item)
    upsert_metadata_record(conn, record)
    clear_metadata_attempt(conn, "item", item["id"])
    return record


def ensure_series_group_metadata(conn: sqlite3.Connection, series_row: sqlite3.Row) -> dict[str, Any]:
    # Re-fetch series that still carry a raw release year in their title so the stored title is cleaned up too.
    title_looks_raw = bool(re.search(r"[\[(](?:19|20)\d{2}[\])]|(?:19|20)\d{2}\s*$", series_row["title"] or ""))
    if series_row["poster_url"] and series_row["description"] and not title_looks_raw:
        clear_metadata_attempt(conn, "series", series_row["id"])
        return dict(series_row)
    record = build_series_group_record(series_row)
    conn.execute(
        """
        UPDATE series_groups
        SET title = ?, release_date = ?, rating = ?, description = ?, poster_url = ?, provider_url = ?, cached_at = ?
        WHERE id = ?
        """,
        (
            record["title"],
            record["release_date"],
            record["rating"],
            record["description"],
            record["poster_url"],
            record["provider_url"],
            record["cached_at"],
            series_row["id"],
        ),
    )
    clear_metadata_attempt(conn, "series", series_row["id"])
    return record


def metadata_warmup_status(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "running": bool(get_state(conn, "metadata_warmup_running", False)),
        "total": int(get_state(conn, "metadata_warmup_total", 0) or 0),
        "completed": int(get_state(conn, "metadata_warmup_completed", 0) or 0),
        "error": get_state(conn, "metadata_warmup_error"),
        "started_at": get_state(conn, "metadata_warmup_started_at"),
        "finished_at": get_state(conn, "metadata_warmup_finished_at"),
    }


async def async_metadata_warmup_status(conn: aiosqlite.Connection) -> dict[str, Any]:
    return {
        "running": bool(await async_get_state(conn, "metadata_warmup_running", False)),
        "total": int(await async_get_state(conn, "metadata_warmup_total", 0) or 0),
        "completed": int(await async_get_state(conn, "metadata_warmup_completed", 0) or 0),
        "error": await async_get_state(conn, "metadata_warmup_error"),
        "started_at": await async_get_state(conn, "metadata_warmup_started_at"),
        "finished_at": await async_get_state(conn, "metadata_warmup_finished_at"),
    }


async def async_get_tmdb_cache(conn: aiosqlite.Connection, cache_key: str, max_age_hours: int = 6) -> dict[str, Any] | None:
    cache = await async_get_state(conn, cache_key)
    if cache and cache.get("cached_at"):
        try:
            cached_at = datetime.fromisoformat(cache["cached_at"])
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
            if cached_at >= datetime.now(timezone.utc) - timedelta(hours=max_age_hours):
                return cache
        except ValueError:
            pass
    return None


async def async_build_tmdb_library_snapshot(movie_endpoint: str, series_endpoint: str, language: str) -> dict[str, Any]:
    movie_results = (await asyncio.to_thread(fetch_tmdb_json, movie_endpoint, {"language": language})).get("results") or []
    series_results = (await asyncio.to_thread(fetch_tmdb_json, series_endpoint, {"language": language})).get("results") or []
    return {
        "cached_at": now_iso(),
        "movies": [
            {
                "provider_id": str(result.get("id") or ""),
                "query": (clean_metadata_query(result.get("title") or "", "movie") or (result.get("title") or "")).lower(),
            }
            for result in movie_results
            if result.get("id") and result.get("title")
        ],
        "series": [
            {
                "query": (clean_metadata_query(result.get("name") or "", "series") or (result.get("name") or "")).lower(),
            }
            for result in series_results
            if result.get("name")
        ],
    }


async def async_get_trending_snapshot(conn: aiosqlite.Connection) -> dict[str, Any]:
    cache = await async_get_tmdb_cache(conn, "tmdb_trending_week_cache")
    if cache:
        return cache
    language = settings.effective_value("METADATA_LANGUAGE", "en-US")
    snapshot = await async_build_tmdb_library_snapshot("trending/movie/week", "trending/tv/week", language)
    # Persist through the serialized writer: the read connection here never
    # commits, so a direct async_set_state would be rolled back and every
    # request would refetch TMDB (several seconds each).
    await write_db(lambda c: async_set_state(c, "tmdb_trending_week_cache", snapshot))
    return snapshot


async def async_get_popular_snapshot(conn: aiosqlite.Connection) -> dict[str, Any]:
    cache = await async_get_tmdb_cache(conn, "tmdb_popular_cache")
    if cache:
        return cache
    language = settings.effective_value("METADATA_LANGUAGE", "en-US")
    snapshot = await async_build_tmdb_library_snapshot("movie/popular", "tv/popular", language)
    await write_db(lambda c: async_set_state(c, "tmdb_popular_cache", snapshot))
    return snapshot


async def async_get_upcoming_snapshot(conn: aiosqlite.Connection) -> dict[str, Any]:
    cache = await async_get_tmdb_cache(conn, "tmdb_upcoming_cache")
    if cache:
        return cache
    language = settings.effective_value("METADATA_LANGUAGE", "en-US")
    results = (await asyncio.to_thread(fetch_tmdb_json, "movie/upcoming", {"language": language, "page": 1})).get("results") or []
    snapshot = {
        "cached_at": now_iso(),
        "items": [
            {
                "id": f"tmdb-upcoming-{result.get('id')}",
                "title": result.get("title") or "",
                "group_name": "TMDB Upcoming",
                "kind": "movie",
                "logo": "",
                "stream_url": "",
                "added_at": "",
                "last_seen_at": "",
                "is_favorite": 0,
                "is_watched": 0,
                "is_new": 0,
                "is_external": 1,
                "metadata_title": result.get("title") or "",
                "release_date": result.get("release_date") or "",
                "rating": result.get("vote_average"),
                "description": result.get("overview") or "",
                "poster_url": f"https://image.tmdb.org/t/p/w342{result['poster_path']}" if result.get("poster_path") else "",
                "provider_url": f"https://www.themoviedb.org/movie/{result.get('id') or ''}",
            }
            for result in results
            if result.get("id") and result.get("title")
        ],
    }
    await write_db(lambda c: async_set_state(c, "tmdb_upcoming_cache", snapshot))
    return snapshot


async def async_library_ids_for_snapshot(conn: aiosqlite.Connection, snapshot: dict[str, Any]) -> dict[str, set[str]]:
    movie_provider_ids = {entry["provider_id"] for entry in snapshot.get("movies", []) if entry.get("provider_id")}
    movie_queries = {entry["query"] for entry in snapshot.get("movies", []) if entry.get("query")}
    series_queries = {entry["query"] for entry in snapshot.get("series", []) if entry.get("query")}

    movie_ids: set[str] = set()
    cursor = await conn.execute(
        """
        SELECT items.id, items.title, metadata.provider_id
        FROM items
        LEFT JOIN metadata ON metadata.item_id = items.id
        WHERE items.available = 1 AND items.kind = 'movie'
        """
    )
    async for row in cursor:
        query = (clean_metadata_query(row["title"], "movie") or row["title"]).lower()
        provider_id = str(row["provider_id"] or "")
        if (provider_id and provider_id in movie_provider_ids) or query in movie_queries:
            movie_ids.add(row["id"])

    series_ids: set[str] = set()
    cursor = await conn.execute("SELECT id, query FROM series_groups")
    async for row in cursor:
        if (row["query"] or "").lower() in series_queries:
            series_ids.add(row["id"])
    return {"movie_ids": movie_ids, "series_ids": series_ids}


async def async_trending_library_ids(conn: aiosqlite.Connection) -> dict[str, set[str]]:
    return await async_library_ids_for_snapshot(conn, await async_get_trending_snapshot(conn))


async def async_popular_library_ids(conn: aiosqlite.Connection) -> dict[str, set[str]]:
    return await async_library_ids_for_snapshot(conn, await async_get_popular_snapshot(conn))


async def async_fetch_tmdb_json(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(fetch_tmdb_json, endpoint, params)


async def async_build_tmdb_record(item: aiosqlite.Row) -> dict[str, Any]:
    return await asyncio.to_thread(build_tmdb_record, item)


async def async_build_series_group_record(series_row: aiosqlite.Row) -> dict[str, Any]:
    return await asyncio.to_thread(build_series_group_record, series_row)


async def async_upsert_metadata_record(conn: aiosqlite.Connection, record: dict[str, Any]) -> None:
    await conn.execute(
        """
        INSERT INTO metadata(item_id, provider, media_type, provider_id, query, title, release_date, rating, votes, description, poster_url, provider_url, cached_at)
        VALUES(:item_id, :provider, :media_type, :provider_id, :query, :title, :release_date, :rating, :votes, :description, :poster_url, :provider_url, :cached_at)
        ON CONFLICT(item_id) DO UPDATE SET
          provider=excluded.provider,
          media_type=excluded.media_type,
          provider_id=excluded.provider_id,
          query=excluded.query,
          title=excluded.title,
          release_date=excluded.release_date,
          rating=excluded.rating,
          votes=excluded.votes,
          description=excluded.description,
          poster_url=excluded.poster_url,
          provider_url=excluded.provider_url,
          cached_at=excluded.cached_at
        """,
        record,
    )


async def async_record_metadata_attempt(conn: aiosqlite.Connection, entity_type: str, entity_id: str, error_text: str | None) -> None:
    await conn.execute(
        """
        INSERT INTO metadata_attempts(entity_type, entity_id, last_attempted_at, last_error, attempts)
        VALUES(?, ?, ?, ?, 1)
        ON CONFLICT(entity_type, entity_id) DO UPDATE SET
          last_attempted_at = excluded.last_attempted_at,
          last_error = excluded.last_error,
          attempts = metadata_attempts.attempts + 1
        """,
        (entity_type, entity_id, retry_after_iso(error_text or ""), error_text),
    )


async def async_clear_metadata_attempt(conn: aiosqlite.Connection, entity_type: str, entity_id: str) -> None:
    await conn.execute(
        "DELETE FROM metadata_attempts WHERE entity_type = ? AND entity_id = ?",
        (entity_type, entity_id),
    )


async def async_ensure_metadata_for_item(conn: aiosqlite.Connection, item: aiosqlite.Row) -> dict[str, Any]:
    cached = await (await conn.execute("SELECT * FROM metadata WHERE item_id = ?", (item["id"],))).fetchone()
    if cached:
        await async_clear_metadata_attempt(conn, "item", item["id"])
        return dict(cached)

    media_type = "tv" if item["kind"] == "series" else "movie"
    query = clean_metadata_query(item["title"], item["kind"]) or item["title"]
    reused = await (
        await conn.execute(
            """
            SELECT * FROM metadata
            WHERE media_type = ? AND query = ?
            ORDER BY cached_at DESC
            LIMIT 1
            """,
            (media_type, query),
        )
    ).fetchone()
    if reused:
        record = dict(reused)
        record["item_id"] = item["id"]
        record["cached_at"] = now_iso()
        await async_upsert_metadata_record(conn, record)
        await async_clear_metadata_attempt(conn, "item", item["id"])
        return record

    record = await async_build_tmdb_record(item)
    await async_upsert_metadata_record(conn, record)
    await async_clear_metadata_attempt(conn, "item", item["id"])
    return record


async def async_ensure_series_group_metadata(conn: aiosqlite.Connection, series_row: aiosqlite.Row) -> dict[str, Any]:
    title_looks_raw = bool(re.search(r"[\[(](?:19|20)\d{2}[\])]|(?:19|20)\d{2}\s*$", series_row["title"] or ""))
    if series_row["poster_url"] and series_row["description"] and not title_looks_raw:
        await async_clear_metadata_attempt(conn, "series", series_row["id"])
        return dict(series_row)
    record = await async_build_series_group_record(series_row)
    await conn.execute(
        """
        UPDATE series_groups
        SET title = ?, release_date = ?, rating = ?, description = ?, poster_url = ?, provider_url = ?, cached_at = ?
        WHERE id = ?
        """,
        (
            record["title"],
            record["release_date"],
            record["rating"],
            record["description"],
            record["poster_url"],
            record["provider_url"],
            record["cached_at"],
            series_row["id"],
        ),
    )
    await async_clear_metadata_attempt(conn, "series", series_row["id"])
    return record


async def async_count_warmup_series(conn: aiosqlite.Connection, last_refresh: str | None, now: str) -> int:
    if last_refresh:
        return (await (
            await conn.execute(
                """
                SELECT COUNT(DISTINCT series_groups.id) AS count
                FROM series_groups
                JOIN items ON items.series_id = series_groups.id
                LEFT JOIN metadata_attempts attempts
                  ON attempts.entity_type = 'series' AND attempts.entity_id = series_groups.id
                WHERE items.available = 1 AND items.added_at = ?
                  AND (COALESCE(series_groups.poster_url, '') = '' OR COALESCE(series_groups.description, '') = '')
                  AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
                """,
                (last_refresh, now),
            )
        ).fetchone())["count"]
    return (await (
        await conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM series_groups
            LEFT JOIN metadata_attempts attempts
              ON attempts.entity_type = 'series' AND attempts.entity_id = series_groups.id
            WHERE (COALESCE(poster_url, '') = '' OR COALESCE(description, '') = '')
              AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
            """,
            (now,),
        )
    ).fetchone())["count"]


async def async_count_warmup_movies(conn: aiosqlite.Connection, last_refresh: str | None, now: str) -> int:
    if last_refresh:
        return (await (
            await conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM items
                LEFT JOIN metadata ON metadata.item_id = items.id
                LEFT JOIN metadata_attempts attempts
                  ON attempts.entity_type = 'item' AND attempts.entity_id = items.id
                WHERE items.available = 1 AND items.kind = 'movie' AND items.added_at = ?
                  AND metadata.item_id IS NULL
                  AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
                """,
                (last_refresh, now),
            )
        ).fetchone())["count"]
    return (await (
        await conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM items
            LEFT JOIN metadata ON metadata.item_id = items.id
            LEFT JOIN metadata_attempts attempts
              ON attempts.entity_type = 'item' AND attempts.entity_id = items.id
            WHERE items.available = 1 AND items.kind = 'movie' AND metadata.item_id IS NULL
              AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
            """,
            (now,),
        )
    ).fetchone())["count"]


async def async_fetch_warmup_series_batch(
    conn: aiosqlite.Connection, last_refresh: str | None, now: str, limit: int
) -> list[aiosqlite.Row]:
    if last_refresh:
        return await (
            await conn.execute(
                """
                SELECT series_groups.*
                FROM series_groups
                JOIN items ON items.series_id = series_groups.id
                LEFT JOIN metadata_attempts attempts
                  ON attempts.entity_type = 'series' AND attempts.entity_id = series_groups.id
                WHERE items.available = 1 AND items.added_at = ?
                  AND (COALESCE(series_groups.poster_url, '') = '' OR COALESCE(series_groups.description, '') = '')
                  AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
                ORDER BY series_groups.title COLLATE NOCASE
                LIMIT ?
                """,
                (last_refresh, now, limit),
            )
        ).fetchall()
    return await (
        await conn.execute(
            """
            SELECT *
            FROM series_groups
            LEFT JOIN metadata_attempts attempts
              ON attempts.entity_type = 'series' AND attempts.entity_id = series_groups.id
            WHERE (COALESCE(poster_url, '') = '' OR COALESCE(description, '') = '')
              AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
            ORDER BY title COLLATE NOCASE
            LIMIT ?
            """,
            (now, limit),
        )
    ).fetchall()


async def async_fetch_warmup_movies_batch(
    conn: aiosqlite.Connection, last_refresh: str | None, now: str, limit: int
) -> list[aiosqlite.Row]:
    if last_refresh:
        return await (
            await conn.execute(
                """
                SELECT items.*
                FROM items
                LEFT JOIN metadata ON metadata.item_id = items.id
                LEFT JOIN metadata_attempts attempts
                  ON attempts.entity_type = 'item' AND attempts.entity_id = items.id
                WHERE items.available = 1 AND items.kind = 'movie' AND items.added_at = ?
                  AND metadata.item_id IS NULL
                  AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
                ORDER BY items.title COLLATE NOCASE
                LIMIT ?
                """,
                (last_refresh, now, limit),
            )
        ).fetchall()
    return await (
        await conn.execute(
            """
            SELECT items.*
            FROM items
            LEFT JOIN metadata ON metadata.item_id = items.id
            LEFT JOIN metadata_attempts attempts
              ON attempts.entity_type = 'item' AND attempts.entity_id = items.id
            WHERE items.available = 1 AND items.kind = 'movie' AND metadata.item_id IS NULL
              AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
            ORDER BY items.title COLLATE NOCASE
            LIMIT ?
            """,
            (now, limit),
        )
    ).fetchall()


def _count_warmup_series(conn: sqlite3.Connection, last_refresh: str | None, now: str) -> int:
    if last_refresh:
        return conn.execute(
            """
            SELECT COUNT(DISTINCT series_groups.id) AS count
            FROM series_groups
            JOIN items ON items.series_id = series_groups.id
            LEFT JOIN metadata_attempts attempts
              ON attempts.entity_type = 'series' AND attempts.entity_id = series_groups.id
            WHERE items.available = 1 AND items.added_at = ?
              AND (COALESCE(series_groups.poster_url, '') = '' OR COALESCE(series_groups.description, '') = '')
              AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
            """,
            (last_refresh, now),
        ).fetchone()["count"]
    return conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM series_groups
        LEFT JOIN metadata_attempts attempts
          ON attempts.entity_type = 'series' AND attempts.entity_id = series_groups.id
        WHERE (COALESCE(poster_url, '') = '' OR COALESCE(description, '') = '')
          AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
        """,
        (now,),
    ).fetchone()["count"]


def _count_warmup_movies(conn: sqlite3.Connection, last_refresh: str | None, now: str) -> int:
    if last_refresh:
        return conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM items
            LEFT JOIN metadata ON metadata.item_id = items.id
            LEFT JOIN metadata_attempts attempts
              ON attempts.entity_type = 'item' AND attempts.entity_id = items.id
            WHERE items.available = 1 AND items.kind = 'movie' AND items.added_at = ?
              AND metadata.item_id IS NULL
              AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
            """,
            (last_refresh, now),
        ).fetchone()["count"]
    return conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM items
        LEFT JOIN metadata ON metadata.item_id = items.id
        LEFT JOIN metadata_attempts attempts
          ON attempts.entity_type = 'item' AND attempts.entity_id = items.id
        WHERE items.available = 1 AND items.kind = 'movie' AND metadata.item_id IS NULL
          AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
        """,
        (now,),
    ).fetchone()["count"]


def _fetch_warmup_series_batch(
    conn: sqlite3.Connection, last_refresh: str | None, now: str, limit: int
) -> list[sqlite3.Row]:
    if last_refresh:
        return conn.execute(
            """
            SELECT series_groups.*
            FROM series_groups
            JOIN items ON items.series_id = series_groups.id
            LEFT JOIN metadata_attempts attempts
              ON attempts.entity_type = 'series' AND attempts.entity_id = series_groups.id
            WHERE items.available = 1 AND items.added_at = ?
              AND (COALESCE(series_groups.poster_url, '') = '' OR COALESCE(series_groups.description, '') = '')
              AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
            ORDER BY series_groups.title COLLATE NOCASE
            LIMIT ?
            """,
            (last_refresh, now, limit),
        ).fetchall()
    return conn.execute(
        """
        SELECT *
        FROM series_groups
        LEFT JOIN metadata_attempts attempts
          ON attempts.entity_type = 'series' AND attempts.entity_id = series_groups.id
        WHERE (COALESCE(poster_url, '') = '' OR COALESCE(description, '') = '')
          AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
        ORDER BY title COLLATE NOCASE
        LIMIT ?
        """,
        (now, limit),
    ).fetchall()


def _fetch_warmup_movies_batch(
    conn: sqlite3.Connection, last_refresh: str | None, now: str, limit: int
) -> list[sqlite3.Row]:
    if last_refresh:
        return conn.execute(
            """
            SELECT items.*
            FROM items
            LEFT JOIN metadata ON metadata.item_id = items.id
            LEFT JOIN metadata_attempts attempts
              ON attempts.entity_type = 'item' AND attempts.entity_id = items.id
            WHERE items.available = 1 AND items.kind = 'movie' AND items.added_at = ?
              AND metadata.item_id IS NULL
              AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
            ORDER BY items.title COLLATE NOCASE
            LIMIT ?
            """,
            (last_refresh, now, limit),
        ).fetchall()
    return conn.execute(
        """
        SELECT items.*
        FROM items
        LEFT JOIN metadata ON metadata.item_id = items.id
        LEFT JOIN metadata_attempts attempts
          ON attempts.entity_type = 'item' AND attempts.entity_id = items.id
        WHERE items.available = 1 AND items.kind = 'movie' AND metadata.item_id IS NULL
          AND (attempts.last_attempted_at IS NULL OR attempts.last_attempted_at <= ?)
        ORDER BY items.title COLLATE NOCASE
        LIMIT ?
        """,
        (now, limit),
    ).fetchall()


async def _metadata_warmup_worker(last_refresh: str | None = None) -> None:
    now = now_iso()

    async def _init_status(conn: aiosqlite.Connection) -> int:
        total_series = await async_count_warmup_series(conn, last_refresh, now)
        total_movies = await async_count_warmup_movies(conn, last_refresh, now)
        total = total_series + total_movies
        if last_refresh is None:
            total = min(total, MAX_WARMUP_PER_RUN)
        await async_set_state(conn, "metadata_warmup_running", True)
        await async_set_state(conn, "metadata_warmup_total", total)
        await async_set_state(conn, "metadata_warmup_completed", 0)
        await async_set_state(conn, "metadata_warmup_error", None)
        await async_set_state(conn, "metadata_warmup_started_at", now)
        await async_set_state(conn, "metadata_warmup_finished_at", None)
        return total

    async def _mark_error(conn: aiosqlite.Connection, exc: BaseException) -> None:
        await async_set_state(conn, "metadata_warmup_error", str(exc))

    async def _finish(conn: aiosqlite.Connection) -> None:
        await async_set_state(conn, "metadata_warmup_running", False)
        await async_set_state(conn, "metadata_warmup_finished_at", now_iso())

    total = await write_db(_init_status)
    completed = 0
    try:
        while completed < total:
            batch = await write_db(lambda conn: async_fetch_warmup_series_batch(conn, last_refresh, now, min(50, total - completed)))
            if not batch:
                break
            for series_row in batch:
                if completed >= total:
                    break
                try:
                    await write_db(lambda conn, row=series_row: async_ensure_series_group_metadata(conn, row))
                except Exception as exc:
                    await write_db(lambda conn, row=series_row, err=str(exc): async_record_metadata_attempt(conn, "series", row["id"], err))
                completed += 1
                await write_db(lambda conn, c=completed: async_set_state(conn, "metadata_warmup_completed", c))
                await asyncio.sleep(WARMUP_REQUEST_DELAY)

        while completed < total:
            batch = await write_db(lambda conn: async_fetch_warmup_movies_batch(conn, last_refresh, now, min(50, total - completed)))
            if not batch:
                break
            for item in batch:
                if completed >= total:
                    break
                try:
                    await write_db(lambda conn, it=item: async_ensure_metadata_for_item(conn, it))
                except Exception as exc:
                    await write_db(lambda conn, it=item, err=str(exc): async_record_metadata_attempt(conn, "item", it["id"], err))
                completed += 1
                await write_db(lambda conn, c=completed: async_set_state(conn, "metadata_warmup_completed", c))
                await asyncio.sleep(WARMUP_REQUEST_DELAY)
    except Exception as exc:
        await write_db(lambda conn, e=exc: _mark_error(conn, e))
    finally:
        await write_db(_finish)


def run_metadata_warmup(last_refresh: str | None = None) -> None:
    global METADATA_WARMUP_TASK
    if METADATA_WARMUP_TASK and not METADATA_WARMUP_TASK.done():
        METADATA_WARMUP_TASK.cancel()
    METADATA_WARMUP_TASK = asyncio.create_task(_metadata_warmup_worker(last_refresh))


@app.get("/api/metadata")
async def metadata(id: str) -> dict[str, Any]:
    await async_init_db()
    async with read_db() as conn:
        item = await (await conn.execute("SELECT * FROM items WHERE id = ?", (id,))).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")
        if item["kind"] == "live":
            raise HTTPException(400, "Metadata lookup is only available for movies and series")
        return await async_ensure_metadata_for_item(conn, item)


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    await async_init_db()
    async with read_db() as conn:
        last_refresh = await async_get_state(conn, "last_refresh")
        return {
            "last_refresh": last_refresh,
            "metadata_status": await async_metadata_warmup_status(conn),
        }


@app.get("/api/state/snapshots", dependencies=[Depends(require_api_key)])
async def list_state_snapshots() -> dict[str, Any]:
    """List available watched/favorite state snapshots."""
    snap_dir = state_snapshot_dir()
    snapshots = []
    if snap_dir.is_dir():
        for path in sorted(snap_dir.glob("snapshot-*.json"), key=lambda p: p.name, reverse=True):
            snapshots.append({"file": path.name, "size": path.stat().st_size})
    latest = snap_dir / "latest.json"
    return {
        "snapshots": snapshots,
        "latest": latest.stat().st_size if latest.exists() else None,
    }


@app.post("/api/state/restore", dependencies=[Depends(require_api_key)])
async def restore_state(file: str = "latest.json") -> dict[str, Any]:
    """Restore watched/favorite state from a snapshot.

    Only state columns are written; ids missing from the current library are
    counted as missing. last_refresh is bumped so open tabs auto-reload.
    """
    await async_init_db()
    file_name = Path(file).name
    snap_path = state_snapshot_dir() / file_name
    if not snap_path.exists():
        raise HTTPException(404, f"State snapshot not found: {file_name}")
    payload = json.loads(snap_path.read_text(encoding="utf-8"))
    if payload.get("version") != STATE_SNAPSHOT_VERSION:
        raise HTTPException(400, "Unsupported snapshot version")
    items: dict[str, dict[str, Any]] = payload.get("items") or {}
    series: dict[str, dict[str, Any]] = payload.get("series_groups") or {}

    async def _apply(conn: aiosqlite.Connection) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "items_updated": 0,
            "items_missing": 0,
            "series_updated": 0,
            "series_missing": 0,
        }
        item_rows = [
            (int(st.get("w") or 0), int(st.get("f") or 0), st.get("at"), item_id)
            for item_id, st in items.items()
        ]
        CHUNK = 5000
        for i in range(0, len(item_rows), CHUNK):
            cursor = await conn.executemany(
                "UPDATE items SET is_watched = ?, is_favorite = ?, watched_at = ? WHERE id = ?",
                item_rows[i : i + CHUNK],
            )
            stats["items_updated"] += cursor.rowcount if cursor.rowcount is not None else 0
        stats["items_missing"] = len(item_rows) - stats["items_updated"]
        series_rows = [
            (int(st.get("w") or 0), int(st.get("f") or 0), st.get("at"), gid)
            for gid, st in series.items()
        ]
        cursor = await conn.executemany(
            "UPDATE series_groups SET is_watched = ?, is_favorite = ?, watched_at = ? WHERE id = ?",
            series_rows,
        )
        stats["series_updated"] = cursor.rowcount if cursor.rowcount is not None else 0
        stats["series_missing"] = len(series_rows) - stats["series_updated"]
        for gid in series:
            await _async_update_series_group_stats(conn, gid)
        await async_set_state(conn, "last_refresh", now_iso())
        return stats

    stats = await write_db(_apply)
    stats["restored_from"] = file_name
    return stats


@app.post("/api/items/{item_id}/favorite")
async def toggle_favorite(item_id: str) -> dict[str, Any]:
    async with read_db() as conn:
        row = await (await conn.execute("SELECT is_favorite FROM items WHERE id = ?", (item_id,))).fetchone()
    if not row:
        raise HTTPException(404, "Item not found")
    value = 0 if row["is_favorite"] else 1

    async def _do_write(conn: aiosqlite.Connection) -> None:
        await conn.execute("UPDATE items SET is_favorite = ? WHERE id = ?", (value, item_id))

    await write_db(_do_write)
    return {"id": item_id, "is_favorite": value}


@app.post("/api/items/{item_id}/watched")
async def toggle_watched(item_id: str) -> dict[str, Any]:
    async with read_db() as conn:
        row = await (
            await conn.execute("SELECT is_watched, series_id FROM items WHERE id = ?", (item_id,))
        ).fetchone()
    if not row:
        raise HTTPException(404, "Item not found")
    value = 0 if row["is_watched"] else 1
    watched_at = now_iso() if value else None

    async def _do_write(conn: aiosqlite.Connection) -> None:
        await conn.execute(
            "UPDATE items SET is_watched = ?, watched_at = ? WHERE id = ?",
            (value, watched_at, item_id),
        )
        if row["series_id"]:
            await _async_update_series_group_stats(conn, row["series_id"])

    await write_db(_do_write)

    series_is_watched = None
    series_watched_at = None
    if row["series_id"]:
        async with read_db() as conn:
            series_row = await (
                await conn.execute(
                    "SELECT is_watched, watched_at FROM series_groups WHERE id = ?",
                    (row["series_id"],),
                )
            ).fetchone()
        if series_row:
            series_is_watched = series_row["is_watched"]
            series_watched_at = series_row["watched_at"]

    return {
        "id": item_id,
        "is_watched": value,
        "watched_at": watched_at,
        "series_id": row["series_id"],
        "series_is_watched": series_is_watched,
        "series_watched_at": series_watched_at,
    }


@app.post("/api/series/{series_id}/favorite")
async def toggle_series_favorite(series_id: str) -> dict[str, Any]:
    async with read_db() as conn:
        row = await (
            await conn.execute("SELECT is_favorite FROM series_groups WHERE id = ?", (series_id,))
        ).fetchone()
    if not row:
        raise HTTPException(404, "Series not found")
    value = 0 if row["is_favorite"] else 1

    async def _do_write(conn: aiosqlite.Connection) -> None:
        await conn.execute("UPDATE series_groups SET is_favorite = ? WHERE id = ?", (value, series_id))

    await write_db(_do_write)
    return {"id": series_id, "is_favorite": value}


@app.post("/api/series/{series_id}/watched")
async def toggle_series_watched(series_id: str) -> dict[str, Any]:
    async with read_db() as conn:
        row = await (
            await conn.execute("SELECT is_watched FROM series_groups WHERE id = ?", (series_id,))
        ).fetchone()
    if not row:
        raise HTTPException(404, "Series not found")
    value = 0 if row["is_watched"] else 1
    watched_at = now_iso() if value else None

    async def _do_write(conn: aiosqlite.Connection) -> None:
        await conn.execute(
            "UPDATE series_groups SET is_watched = ?, watched_at = ? WHERE id = ?",
            (value, watched_at, series_id),
        )
        if value:
            await conn.execute(
                "UPDATE items SET is_watched = 1, watched_at = ? WHERE series_id = ?",
                (watched_at, series_id),
            )
        else:
            await conn.execute(
                "UPDATE items SET is_watched = 0, watched_at = NULL WHERE series_id = ?",
                (series_id,),
            )
        await _async_update_series_group_stats(conn, series_id)

    await write_db(_do_write)
    return {"id": series_id, "is_watched": value, "watched_at": watched_at}


@app.post("/api/metadata/enrich", dependencies=[Depends(require_api_key)])
async def enrich_metadata(ids: list[str]) -> dict[str, Any]:
    await async_init_db()
    loaded: list[dict[str, Any]] = []
    for item_id in ids[:24]:
        try:
            loaded.append(await metadata(item_id))
        except HTTPException:
            continue
    return {"items": loaded}


@app.post("/api/metadata/warmup", dependencies=[Depends(require_api_key)])
async def trigger_metadata_warmup() -> dict[str, Any]:
    await async_init_db()
    run_metadata_warmup()
    async with read_db() as conn:
        return await async_metadata_warmup_status(conn)


@app.get("/api/metadata/status")
async def get_metadata_status() -> dict[str, Any]:
    await async_init_db()
    async with read_db() as conn:
        return await async_metadata_warmup_status(conn)


@app.get("/watch/{id}.m3u")
def watch_playlist(id: str) -> Response:
    init_db()
    with db() as conn:
        item = conn.execute("SELECT title, stream_url FROM items WHERE id = ?", (id,)).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")
        body = f"#EXTM3U\n#EXTINF:-1,{item['title']}\n{item['stream_url']}\n"
        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", item["title"]).strip("_") or "stream"
        return Response(
            body,
            media_type="audio/x-mpegurl",
            headers={"Content-Disposition": f'attachment; filename="{filename}.m3u"'},
        )
