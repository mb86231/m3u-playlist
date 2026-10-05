from __future__ import annotations

import hashlib
import hmac
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import time
import sqlite3
import threading
import aiosqlite
import asyncio
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security, status
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.security import APIKeyHeader

from m3u_library import migrations
from m3u_library import settings
from m3u_library.db import db as ASYNC_DB, init_db as async_init_db, read_db, write_db, get_state as async_get_state, set_state as async_set_state


APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", "/var/lib/apps/m3u-library"))
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "app.db"))
TRANSCODE_ROOT = DATA_DIR / "transcode"
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
TRANSCODE_LOCK = threading.Lock()
ACTIVE_TRANSCODES: dict[str, dict[str, Any]] = {}


@app.middleware("http")
async def disable_cache(request: Request, call_next):
    response = await call_next(request)
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


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def vaapi_device() -> str | None:
    for candidate in ("/dev/dri/renderD128", "/dev/dri/renderD129"):
        if Path(candidate).exists():
            return candidate
    return None


def ffmpeg_video_args(for_streaming: bool) -> tuple[list[str], str]:
    device = vaapi_device()
    if device:
        if for_streaming:
            return (
                [
                    "-vaapi_device",
                    device,
                    "-vf",
                    "scale='min(1280,iw)':-2,format=nv12,hwupload",
                    "-rc_mode",
                    "CQP",
                    "-qp",
                    "23",
                    "-c:v",
                    "h264_vaapi",
                    "-g",
                    "48",
                    "-keyint_min",
                    "48",
                    "-bf",
                    "0",
                ],
                "VAAPI GPU",
            )
        return (
            [
                "-vaapi_device",
                device,
                "-vf",
                "scale='min(1280,iw)':-2,format=nv12,hwupload",
                "-rc_mode",
                "CQP",
                "-qp",
                "23",
                "-c:v",
                "h264_vaapi",
            ],
            "VAAPI GPU",
        )

    if for_streaming:
        return (
            [
                "-c:v",
                "libx264",
                "-preset",
                "superfast",
                "-tune",
                "zerolatency",
                "-crf",
                "23",
                "-vf",
                "scale='min(1280,iw)':-2",
                "-maxrate",
                "3500k",
                "-bufsize",
                "7000k",
                "-g",
                "48",
                "-keyint_min",
                "48",
                "-sc_threshold",
                "0",
            ],
            "CPU x264",
        )
    return (
        [
            "-c:v",
            "libx264",
            "-preset",
            "superfast",
            "-crf",
            "23",
            "-vf",
            "scale='min(1280,iw)':-2",
            "-maxrate",
            "3500k",
            "-bufsize",
            "7000k",
        ],
        "CPU x264",
    )


def browser_playback_mode(stream_url: str) -> str:
    parsed = urllib.parse.urlparse(stream_url)
    path = (parsed.path or "").lower()
    if path.endswith(".m3u8"):
        return "hls"
    if path.endswith(".mp4") or path.endswith(".webm"):
        return "native"
    return "transcode"


def is_http_stream(stream_url: str) -> bool:
    scheme = urllib.parse.urlparse(stream_url).scheme.lower()
    return scheme in {"http", "https"}


def probe_streams(stream_url: str) -> dict[str, Any]:
    if not ffprobe_available():
        raise HTTPException(503, "ffprobe is not installed on the server yet")

    input_args: list[str] = []
    if is_http_stream(stream_url):
        input_args = [
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_on_network_error",
            "1",
            "-reconnect_on_http_error",
            "4xx,5xx",
            "-reconnect_delay_max",
            "2",
        ]

    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        *input_args,
        stream_url,
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "ffprobe timed out while checking the source stream") from exc
    except OSError as exc:
        raise HTTPException(500, f"Could not run ffprobe: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise HTTPException(502, detail[-1] if detail else "ffprobe could not inspect the source stream")

    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []

    def normalize_track(stream: dict[str, Any]) -> dict[str, Any]:
        tags = stream.get("tags") or {}
        disposition = stream.get("disposition") or {}
        codec_type = stream.get("codec_type") or "unknown"
        language = tags.get("language") or "und"
        title = tags.get("title") or tags.get("handler_name") or ""
        label_parts = [f"#{stream.get('index', '?')}", language]
        codec_name = stream.get("codec_name")
        if codec_name:
            label_parts.append(codec_name)
        channels = stream.get("channels")
        if codec_type == "audio" and channels:
            label_parts.append(f"{channels}ch")
        if title:
            label_parts.append(title)
        flags: list[str] = []
        if disposition.get("default"):
            flags.append("default")
        if disposition.get("forced"):
            flags.append("forced")
        return {
            "index": stream.get("index"),
            "codec_type": codec_type,
            "codec_name": codec_name,
            "language": language,
            "channels": channels,
            "title": title,
            "default": bool(disposition.get("default")),
            "forced": bool(disposition.get("forced")),
            "label": " | ".join(str(part) for part in label_parts if part),
            "flags": flags,
        }

    audio_tracks = [normalize_track(stream) for stream in streams if stream.get("codec_type") == "audio"]
    subtitle_tracks = [normalize_track(stream) for stream in streams if stream.get("codec_type") == "subtitle"]
    video_tracks = [normalize_track(stream) for stream in streams if stream.get("codec_type") == "video"]
    return {
        "audio_tracks": audio_tracks,
        "subtitle_tracks": subtitle_tracks,
        "video_tracks": video_tracks,
        "audio_count": len(audio_tracks),
        "subtitle_count": len(subtitle_tracks),
        "video_count": len(video_tracks),
    }


def cleanup_transcode_sessions(max_age_seconds: int = 7200) -> None:
    cutoff = time.time() - max_age_seconds
    TRANSCODE_ROOT.mkdir(parents=True, exist_ok=True)
    stale_ids: list[str] = []
    with TRANSCODE_LOCK:
        for session_id, session in list(ACTIVE_TRANSCODES.items()):
            process = session.get("process")
            session_dir = Path(session["dir"])
            session_type = session.get("session_type", "stream")
            if process and process.poll() is None and session.get("started_at", 0) >= cutoff:
                continue
            stale_ids.append(session_id)
            if process and process.poll() is None:
                process.kill()
            for extra in session.get("extra_processes", []):
                extra_process = extra.get("process")
                if extra_process and extra_process.poll() is None:
                    extra_process.kill()
                extra_log_handle = extra.get("log_handle")
                if extra_log_handle:
                    try:
                        extra_log_handle.close()
                    except OSError:
                        pass
            if session_type != "vod" and session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
        for session_id in stale_ids:
            ACTIVE_TRANSCODES.pop(session_id, None)

    for path in TRANSCODE_ROOT.iterdir():
        if not path.is_dir():
            continue
        if path.stat().st_mtime >= cutoff:
            continue
        shutil.rmtree(path, ignore_errors=True)


def should_retry_vod_start(log_path: Path, output_path: Path, retry_count: int) -> bool:
    if retry_count >= 2:
        return False
    if output_path.exists() and output_path.stat().st_size > 5 * 1024 * 1024:
        return False
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    retry_markers = (
        "error opening input files",
        "temporary failure in name resolution",
        "input/output error",
        "server returned 5",
        "connection reset by peer",
    )
    return any(marker in log_text for marker in retry_markers)


def subtitle_codec_supported_for_webvtt(codec_name: str | None) -> bool:
    return (codec_name or "").lower() in {"subrip", "srt", "webvtt", "ass", "ssa", "mov_text"}


def subtitle_candidates_from_probe(probe: dict[str, Any]) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    for track in probe.get("subtitle_tracks", []):
        if not subtitle_codec_supported_for_webvtt(track.get("codec_name")):
            continue
        normalized = dict(track)
        normalized["path"] = f"subtitle_{track['index']}.vtt"
        normalized["url"] = normalized["path"]
        tracks.append(normalized)
    return tracks


def start_vod_subtitle_extracts(
    session_dir: Path, stream_url: str, subtitle_tracks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    input_args: list[str] = []
    if is_http_stream(stream_url):
        input_args = [
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_on_network_error",
            "1",
            "-reconnect_on_http_error",
            "4xx,5xx",
            "-reconnect_delay_max",
            "2",
        ]

    started: list[dict[str, Any]] = []
    for track in subtitle_tracks:
        output_path = session_dir / track["path"]
        log_path = session_dir / f"subtitle_{track['index']}.log"
        log_handle = log_path.open("wb")
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-nostdin",
            *input_args,
            "-i",
            stream_url,
            "-map",
            f"0:{track['index']}",
            "-c:s",
            "webvtt",
            str(output_path),
        ]
        process = subprocess.Popen(
            command,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        started.append(
            {
                "process": process,
                "log_handle": log_handle,
                "log_path": str(log_path),
                "track": track,
                "output_path": str(output_path),
            }
        )
    return started


def available_vod_subtitle_tracks(session_dir: Path, subtitle_tracks: list[dict[str, Any]], item_id: str) -> list[dict[str, Any]]:
    available: list[dict[str, Any]] = []
    for track in subtitle_tracks:
        path = session_dir / track["path"]
        if not path.exists() or path.stat().st_size <= 0:
            continue
        available.append(
            {
                "index": track["index"],
                "language": track.get("language") or "und",
                "label": track.get("label") or f"Subtitle {track['index']}",
                "default": bool(track.get("default")),
                "forced": bool(track.get("forced")),
                "url": f"/play/vod/{item_id}/{track['path']}",
            }
        )
    return available


def subtitle_track_urls(subtitle_tracks: list[dict[str, Any]], item_id: str) -> list[dict[str, Any]]:
    return [
        {
            "index": track["index"],
            "language": track.get("language") or "und",
            "label": track.get("label") or f"Subtitle {track['index']}",
            "default": bool(track.get("default")),
            "forced": bool(track.get("forced")),
            "url": f"/play/subtitle/{item_id}/{track['index']}.vtt",
        }
        for track in subtitle_tracks
    ]


def extract_subtitle_to_vtt(stream_url: str, stream_index: int, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        return

    input_args: list[str] = []
    if is_http_stream(stream_url):
        input_args = [
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_on_network_error",
            "1",
            "-reconnect_on_http_error",
            "4xx,5xx",
            "-reconnect_delay_max",
            "2",
        ]

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-nostdin",
        *input_args,
        "-i",
        stream_url,
        "-map",
        f"0:{stream_index}",
        "-c:s",
        "webvtt",
        str(output_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(504, "Subtitle extraction timed out") from exc
    except OSError as exc:
        raise HTTPException(500, f"Could not run ffmpeg for subtitle extraction: {exc}") from exc

    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise HTTPException(502, detail[-1] if detail else "Subtitle extraction failed")


def vod_playlist_ready(playlist_path: Path, minimum_segments: int = 2) -> bool:
    if not playlist_path.exists() or playlist_path.stat().st_size <= 0:
        return False
    try:
        playlist_text = playlist_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return playlist_text.count("#EXTINF:") >= minimum_segments


def start_vod_process(session_dir: Path, stream_url: str) -> tuple[subprocess.Popen[bytes], Any, str]:
    playlist_path = session_dir / "index.m3u8"
    log_path = session_dir / "ffmpeg.log"
    log_handle = log_path.open("wb")
    input_args: list[str] = []
    if is_http_stream(stream_url):
        input_args = [
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_on_network_error",
            "1",
            "-reconnect_on_http_error",
            "4xx,5xx",
            "-reconnect_delay_max",
            "2",
        ]
    video_args, accel_label = ffmpeg_video_args(for_streaming=False)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-y",
        "-nostdin",
        *input_args,
        "-i",
        stream_url,
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-sn",
        *video_args,
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ac",
        "2",
        "-f",
        "hls",
        "-hls_time",
        "4",
        "-hls_list_size",
        "0",
        "-hls_playlist_type",
        "event",
        "-hls_flags",
        "append_list+independent_segments",
        "-hls_segment_filename",
        str(session_dir / "segment_%05d.ts"),
        str(playlist_path),
    ]
    process = subprocess.Popen(
        command,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return process, log_handle, accel_label


def ensure_transcode_session(item_id: str, stream_url: str) -> dict[str, str]:
    cleanup_transcode_sessions()
    TRANSCODE_ROOT.mkdir(parents=True, exist_ok=True)
    with TRANSCODE_LOCK:
        for session_id, session in ACTIVE_TRANSCODES.items():
            if session["item_id"] != item_id:
                continue
            process = session["process"]
            playlist = Path(session["dir"]) / "index.m3u8"
            if process.poll() is None and playlist.exists():
                return {
                    "session_id": session_id,
                    "playlist_url": f"/play/session/{session_id}/index.m3u8",
                    "accel_label": session.get("accel_label", "Unknown"),
                }

        session_id = uuid.uuid4().hex[:12]
        session_dir = TRANSCODE_ROOT / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        playlist = session_dir / "index.m3u8"
        log_path = session_dir / "ffmpeg.log"
        log_handle = log_path.open("wb")
        input_args: list[str] = []
        if is_http_stream(stream_url):
            input_args = [
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_on_network_error",
                "1",
                "-reconnect_on_http_error",
                "4xx,5xx",
                "-reconnect_delay_max",
                "2",
            ]
        video_args, accel_label = ffmpeg_video_args(for_streaming=True)
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-nostdin",
            *input_args,
            "-i",
            stream_url,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-sn",
            *video_args,
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ac",
            "2",
            "-f",
            "hls",
            "-hls_time",
            "4",
            "-hls_list_size",
            "0",
            "-hls_playlist_type",
            "event",
            "-hls_flags",
            "append_list+independent_segments",
            "-hls_segment_filename",
            str(session_dir / "segment_%03d.ts"),
            str(playlist),
        ]
        process = subprocess.Popen(
            command,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        ACTIVE_TRANSCODES[session_id] = {
            "item_id": item_id,
            "dir": str(session_dir),
            "process": process,
            "started_at": time.time(),
            "log_path": str(log_path),
            "log_handle": log_handle,
            "session_type": "stream",
            "accel_label": accel_label,
        }

    deadline = time.time() + 20
    while time.time() < deadline:
        if playlist.exists() and playlist.stat().st_size > 0:
            try:
                playlist_text = playlist.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                playlist_text = ""
            if playlist_text.count("#EXTINF:") >= 3:
                return {
                    "session_id": session_id,
                    "playlist_url": f"/play/session/{session_id}/index.m3u8",
                    "accel_label": accel_label,
                }
        if process.poll() is not None:
            break
        time.sleep(0.5)

    try:
        log_text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        log_text = ""
    detail = log_text.strip().splitlines()[-1] if log_text.strip() else "ffmpeg could not prepare the stream"
    raise HTTPException(502, f"Browser transcoding failed: {detail}")


def ensure_vod_session(item_id: str, stream_url: str) -> dict[str, Any]:
    cleanup_transcode_sessions()
    TRANSCODE_ROOT.mkdir(parents=True, exist_ok=True)
    session_id = f"vod_{item_id}"
    session_dir = TRANSCODE_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    playlist_path = session_dir / "index.m3u8"
    log_path = session_dir / "ffmpeg.log"
    done_path = session_dir / ".complete"

    with TRANSCODE_LOCK:
        existing = ACTIVE_TRANSCODES.get(session_id)
        if done_path.exists() and vod_playlist_ready(playlist_path, minimum_segments=1) and not existing:
            return {
                "session_id": session_id,
                "status": "ready",
                "playlist_url": f"/play/vod/{item_id}/index.m3u8",
                "accel_label": "Unknown",
            }
        if existing:
            process = existing["process"]
            return_code = process.poll()
            if return_code is None:
                return {
                    "session_id": session_id,
                    "status": "processing",
                    "playlist_url": f"/play/vod/{item_id}/index.m3u8",
                    "accel_label": existing.get("accel_label", "Unknown"),
                }
            ACTIVE_TRANSCODES.pop(session_id, None)
            log_handle = existing.get("log_handle")
            if log_handle:
                try:
                    log_handle.close()
                except OSError:
                    pass
            if return_code == 0 and vod_playlist_ready(playlist_path, minimum_segments=1):
                done_path.write_text(now_iso(), encoding="utf-8")
                return {
                    "session_id": session_id,
                    "status": "ready",
                    "playlist_url": f"/play/vod/{item_id}/index.m3u8",
                    "accel_label": existing.get("accel_label", "Unknown"),
                }
            retry_count = int(existing.get("retry_count", 0))
            if should_retry_vod_start(log_path, playlist_path, retry_count):
                done_path.unlink(missing_ok=True)
                if playlist_path.exists():
                    playlist_path.unlink(missing_ok=True)
                for segment in session_dir.glob("segment_*.ts"):
                    segment.unlink(missing_ok=True)
                process, log_handle, accel_label = start_vod_process(session_dir, stream_url)
                ACTIVE_TRANSCODES[session_id] = {
                    "item_id": item_id,
                    "dir": str(session_dir),
                    "process": process,
                    "started_at": time.time(),
                    "log_path": str(log_path),
                    "log_handle": log_handle,
                    "session_type": "vod",
                    "accel_label": accel_label,
                    "retry_count": retry_count + 1,
                }
                return {
                    "session_id": session_id,
                    "status": "processing",
                    "playlist_url": f"/play/vod/{item_id}/index.m3u8",
                    "accel_label": accel_label,
                }
            done_path.unlink(missing_ok=True)
            if playlist_path.exists():
                playlist_path.unlink(missing_ok=True)
            for segment in session_dir.glob("segment_*.ts"):
                segment.unlink(missing_ok=True)
            return {
                "session_id": session_id,
                "status": "failed",
                "detail": "VOD build failed before the movie finished. The source stream was interrupted.",
            }

        if playlist_path.exists() and not done_path.exists():
            playlist_path.unlink(missing_ok=True)
        for segment in session_dir.glob("segment_*.ts"):
            segment.unlink(missing_ok=True)
        process, log_handle, accel_label = start_vod_process(session_dir, stream_url)
        ACTIVE_TRANSCODES[session_id] = {
            "item_id": item_id,
            "dir": str(session_dir),
            "process": process,
            "started_at": time.time(),
            "log_path": str(log_path),
            "log_handle": log_handle,
            "session_type": "vod",
            "accel_label": accel_label,
            "retry_count": 0,
        }
    return {
        "session_id": session_id,
        "status": "processing",
        "playlist_url": f"/play/vod/{item_id}/index.m3u8",
        "accel_label": accel_label,
    }


def vod_session_status(item_id: str) -> dict[str, Any]:
    cleanup_transcode_sessions()
    session_id = f"vod_{item_id}"
    session_dir = TRANSCODE_ROOT / session_id
    playlist_path = session_dir / "index.m3u8"
    log_path = session_dir / "ffmpeg.log"
    done_path = session_dir / ".complete"
    playlist_url = f"/play/vod/{item_id}/index.m3u8"
    segment_sizes = [segment.stat().st_size for segment in session_dir.glob("segment_*.ts") if segment.exists()]
    result: dict[str, Any] = {
        "session_id": session_id,
        "playlist_url": playlist_url,
        "playback_path": "Built HLS VOD",
        "accel_label": "Unknown",
        "exists": playlist_path.exists(),
        "size_bytes": (playlist_path.stat().st_size if playlist_path.exists() else 0) + sum(segment_sizes),
        "status": "missing",
        "ffmpeg_active": False,
        "stalled": False,
    }
    with TRANSCODE_LOCK:
        existing = ACTIVE_TRANSCODES.get(session_id)
        if existing:
            process = existing["process"]
            return_code = process.poll()
            result["ffmpeg_active"] = return_code is None
            result["started_at"] = existing.get("started_at")
            result["accel_label"] = existing.get("accel_label", "Unknown")
            if return_code is None:
                result["status"] = "processing"
            elif return_code == 0 and done_path.exists() and vod_playlist_ready(playlist_path, minimum_segments=1):
                result["status"] = "ready"
            else:
                result["status"] = "failed"
                result["detail"] = "VOD build failed before the movie finished."

    if result["status"] == "missing":
        if done_path.exists() and vod_playlist_ready(playlist_path, minimum_segments=1):
            result["status"] = "ready"
        elif vod_playlist_ready(playlist_path, minimum_segments=1):
            result["status"] = "partial"
        elif log_path.exists():
            result["status"] = "failed"


    if playlist_path.exists():
        modified_at = max(
            [playlist_path.stat().st_mtime]
            + [segment.stat().st_mtime for segment in session_dir.glob("segment_*.ts") if segment.exists()]
        )
        result["updated_at"] = modified_at
        result["stalled"] = result["status"] == "processing" and (time.time() - modified_at) > 120
        result["can_play_while_building"] = vod_playlist_ready(playlist_path, minimum_segments=2)

    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
        except OSError:
            lines = []
        if lines:
            result["last_log_line"] = lines[-1]
            if result["status"] == "failed" and "detail" not in result:
                result["detail"] = lines[-1]

    return result


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
            print(f"M3U fetch: status={response.status}, bytes={len(raw)}, url={url}")
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
    """Return the effective settings. Values are masked unless ``reveal``."""
    session = session_from_request(request)
    csrf = session.get("csrf") if session else None
    keys: dict[str, Any] = {}
    for key in settings.UI_KEYS:
        value = settings.effective_value(key)
        is_secret = key != "METADATA_LANGUAGE"
        keys[key] = {
            "set": bool(value),
            "value": value if (not is_secret or (reveal and value)) else _mask(value),
        }
    return {"keys": keys, "csrf": csrf}


@app.put("/api/admin/settings")
async def admin_put_settings(
    request: Request,
    body: dict[str, Any],
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, bool]:
    """Apply settings updates. ``null`` or empty string removes a value.

    Updates land in ``DATA_DIR/.env`` (mode 0600) and the running process,
    so they take effect immediately; the systemd units pick them up at the
    next restart via the ``EnvironmentFile``.
    """
    updates: dict[str, str | None] = {}
    for key in settings.UI_KEYS:
        if key not in body:
            continue
        raw = body.get(key)
        value = str(raw).strip() if raw is not None else ""
        updates[key] = value if value else None
    settings.apply_updates(updates)
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


@app.get("/settings", response_class=HTMLResponse)
def settings_page() -> str:
    return SETTINGS_HTML


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.get("/series/{series_id}", response_class=HTMLResponse)
def series_page(series_id: str) -> str:
    return HTML


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
) -> dict[str, Any]:
    await async_init_db()
    async with read_db() as conn:
        last_refresh = await async_get_state(conn, "last_refresh")
        new_since = await async_new_since_for_window(conn, new_window)
        trending_ids = await async_trending_library_ids(conn)
        popular_ids = await async_popular_library_ids(conn)
        upcoming_snapshot = await async_get_upcoming_snapshot(conn)

        # Unified view: one row per non-series item and one row per series group.
        # Series aggregates are pre-computed in series_groups for speed.
        visible_items_cte = """
        WITH visible_items AS (
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
            CASE WHEN series_groups.is_watched = 1 OR series_groups.watched_episode_count > 0 THEN 1 ELSE 0 END AS is_watched,
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
        """
        cte_params = [new_since, new_since]

        async def _count_visible(where: str = "1 = 1", params: list[Any] | None = None) -> int:
            row = await (await conn.execute(
                f"{visible_items_cte} SELECT COUNT(*) AS count FROM visible_items WHERE {where}",
                [*cte_params, *(params or [])],
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
                f"{visible_items_cte} SELECT kind, COUNT(*) AS count FROM visible_items GROUP BY kind",
                cte_params,
            )).fetchall()
            kind_counts = {row["kind"]: row["count"] for row in kind_count_rows}
            new_count = await _count_visible("is_new = 1")
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
                    "favorites": await _count_visible("is_favorite = 1"),
                    "watched": await _count_visible("is_watched = 1"),
                    "lastWatched": await async_last_watched_count(conn),
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
                "(visible_items.title LIKE ? OR visible_items.source_title LIKE ? OR visible_items.group_name LIKE ? OR visible_items.metadata_title LIKE ?)"
            )
            like = f"%{q}%"
            params.extend([like, like, like, like])
        if kind:
            clauses.append("visible_items.kind = ?")
            params.append(kind)
        if group:
            clauses.append("visible_items.group_name = ?")
            params.append(group)
        if section == "favorites":
            clauses.append("visible_items.is_favorite = 1")
        elif section == "watched":
            clauses.append("visible_items.is_watched = 1")
        elif section == "new":
            clauses.append("visible_items.is_new = 1")
        elif section == "trending":
            clauses.append("visible_items.kind = 'movie'")
            if trending_ids["movie_ids"]:
                placeholders = ",".join("?" for _ in trending_ids["movie_ids"])
                clauses.append(f"visible_items.id IN ({placeholders})")
                params.extend(sorted(trending_ids["movie_ids"]))
            else:
                clauses.append("1 = 0")
        elif section == "popular":
            clauses.append("visible_items.kind = 'movie'")
            if popular_ids["movie_ids"]:
                placeholders = ",".join("?" for _ in popular_ids["movie_ids"])
                clauses.append(f"visible_items.id IN ({placeholders})")
                params.extend(sorted(popular_ids["movie_ids"]))
            else:
                clauses.append("1 = 0")
        where = " AND ".join(clauses)

        order_by = "visible_items.is_favorite DESC, visible_items.added_at DESC, visible_items.title COLLATE NOCASE"
        if sort == "title":
            order_by = "visible_items.is_favorite DESC, visible_items.title COLLATE NOCASE"
        elif sort == "rating":
            order_by = "visible_items.is_favorite DESC, COALESCE(visible_items.rating, 0) DESC, visible_items.title COLLATE NOCASE"
        elif sort == "release":
            order_by = "visible_items.is_favorite DESC, COALESCE(visible_items.release_date, '') DESC, visible_items.title COLLATE NOCASE"
        elif sort == "new":
            order_by = "visible_items.is_new DESC, visible_items.added_at DESC, visible_items.title COLLATE NOCASE"
        elif section == "watched" or sort == "watched":
            order_by = "visible_items.is_favorite DESC, COALESCE(visible_items.watched_at, '') DESC, visible_items.title COLLATE NOCASE"

        total = await _count_visible()
        matched = await _count_visible(where, params)
        rows = await (await conn.execute(
            f"""
            {visible_items_cte}
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
              is_favorite,
              is_watched,
              watched_at,
              is_new,
              metadata_title,
              release_date,
              rating,
              description,
              poster_url,
              episode_count,
              season_count,
              watched_episode_count
            FROM visible_items
            WHERE {where}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            [*cte_params, *params, limit, offset],
        )).fetchall()
        group_rows = await (await conn.execute(
            f"{visible_items_cte} SELECT DISTINCT group_name FROM visible_items WHERE group_name != 'Uncategorized' AND group_name != '' ORDER BY group_name",
            cte_params,
        )).fetchall()
        groups = [row["group_name"] for row in group_rows]
        kind_count_rows = await (await conn.execute(
            f"{visible_items_cte} SELECT kind, COUNT(*) AS count FROM visible_items GROUP BY kind",
            cte_params,
        )).fetchall()
        kind_counts = {row["kind"]: row["count"] for row in kind_count_rows}
        new_count = await _count_visible("is_new = 1")
        return {
            "items": [dict(row) for row in rows],
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
                "favorites": await _count_visible("is_favorite = 1"),
                "watched": await _count_visible("is_watched = 1"),
                "lastWatched": await async_last_watched_count(conn),
                "new": new_count,
                "trending": len(trending_ids["movie_ids"]),
                "popular": len(popular_ids["movie_ids"]),
                "upcoming": len(upcoming_snapshot.get("items", [])),
            },
        }


@app.post("/api/refresh", dependencies=[Depends(require_api_key)])
async def refresh() -> dict[str, Any]:
    await async_init_db()
    m3u_url = settings.effective_value("M3U_URL")
    if not m3u_url:
        config_path = APP_DIR / "config.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                m3u_url = (config.get("m3u_url") or "").strip()
            except (json.JSONDecodeError, OSError):
                pass
    if not m3u_url:
        raise HTTPException(400, "M3U_URL is missing in /var/lib/apps/m3u-library/.env and config.json")
    raw_text = await asyncio.to_thread(fetch_text, m3u_url, None, 120, True)
    parsed = await asyncio.to_thread(parse_m3u, raw_text)
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
) -> dict[str, Any]:
    await async_init_db()
    async with read_db() as conn:
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
        if section == "favorites":
            clauses.append("is_favorite = 1")
        elif section == "watched":
            clauses.append("(is_watched = 1 OR watched_episode_count > 0)")
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
                "SELECT COUNT(*) AS count FROM series_groups WHERE episode_count > 0 AND (is_watched = 1 OR watched_episode_count > 0)"
            )).fetchone())["count"],
            "lastWatched": 0,
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


def _last_watched_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    movie_rows = conn.execute(
        """
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
          0 AS is_new,
          metadata.title AS metadata_title,
          metadata.release_date,
          metadata.rating,
          metadata.description,
          metadata.poster_url,
          NULL AS episode_count,
          NULL AS season_count,
          items.watched_at
        FROM items
        LEFT JOIN metadata ON metadata.item_id = items.id
        WHERE items.available = 1
          AND items.kind != 'series'
          AND items.is_watched = 1
          AND items.watched_at IS NOT NULL
        """
    ).fetchall()
    series_rows = conn.execute(
        """
        SELECT
          series_groups.id,
          series_groups.title,
          series_groups.title AS source_title,
          MAX(items.group_name) AS group_name,
          'series' AS kind,
          series_groups.poster_url AS logo,
          '' AS stream_url,
          MAX(items.added_at) AS added_at,
          MAX(items.last_seen_at) AS last_seen_at,
          series_groups.is_favorite,
          1 AS is_watched,
          0 AS is_new,
          NULL AS metadata_title,
          series_groups.release_date,
          series_groups.rating,
          series_groups.description,
          series_groups.poster_url,
          COUNT(items.id) AS episode_count,
          COUNT(DISTINCT COALESCE(items.season_number, 0)) AS season_count,
          series_groups.watched_at AS series_watched_at,
          MAX(items.watched_at) AS max_episode_watched_at
        FROM series_groups
        JOIN items ON items.series_id = series_groups.id
        WHERE items.available = 1
          AND (series_groups.is_watched = 1 OR items.is_watched = 1)
        GROUP BY series_groups.id
        HAVING series_groups.watched_at IS NOT NULL OR MAX(items.watched_at) IS NOT NULL
        """
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in movie_rows:
        item = dict(row)
        item["is_external"] = False
        items.append(item)
    for row in series_rows:
        item = dict(row)
        item["watched_at"] = max(
            (row["series_watched_at"] or ""),
            (row["max_episode_watched_at"] or ""),
        ) or None
        item.pop("series_watched_at", None)
        item.pop("max_episode_watched_at", None)
        item["is_external"] = False
        items.append(item)
    items.sort(key=lambda item: item.get("watched_at") or "", reverse=True)
    return items


@app.get("/api/last-watched")
async def list_last_watched(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    await async_init_db()
    async with read_db() as conn:
        items = await async_last_watched_rows(conn)
    total = len(items)
    items = items[offset : offset + limit]
    return {"items": items, "total": total, "matched": total, "limit": limit, "offset": offset}


def last_watched_count(conn: sqlite3.Connection) -> int:
    return len(_last_watched_rows(conn))


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
    await async_set_state(conn, "tmdb_trending_week_cache", snapshot)
    return snapshot


async def async_get_popular_snapshot(conn: aiosqlite.Connection) -> dict[str, Any]:
    cache = await async_get_tmdb_cache(conn, "tmdb_popular_cache")
    if cache:
        return cache
    language = settings.effective_value("METADATA_LANGUAGE", "en-US")
    snapshot = await async_build_tmdb_library_snapshot("movie/popular", "tv/popular", language)
    await async_set_state(conn, "tmdb_popular_cache", snapshot)
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
    await async_set_state(conn, "tmdb_upcoming_cache", snapshot)
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


async def async_last_watched_rows(conn: aiosqlite.Connection) -> list[dict[str, Any]]:
    cursor = await conn.execute(
        """
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
          0 AS is_new,
          metadata.title AS metadata_title,
          metadata.release_date,
          metadata.rating,
          metadata.description,
          metadata.poster_url,
          NULL AS episode_count,
          NULL AS season_count,
          items.watched_at
        FROM items
        LEFT JOIN metadata ON metadata.item_id = items.id
        WHERE items.available = 1
          AND items.kind != 'series'
          AND items.is_watched = 1
          AND items.watched_at IS NOT NULL
        """
    )
    movie_rows = await cursor.fetchall()
    cursor = await conn.execute(
        """
        SELECT
          series_groups.id,
          series_groups.title,
          series_groups.title AS source_title,
          MAX(items.group_name) AS group_name,
          'series' AS kind,
          series_groups.poster_url AS logo,
          '' AS stream_url,
          MAX(items.added_at) AS added_at,
          MAX(items.last_seen_at) AS last_seen_at,
          series_groups.is_favorite,
          1 AS is_watched,
          0 AS is_new,
          NULL AS metadata_title,
          series_groups.release_date,
          series_groups.rating,
          series_groups.description,
          series_groups.poster_url,
          COUNT(items.id) AS episode_count,
          COUNT(DISTINCT COALESCE(items.season_number, 0)) AS season_count,
          series_groups.watched_at AS series_watched_at,
          MAX(items.watched_at) AS max_episode_watched_at
        FROM series_groups
        JOIN items ON items.series_id = series_groups.id
        WHERE items.available = 1
          AND (series_groups.is_watched = 1 OR items.is_watched = 1)
        GROUP BY series_groups.id
        HAVING series_groups.watched_at IS NOT NULL OR MAX(items.watched_at) IS NOT NULL
        """
    )
    series_rows = await cursor.fetchall()
    items: list[dict[str, Any]] = []
    for row in movie_rows:
        item = dict(row)
        item["is_external"] = False
        items.append(item)
    for row in series_rows:
        item = dict(row)
        item["watched_at"] = max(
            (row["series_watched_at"] or ""),
            (row["max_episode_watched_at"] or ""),
        ) or None
        item.pop("series_watched_at", None)
        item.pop("max_episode_watched_at", None)
        item["is_external"] = False
        items.append(item)
    items.sort(key=lambda item: item.get("watched_at") or "", reverse=True)
    return items


async def async_last_watched_count(conn: aiosqlite.Connection) -> int:
    return len(await async_last_watched_rows(conn))


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


@app.get("/play/proxy/{id}")
def proxy_playback(id: str, request: Request) -> Response:
    init_db()
    with db() as conn:
        item = conn.execute("SELECT stream_url FROM items WHERE id = ?", (id,)).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")
        stream_url = item["stream_url"]
    if not is_http_stream(stream_url):
        raise HTTPException(400, "Proxy playback only supports HTTP/HTTPS sources")

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    upstream_request = urllib.request.Request(stream_url, headers=headers)
    try:
        upstream = urllib.request.urlopen(upstream_request, timeout=30)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip() or str(exc)
        raise HTTPException(exc.code, detail)
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"Proxy playback failed: {exc.reason}")

    response_headers: dict[str, str] = {
        "Accept-Ranges": upstream.headers.get("Accept-Ranges", "bytes"),
    }
    for key in ("Content-Length", "Content-Range", "Content-Type", "Last-Modified", "ETag"):
        value = upstream.headers.get(key)
        if value:
            response_headers[key] = value

    media_type = upstream.headers.get_content_type() or "video/mp4"

    def iterator():
        try:
            while True:
                chunk = upstream.read(1024 * 256)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        iterator(),
        status_code=upstream.getcode(),
        media_type=media_type,
        headers=response_headers,
    )


@app.post("/api/play/{id}/session")
def create_browser_session(id: str) -> dict[str, Any]:
    init_db()
    with db() as conn:
        item = conn.execute(
            "SELECT id, title, stream_url, kind FROM items WHERE id = ?",
            (id,),
        ).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")
        if item["kind"] == "movie":
            mode = browser_playback_mode(item["stream_url"])
            if mode == "native":
                return {
                    "mode": "proxy-native",
                    "status": "ready",
                    "video_url": f"/play/proxy/{item['id']}",
                    "playback_path": "Proxy MP4",
                }
            if not ffmpeg_available():
                raise HTTPException(503, "ffmpeg is not installed on the server yet")
            session = ensure_vod_session(item["id"], item["stream_url"])
            return {"mode": "vod-hls", "playback_path": "Built HLS VOD", **session}
        mode = browser_playback_mode(item["stream_url"])
        if mode == "hls":
            return {"mode": "hls-direct", "stream_url": item["stream_url"], "playback_path": "Direct HLS"}
        if mode == "native":
            return {"mode": "native", "stream_url": item["stream_url"], "playback_path": "Direct File"}
        if not ffmpeg_available():
            raise HTTPException(503, "ffmpeg is not installed on the server yet")
        try:
            session = ensure_transcode_session(item["id"], item["stream_url"])
            return {"mode": "transcode-hls", "playback_path": "Transcoded HLS", **session}
        except HTTPException as exc:
            if exc.status_code != 502 or item["kind"] == "live":
                raise
            session = ensure_vod_session(item["id"], item["stream_url"])
        return {"mode": "vod-hls", "playback_path": "Built HLS VOD", **session}


@app.post("/api/play/{id}/vod-session")
def create_vod_browser_session(id: str) -> dict[str, Any]:
    init_db()
    with db() as conn:
        item = conn.execute(
            "SELECT id, title, stream_url FROM items WHERE id = ?",
            (id,),
        ).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")
        mode = browser_playback_mode(item["stream_url"])
        if mode == "native":
            return {
                "mode": "proxy-native",
                "status": "ready",
                "video_url": f"/play/proxy/{item['id']}",
                "playback_path": "Proxy MP4",
            }
        if not ffmpeg_available():
            raise HTTPException(503, "ffmpeg is not installed on the server yet")
        session = ensure_vod_session(item["id"], item["stream_url"])
        return {"mode": "vod-hls", "playback_path": "Built HLS VOD", **session}


@app.get("/api/play/{id}/vod-status")
def get_vod_browser_status(id: str) -> dict[str, Any]:
    init_db()
    with db() as conn:
        item = conn.execute("SELECT id FROM items WHERE id = ?", (id,)).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")
    return vod_session_status(id)


@app.get("/api/play/{id}/probe")
def probe_playback_source(id: str) -> dict[str, Any]:
    init_db()
    with db() as conn:
        item = conn.execute(
            "SELECT id, title, stream_url FROM items WHERE id = ?",
            (id,),
        ).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")
    probe = probe_streams(item["stream_url"])
    return {
        "id": item["id"],
        "title": item["title"],
        **probe,
    }


@app.get("/play/session/{session_id}/{name:path}")
def transcode_session_file(session_id: str, name: str) -> Response:
    cleanup_transcode_sessions()
    safe_name = Path(name).name
    session_dir = TRANSCODE_ROOT / session_id
    file_path = session_dir / safe_name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "Transcode file not ready")
    media_type = None
    if file_path.suffix == ".m3u8":
        media_type = "application/vnd.apple.mpegurl"
    elif file_path.suffix == ".ts":
        media_type = "video/mp2t"
    return FileResponse(file_path, media_type=media_type)


@app.get("/play/vod/{item_id}/{name:path}")
def vod_session_file(item_id: str, name: str) -> Response:
    cleanup_transcode_sessions()
    safe_name = Path(name).name
    session_dir = TRANSCODE_ROOT / f"vod_{item_id}"
    file_path = session_dir / safe_name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "VOD file not ready")
    media_type = None
    if file_path.suffix == ".m3u8":
        media_type = "application/vnd.apple.mpegurl"
    elif file_path.suffix == ".ts":
        media_type = "video/mp2t"
    elif file_path.suffix == ".vtt":
        media_type = "text/vtt"
    return FileResponse(file_path, media_type=media_type)


@app.get("/play/subtitle/{item_id}/{stream_index}.vtt")
def vod_subtitle_file(item_id: str, stream_index: int) -> Response:
    init_db()
    with db() as conn:
        item = conn.execute(
            "SELECT id, stream_url FROM items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")
    probe = probe_streams(item["stream_url"])
    track = next((track for track in subtitle_candidates_from_probe(probe) if int(track["index"]) == stream_index), None)
    if not track:
        raise HTTPException(404, "Subtitle track not found or not supported for browser playback")
    session_dir = TRANSCODE_ROOT / f"vod_{item_id}"
    output_path = session_dir / f"subtitle_{stream_index}.vtt"
    extract_subtitle_to_vtt(item["stream_url"], stream_index, output_path)
    return FileResponse(output_path, media_type="text/vtt")


@app.get("/play/{id}", response_class=HTMLResponse)
def browser_player(id: str) -> str:
    init_db()
    with db() as conn:
        item = conn.execute(
            "SELECT id, title, stream_url, kind, series_id FROM items WHERE id = ?",
            (id,),
        ).fetchone()
        if not item:
            raise HTTPException(404, "Item not found")
        title = html_lib.escape(item["title"])
        stream_url = item["stream_url"]
        back_href = f"/series/{urllib.parse.quote(item['series_id'])}" if item["series_id"] else "/"
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | Browser Player</title>
  <style>
    :root {{
      --bg: #111318;
      --panel: #191d24;
      --panel-2: #242b35;
      --text: #f6f7fb;
      --muted: #aab3c2;
      --accent: #ffb84d;
      --accent-2: #72d6a1;
      --border: rgba(255,255,255,0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, "Segoe UI", system-ui, sans-serif;
      background: linear-gradient(180deg, #0f1217 0%, #151922 100%);
      color: var(--text);
    }}
    .page {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }}
    .topbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 18px;
    }}
    .title-wrap h1 {{
      margin: 0;
      font-size: 1.6rem;
      line-height: 1.2;
    }}
    .subtitle {{
      color: var(--muted);
      margin-top: 6px;
      font-size: 0.95rem;
    }}
    .actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .button, button, select {{
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      padding: 10px 14px;
      font: inherit;
    }}
    .button {{
      text-decoration: none;
      display: inline-flex;
      align-items: center;
    }}
    .button.primary {{
      background: var(--accent);
      color: #1c1300;
      border-color: transparent;
      font-weight: 700;
    }}
    .button.active-mode {{
      background: var(--accent-2);
      color: #10261a;
      border-color: transparent;
      font-weight: 700;
    }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 18px;
    }}
    .player-shell, .sidebar {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    .player-shell {{
      padding: 18px;
    }}
    video {{
      width: 100%;
      background: #000;
      border-radius: 8px;
      aspect-ratio: 16 / 9;
    }}
    .sidebar {{
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }}
    .field {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .field label {{
      color: var(--muted);
      font-size: 0.88rem;
    }}
    .status {{
      min-height: 44px;
      color: var(--muted);
      line-height: 1.45;
    }}
    .hint {{
      padding: 12px;
      border-radius: 8px;
      background: rgba(114, 214, 161, 0.08);
      border: 1px solid rgba(114, 214, 161, 0.18);
      color: #dcefe5;
      font-size: 0.92rem;
      line-height: 1.45;
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 0.9em;
    }}
    @media (max-width: 980px) {{
      .layout {{
        grid-template-columns: 1fr;
      }}
      .page {{
        padding: 16px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="topbar">
      <div class="title-wrap">
        <h1>{title}</h1>
        <div class="subtitle">Browser playback test with HLS audio and subtitle track support when the stream exposes them.</div>
      </div>
      <div class="actions">
        <a class="button" href="{html_lib.escape(back_href)}">Back</a>
        <a class="button primary" href="/watch/{urllib.parse.quote(item['id'])}.m3u">Open in PotPlayer</a>
      </div>
    </div>
    <div class="layout">
      <section class="player-shell">
        <video id="video" controls playsinline preload="metadata"></video>
      </section>
      <aside class="sidebar">
        <div class="field">
          <label>Playback</label>
          <div class="actions">
            <button id="mode-vod" type="button" class="button active-mode">VOD</button>
          </div>
        </div>
        <div class="field">
          <label>Playback path</label>
          <div class="status" id="playback-path">Detecting...</div>
        </div>
        <div class="field">
          <label for="audio-track">Audio language</label>
          <select id="audio-track" disabled>
            <option>No alternate audio detected</option>
          </select>
        </div>
        <div class="field">
          <label for="subtitle-track">Subtitles</label>
          <select id="subtitle-track" disabled>
            <option>No subtitles detected</option>
          </select>
        </div>
        <div class="field">
          <label>Status</label>
          <div class="status" id="status">Preparing player...</div>
        </div>
        <div class="field">
          <label>Detected source tracks</label>
          <div class="status" id="probe-status">Inspecting source streams...</div>
        </div>
        <div class="hint">
          If this stream does not start, the usual reasons are unsupported codecs, missing CORS headers, or a source that needs remuxing/transcoding before browsers can handle it.
        </div>
      </aside>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
  <script>
    const itemId = {json.dumps(item["id"])};
    const title = {json.dumps(item["title"])};
    const itemKind = {json.dumps(item["kind"])};
    const video = document.getElementById("video");
    const statusEl = document.getElementById("status");
    const probeStatusEl = document.getElementById("probe-status");
    const playbackPathEl = document.getElementById("playback-path");
    const vodModeButton = document.getElementById("mode-vod");
    const audioSelect = document.getElementById("audio-track");
    const subtitleSelect = document.getElementById("subtitle-track");
    let hls = null;
    let vodPollTimer = null;
    let vodAttached = false;
    let manualSubtitleTracks = [];
    let currentPlaybackPath = "Unknown";

    function setStatus(message) {{
      statusEl.textContent = message;
    }}

    function setPlaybackPath(message) {{
      currentPlaybackPath = message;
      playbackPathEl.textContent = message;
    }}

    function setProbeStatus(message) {{
      probeStatusEl.textContent = message;
    }}

    function playbackPathLabel(base, accel) {{
      if (!accel || accel === "Unknown") return base;
      return `${{base}} · ${{accel}}`;
    }}

    function formatBytes(bytes) {{
      if (!bytes) return "0 B";
      const units = ["B", "KB", "MB", "GB"];
      let value = bytes;
      let index = 0;
      while (value >= 1024 && index < units.length - 1) {{
        value /= 1024;
        index += 1;
      }}
      return `${{value.toFixed(index === 0 ? 0 : 1)}} ${{units[index]}}`;
    }}

    function formatDetectedTrack(track) {{
      const parts = [track.label];
      if (track.flags && track.flags.length) {{
        parts.push(`(${{track.flags.join(", ")}})`);
      }}
      return parts.join(" ");
    }}

    async function loadProbe() {{
      setProbeStatus("Inspecting source streams...");
      const res = await fetch(`/api/play/${{encodeURIComponent(itemId)}}/probe`, {{
        cache: "no-store"
      }});
      const data = await res.json();
      if (!res.ok) {{
        setProbeStatus(data.detail || "Could not inspect source tracks.");
        return;
      }}
      const lines = [];
      if (data.audio_tracks?.length) {{
        lines.push(`Audio: ${{data.audio_tracks.map(formatDetectedTrack).join(" ; ")}}`);
      }} else {{
        lines.push("Audio: none detected");
      }}
      if (data.subtitle_tracks?.length) {{
        lines.push(`Subtitles: ${{data.subtitle_tracks.map(formatDetectedTrack).join(" ; ")}}`);
        applyManualSubtitleTracks(data.subtitle_tracks.map(track => ({{
          index: track.index,
          language: track.language,
          label: track.label,
          default: !!track.default,
          forced: !!track.forced,
          url: `/play/subtitle/${{encodeURIComponent(itemId)}}/${{track.index}}.vtt`
        }})));
      }} else {{
        lines.push("Subtitles: none detected");
      }}
      setProbeStatus(lines.join(" | "));
    }}

    function setMode(mode) {{
      vodModeButton.classList.toggle("active-mode", mode === "vod");
    }}

    function stopVodPolling() {{
      if (vodPollTimer) {{
        clearTimeout(vodPollTimer);
        vodPollTimer = null;
      }}
    }}

    function resetPlayer() {{
      stopVodPolling();
      vodAttached = false;
      manualSubtitleTracks = [];
      if (hls) {{
        hls.destroy();
        hls = null;
      }}
      video.pause();
      video.removeAttribute("src");
      video.load();
      setPlaybackPath("Detecting...");
      audioSelect.disabled = true;
      subtitleSelect.disabled = true;
      audioSelect.innerHTML = "<option>No alternate audio detected</option>";
      subtitleSelect.innerHTML = "<option>No subtitles detected</option>";
      for (const trackEl of Array.from(video.querySelectorAll("track[data-manual-subtitle='1']"))) {{
        trackEl.remove();
      }}
    }}

    function fillSelect(select, options, disabledLabel) {{
      select.innerHTML = "";
      if (!options.length) {{
        select.disabled = true;
        const option = document.createElement("option");
        option.textContent = disabledLabel;
        select.appendChild(option);
        return;
      }}
      select.disabled = false;
      for (const entry of options) {{
        const option = document.createElement("option");
        option.value = String(entry.value);
        option.textContent = entry.label;
        if (entry.selected) option.selected = true;
        select.appendChild(option);
      }}
    }}

    function updateAudioTracks() {{
      if (!hls) return;
      const tracks = (hls.audioTracks || []).map((track, index) => {{
        const parts = [track.name || `Track ${{index + 1}}`];
        if (track.lang) parts.push(track.lang);
        return {{
          value: index,
          label: parts.join(" | "),
          selected: hls.audioTrack === index
        }};
      }});
      fillSelect(audioSelect, tracks, "No alternate audio detected");
    }}

    function updateSubtitleTracks() {{
      if (!hls) return;
      const tracks = [{{
        value: -1,
        label: "Off",
        selected: hls.subtitleTrack === -1
      }}];
      for (const [index, track] of (hls.subtitleTracks || []).entries()) {{
        const parts = [track.name || `Subtitle ${{index + 1}}`];
        if (track.lang) parts.push(track.lang);
        tracks.push({{
          value: index,
          label: parts.join(" | "),
          selected: hls.subtitleTrack === index
        }});
      }}
      if (tracks.length > 1) {{
        fillSelect(subtitleSelect, tracks, "No subtitles detected");
        return;
      }}
      if (manualSubtitleTracks.length) {{
        const manualOptions = [{{
          value: -1,
          label: "Off",
          selected: !Array.from(video.textTracks || []).some(track => track.mode === "showing")
        }}, ...manualSubtitleTracks.map((track, index) => ({{
          value: index,
          label: track.label,
          selected: Array.from(video.textTracks || [])[index]?.mode === "showing"
        }}))];
        fillSelect(subtitleSelect, manualOptions, "No subtitles detected");
        return;
      }}
      fillSelect(subtitleSelect, [], "No subtitles detected");
    }}

    audioSelect.addEventListener("change", () => {{
      if (hls) {{
        hls.audioTrack = Number(audioSelect.value);
        return;
      }}
      const nativeTracks = video.audioTracks;
      if (!nativeTracks) return;
      const selected = Number(audioSelect.value);
      for (let i = 0; i < nativeTracks.length; i += 1) {{
        nativeTracks[i].enabled = i === selected;
      }}
    }});

    subtitleSelect.addEventListener("change", () => {{
      if (hls && (hls.subtitleTracks || []).length) {{
        hls.subtitleTrack = Number(subtitleSelect.value);
        return;
      }}
      const selected = Number(subtitleSelect.value);
      const nativeTracks = Array.from(video.textTracks || []);
      for (const [index, track] of nativeTracks.entries()) {{
        if (selected === -1) {{
          track.mode = "disabled";
        }} else {{
          track.mode = index === selected ? "showing" : "disabled";
        }}
      }}
    }});

    function updateNativeTracks() {{
      const audioTracks = video.audioTracks ? Array.from(video.audioTracks) : [];
      const audioOptions = audioTracks.map((track, index) => {{
        const label = track.label || track.language || `Audio ${{index + 1}}`;
        return {{
          value: index,
          label,
          selected: !!track.enabled
        }};
      }});
      fillSelect(audioSelect, audioOptions, audioTracks.length ? "No alternate audio detected" : "Browser does not expose audio tracks");

      const textTracks = Array.from(video.textTracks || []).filter(track => !track.kind || ["subtitles", "captions"].includes(track.kind));
      const subtitleOptions = textTracks.length
        ? [{{
            value: -1,
            label: "Off",
            selected: !textTracks.some(track => track.mode === "showing")
          }}, ...textTracks.map((track, index) => ({{
            value: index,
            label: track.label || track.language || `Subtitle ${{index + 1}}`,
            selected: track.mode === "showing"
          }}))]
        : [];
      fillSelect(subtitleSelect, subtitleOptions, textTracks.length ? "No subtitles detected" : "Browser does not expose subtitle tracks");
    }}

    function applyManualSubtitleTracks(tracks) {{
      manualSubtitleTracks = tracks || [];
      for (const trackEl of Array.from(video.querySelectorAll("track[data-manual-subtitle='1']"))) {{
        trackEl.remove();
      }}
      for (const [index, track] of manualSubtitleTracks.entries()) {{
        const element = document.createElement("track");
        element.kind = "subtitles";
        element.label = track.label || `Subtitle ${{index + 1}}`;
        element.srclang = track.language || "und";
        element.src = track.url;
        element.default = !!track.default && index === 0;
        element.dataset.manualSubtitle = "1";
        video.appendChild(element);
      }}
      setTimeout(() => {{
        updateNativeTracks();
        updateSubtitleTracks();
      }}, 0);
    }}

    function attachNative(streamUrl, playbackPath = "Native") {{
      setPlaybackPath(playbackPath);
      setStatus("Using your browser's native player. Track switching depends on what the browser exposes.");
      video.src = streamUrl;
      video.addEventListener("loadedmetadata", () => {{
        updateNativeTracks();
        setStatus("Playback ready.");
      }}, {{ once: true }});
      video.addEventListener("error", () => setStatus("Native playback failed. The stream may need HLS support, CORS permission, or transcoding."));
    }}

    function attachHls(streamUrl, transcoded, playbackPath = "HLS") {{
      setPlaybackPath(playbackPath);
      hls = new Hls({{
        enableWorker: true,
        renderTextTracksNatively: false
      }});
      hls.loadSource(streamUrl);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, (_, data) => {{
        updateAudioTracks();
        updateSubtitleTracks();
        setStatus(`Manifest loaded. ${{data.levels?.length || 0}} quality level(s) detected.`);
      }});
      hls.on(Hls.Events.AUDIO_TRACKS_UPDATED, updateAudioTracks);
      hls.on(Hls.Events.AUDIO_TRACK_SWITCHED, updateAudioTracks);
      hls.on(Hls.Events.SUBTITLE_TRACKS_UPDATED, updateSubtitleTracks);
      hls.on(Hls.Events.SUBTITLE_TRACK_SWITCH, updateSubtitleTracks);
      hls.on(Hls.Events.ERROR, (_, data) => {{
        const fatal = data?.fatal ? " Fatal." : "";
        setStatus(`Playback error.${{fatal}} ${{data?.details || "Unknown player error"}}`);
      }});
      video.addEventListener("loadedmetadata", () => setStatus(transcoded ? "Playback ready. Server transcoding is active." : "Playback ready."), {{ once: true }});
    }}

    async function bootstrapVod() {{
      resetPlayer();
      setMode("vod");
      setStatus("Preparing VOD file. This can take a while for full-length items...");
      const res = await fetch(`/api/play/${{encodeURIComponent(itemId)}}/vod-session`, {{
        method: "POST",
        cache: "no-store"
      }});
      const data = await res.json();
      if (!res.ok) {{
        setStatus(data.detail || "Could not prepare VOD playback.");
        return;
      }}
      setPlaybackPath(playbackPathLabel(data.playback_path || "VOD", data.accel_label));
      if (Array.isArray(data.subtitle_tracks) && data.subtitle_tracks.length) {{
        applyManualSubtitleTracks(data.subtitle_tracks);
      }}
      if (data.status === "ready") {{
        vodAttached = true;
        attachHls(data.playlist_url, false, playbackPathLabel(data.playback_path || "VOD", data.accel_label));
        setStatus("VOD ready.");
        return;
      }}
      await pollVodStatus();
    }}

    async function pollVodStatus() {{
      const res = await fetch(`/api/play/${{encodeURIComponent(itemId)}}/vod-status`, {{
        cache: "no-store"
      }});
      const data = await res.json();
      if (!res.ok) {{
        setStatus(data.detail || "Could not load VOD status.");
        return;
      }}
      setPlaybackPath(playbackPathLabel(data.playback_path || "VOD", data.accel_label));
      if (Array.isArray(data.subtitle_tracks) && data.subtitle_tracks.length) {{
        applyManualSubtitleTracks(data.subtitle_tracks);
      }}
      if (data.status === "ready") {{
        vodAttached = true;
        attachHls(data.playlist_url, false, playbackPathLabel(data.playback_path || "VOD", data.accel_label));
        setStatus(`VOD ready. ${{formatBytes(data.size_bytes || 0)}} prepared.`);
        return;
      }}
      if (data.status === "failed") {{
        setStatus(data.detail || "VOD build failed.");
        return;
      }}
      if (!vodAttached && data.can_play_while_building && data.playlist_url) {{
        vodAttached = true;
        attachHls(data.playlist_url, false, playbackPathLabel(data.playback_path || "VOD", data.accel_label));
      }}
      if (data.status === "processing") {{
        const sizeText = formatBytes(data.size_bytes || 0);
        if (data.stalled) {{
          setStatus(`VOD appears stalled at ${{sizeText}}. The source may be unstable right now.`);
        }} else if (data.can_play_while_building) {{
          setStatus(`VOD is playable while still building... ${{sizeText}} prepared so far.`);
        }} else {{
          setStatus(`Building VOD in the background... ${{sizeText}} written so far.`);
        }}
      }} else if (data.status === "partial") {{
        if (data.can_play_while_building) {{
          setStatus(`Partial VOD is already playable. ${{formatBytes(data.size_bytes || 0)}} prepared so far.`);
        }} else {{
          setStatus(`A partial VOD file exists (${{formatBytes(data.size_bytes || 0)}}), but the build has not completed.`);
        }}
      }} else {{
        setStatus("Waiting for VOD build to start...");
      }}
      vodPollTimer = setTimeout(() => {{
        pollVodStatus().catch(error => {{
          setStatus(error.message || "Could not continue VOD status checks.");
        }});
      }}, 4000);
    }}

    vodModeButton.addEventListener("click", () => {{
      bootstrapVod().catch(error => {{
        setStatus(error.message || "Could not start VOD playback.");
      }});
    }});

    bootstrapVod().catch(error => {{
      setStatus(error.message || "Could not start browser playback.");
    }});
    loadProbe().catch(error => {{
      setProbeStatus(error.message || "Could not inspect source tracks.");
    }});

    document.title = `${{title}} | Browser Player`;
  </script>
</body>
</html>"""


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>M3U Library</title>
  <style>
    :root {
      --bg: #f2efe8;
      --bg-strong: #e8e0d1;
      --panel: rgba(255, 251, 244, 0.9);
      --panel-solid: #fffaf2;
      --text: #1f2430;
      --muted: #6c746f;
      --line: #ddd1bc;
      --accent: #a74f2f;
      --accent-strong: #8d3c21;
      --highlight: #d4a62a;
      --success: #2f7b58;
      --shadow: 0 16px 40px rgba(78, 55, 24, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Trebuchet MS", "Segoe UI", system-ui, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(212, 166, 42, 0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(167, 79, 47, 0.16), transparent 24%),
        linear-gradient(180deg, #f8f4ec 0%, var(--bg) 40%, #ece3d4 100%);
      min-height: 100vh;
    }
    *:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    header {
      position: sticky;
      top: 0;
      z-index: 5;
      backdrop-filter: blur(18px);
      background: rgba(248, 244, 236, 0.86);
      border-bottom: 1px solid rgba(166, 138, 93, 0.18);
    }
    .shell, main {
      max-width: 1260px;
      margin: 0 auto;
      padding: 20px 24px;
    }
    .shell {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 18px;
      align-items: center;
    }
    h1 {
      margin: 0;
      font-size: clamp(28px, 3vw, 40px);
      line-height: 1;
      letter-spacing: 0;
    }
    .subtitle {
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
    }
    .actions, .row, .card-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }
    .actions {
      flex-direction: column;
      align-items: flex-end;
      gap: 8px;
    }
    .refresh-meta {
      color: var(--muted);
      font-size: 13px;
    }
    button, select, input, .button {
      border: 1px solid var(--line);
      background: var(--panel-solid);
      color: var(--text);
      border-radius: 10px;
      font: inherit;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      padding: 0 14px;
      transition: transform 140ms ease, background 140ms ease, border-color 140ms ease, box-shadow 140ms ease;
    }
    button:hover, .button:hover, select:hover, input:hover {
      transform: translateY(-1px);
      border-color: #c59d63;
      box-shadow: 0 10px 18px rgba(66, 44, 17, 0.08);
    }
    .primary {
      cursor: pointer;
      background: var(--accent);
      color: #fff9f4;
      border-color: var(--accent);
      font-weight: 700;
    }
    .primary:hover { background: var(--accent-strong); }
    .secondary { background: var(--panel-solid); }
    .icon-button {
      width: 42px;
      min-width: 42px;
      padding: 0;
      font-size: 18px;
      border-radius: 12px;
    }
    .icon-button.active-favorite {
      background: rgba(212, 166, 42, 0.14);
      border-color: rgba(212, 166, 42, 0.55);
      color: #9c6a00;
    }
    .icon-button.active-watched {
      background: rgba(47, 123, 88, 0.14);
      border-color: rgba(47, 123, 88, 0.45);
      color: var(--success);
    }
    .pill-new {
      background: rgba(212, 166, 42, 0.18);
      border-color: rgba(212, 166, 42, 0.5);
      color: #936000;
      font-weight: 700;
    }
    .hero {
      margin-top: 18px;
      padding: 24px;
      border: 1px solid rgba(166, 138, 93, 0.18);
      border-radius: 20px;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.75), rgba(255,248,236,0.88)),
        linear-gradient(120deg, rgba(212,166,42,0.13), rgba(167,79,47,0.08));
      box-shadow: var(--shadow);
      display: grid;
      gap: 18px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .stat {
      background: rgba(255, 252, 246, 0.7);
      border: 1px solid rgba(166, 138, 93, 0.18);
      border-radius: 14px;
      padding: 14px 16px;
      min-height: 86px;
      display: grid;
      align-content: space-between;
    }
    button.stat {
      width: 100%;
      text-align: left;
      justify-items: start;
      cursor: pointer;
      min-height: 86px;
      padding: 14px 16px;
    }
    .stat.active {
      border-color: rgba(167, 79, 47, 0.45);
      background: rgba(167, 79, 47, 0.08);
      box-shadow: 0 10px 18px rgba(66, 44, 17, 0.08);
    }
    .stat-label {
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .stat-value {
      font-size: 24px;
      font-weight: 700;
    }
    .filters {
      display: grid;
      grid-template-columns: minmax(220px, 1.5fr) 160px 220px 180px;
      gap: 12px;
      margin: 18px 0;
    }
    input, select { width: 100%; }
    .status {
      color: var(--muted);
      font-size: 14px;
      min-height: 20px;
    }
    .update-banner {
      background: rgba(47, 123, 88, 0.12);
      border: 1px solid rgba(47, 123, 88, 0.35);
      color: var(--success);
      padding: 12px 16px;
      border-radius: 12px;
      margin-top: 12px;
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
    }
    .update-banner[hidden] { display: none; }
    .update-banner button {
      min-height: 32px;
      padding: 0 12px;
      font-size: 13px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(310px, 1fr));
      gap: 16px;
    }
    .item {
      display: grid;
      grid-template-columns: 112px 1fr;
      background: var(--panel);
      border: 1px solid rgba(166, 138, 93, 0.22);
      border-radius: 18px;
      overflow: hidden;
      box-shadow: var(--shadow);
      min-height: 240px;
    }
    .poster {
      background:
        linear-gradient(180deg, rgba(212,166,42,0.18), rgba(167,79,47,0.12)),
        #e9dfd2;
      min-height: 240px;
      display: grid;
      place-items: center;
      color: rgba(31, 36, 48, 0.58);
      font-weight: 700;
      letter-spacing: 0.08em;
      font-size: 12px;
    }
    .poster img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .details {
      padding: 16px;
      display: grid;
      gap: 12px;
      align-content: start;
      min-width: 0;
    }
    .card-top {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: start;
    }
    .title {
      font-size: 18px;
      font-weight: 700;
      line-height: 1.2;
      overflow-wrap: anywhere;
    }
    .meta {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }
    .source-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 4px;
    }
    .source-tag {
      width: fit-content;
      max-width: 100%;
      border: 1px solid rgba(166, 138, 93, 0.24);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 11px;
      color: var(--muted);
      background: rgba(255, 249, 239, 0.6);
      text-transform: uppercase;
      letter-spacing: 0.02em;
      overflow-wrap: anywhere;
    }
    .pill {
      width: fit-content;
      max-width: 100%;
      border: 1px solid rgba(166, 138, 93, 0.32);
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      color: var(--muted);
      background: rgba(255, 249, 239, 0.75);
    }
    .metadata {
      display: grid;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
      min-height: 68px;
    }
    .metadata-head {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
    }
    .metadata-title {
      color: var(--text);
      font-weight: 700;
    }
    .rating {
      font-weight: 700;
      color: #956300;
    }
    .card-actions {
      align-items: center;
      justify-content: space-between;
      margin-top: auto;
    }
    .action-group {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .pager {
      display: flex;
      justify-content: center;
      padding: 22px 0 8px;
    }
    .empty {
      border: 1px dashed rgba(166, 138, 93, 0.38);
      border-radius: 18px;
      color: var(--muted);
      padding: 42px 26px;
      text-align: center;
      background: rgba(255, 252, 246, 0.78);
    }
    .series-hero {
      display: grid;
      grid-template-columns: 180px minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }
    .series-hero-poster {
      min-height: 270px;
      border-radius: 18px;
      overflow: hidden;
      background: #e9dfd2;
      display: grid;
      place-items: center;
      font-weight: 700;
      color: rgba(31, 36, 48, 0.58);
    }
    .series-hero-poster img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .season-block {
      margin-top: 18px;
      border: 1px solid rgba(166, 138, 93, 0.18);
      border-radius: 18px;
      background: rgba(255, 252, 246, 0.86);
      overflow: hidden;
    }
    .season-header {
      padding: 14px 16px;
      font-weight: 700;
      border-bottom: 1px solid rgba(166, 138, 93, 0.18);
      background: rgba(245, 235, 220, 0.8);
    }
    .episode-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid rgba(166, 138, 93, 0.12);
      align-items: center;
    }
    .episode-row:last-child { border-bottom: 0; }
    .episode-title { font-weight: 700; }
    .episode-meta { color: var(--muted); font-size: 13px; margin-top: 4px; }
    @media (max-width: 900px) {
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .filters { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      .shell { grid-template-columns: 1fr; }
      .item { grid-template-columns: 96px 1fr; min-height: 220px; }
      .poster { min-height: 220px; }
      .grid { grid-template-columns: 1fr; }
      .stats { grid-template-columns: 1fr 1fr; }
      .series-hero { grid-template-columns: 1fr; }
      .series-hero-poster { min-height: 220px; max-width: 220px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="shell">
      <div>
        <h1>M3U Library</h1>
        <div class="subtitle">Your streaming catalog with metadata, favorites, and watched tracking.</div>
      </div>
      <div class="actions">
        <button id="refresh" class="primary">Refresh Library</button>
        <a href="/settings" class="secondary" style="text-decoration:none; display:inline-flex; align-items:center; padding:9px 14px; border:1px solid var(--line); border-radius:10px; color:var(--accent); background:var(--panel-solid);">Settings</a>
        <select id="newWindow" class="secondary">
          <option value="refresh">New: this refresh</option>
          <option value="7">New: this week</option>
          <option value="30">New: this month</option>
          <option value="90">New: last 3 months</option>
          <option value="180">New: last 6 months</option>
        </select>
        <div class="refresh-meta">Last refresh: <span id="statRefresh">Never</span></div>
      </div>
    </div>
  </header>
  <main>
    <section class="hero">
      <div class="stats">
        <button class="stat active" data-section="all" id="statAllCard"><div class="stat-label">Total Items</div><div class="stat-value" id="statTotal">0</div></button>
        <button class="stat" data-section="trending" id="statTrendingCard"><div class="stat-label">Trending This Week</div><div class="stat-value" id="statTrending">0</div></button>
        <button class="stat" data-section="popular" id="statPopularCard"><div class="stat-label">Popular</div><div class="stat-value" id="statPopular">0</div></button>
        <button class="stat" data-section="upcoming" id="statUpcomingCard"><div class="stat-label">Upcoming</div><div class="stat-value" id="statUpcoming">0</div></button>
        <button class="stat" data-section="new" id="statNewCard"><div class="stat-label">New</div><div class="stat-value" id="statNew">0</div></button>
        <button class="stat" data-section="favorites" id="statFavoritesCard"><div class="stat-label">Favorites</div><div class="stat-value" id="statFavorites">0</div></button>
        <button class="stat" data-section="watched" id="statWatchedCard"><div class="stat-label">Watched</div><div class="stat-value" id="statWatched">0</div></button>
        <button class="stat" data-section="lastWatched" id="statLastWatchedCard"><div class="stat-label">Last Watched</div><div class="stat-value" id="statLastWatched">0</div></button>
      </div>
      <div class="status" id="status">Loading library...</div>
      <div id="updateBanner" class="update-banner" hidden>
        <span>Refresh complete — new content available.</span>
        <button id="updateBannerAction" class="primary">Click to update</button>
      </div>
    </section>

    <section class="filters">
      <input id="search" placeholder="Search title or group">
      <select id="kind">
        <option value="">All types</option>
        <option value="live">Live TV</option>
        <option value="movie">Movies</option>
        <option value="series">Series</option>
      </select>
      <select id="group"><option value="">All groups</option></select>
      <select id="sort">
        <option value="added">Recently added</option>
        <option value="new">Newest first</option>
        <option value="rating">Highest rating</option>
        <option value="release">Latest release</option>
        <option value="title">Title A-Z</option>
      </select>
    </section>

    <section id="library" class="grid"></section>
    <div class="pager"><button class="secondary" id="loadMore" hidden>Load more</button></div>
  </main>
  <script>
    const state = {
      items: [],
      limit: 60,
      matched: 0,
      total: 0,
      section: "all",
      groups: [],
      sectionCounts: { all: 0, trending: 0, popular: 0, upcoming: 0, new: 0, favorites: 0, watched: 0, lastWatched: 0 },
      lastRefresh: null,
      newWindow: "refresh",
      metadataStatus: { running: false, completed: 0, total: 0, error: null }
    };
    const els = {
      status: document.querySelector("#status"),
      library: document.querySelector("#library"),
      refresh: document.querySelector("#refresh"),
      search: document.querySelector("#search"),
      kind: document.querySelector("#kind"),
      group: document.querySelector("#group"),
      loadMore: document.querySelector("#loadMore"),
      statTotal: document.querySelector("#statTotal"),
      statTrending: document.querySelector("#statTrending"),
      statPopular: document.querySelector("#statPopular"),
      statUpcoming: document.querySelector("#statUpcoming"),
      statNew: document.querySelector("#statNew"),
      statFavorites: document.querySelector("#statFavorites"),
      statWatched: document.querySelector("#statWatched"),
      statLastWatched: document.querySelector("#statLastWatched"),
      statRefresh: document.querySelector("#statRefresh"),
      sort: document.querySelector("#sort"),
      newWindow: document.querySelector("#newWindow"),
      statCards: [...document.querySelectorAll(".stats [data-section]")],
      main: document.querySelector("main")
    };
    const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[char]));
    const yearOf = value => value ? String(value).slice(0, 4) : "";
    const currentSeriesId = location.pathname.startsWith("/series/") ? decodeURIComponent(location.pathname.split("/").pop()) : null;
    const pageParams = new URLSearchParams(location.search);

    const CACHE_KEY = 'm3u-library-cache-v1';

    function loadCache() {
      try { return JSON.parse(localStorage.getItem(CACHE_KEY)) || null; } catch { return null; }
    }

    function saveCache(state) {
      try { localStorage.setItem(CACHE_KEY, JSON.stringify(state)); } catch {}
    }

    function clearCache() {
      try { localStorage.removeItem(CACHE_KEY); } catch {}
    }

    function showUpdateBanner() {
      const banner = document.getElementById("updateBanner");
      if (banner) banner.hidden = false;
    }

    function hideUpdateBanner() {
      const banner = document.getElementById("updateBanner");
      if (banner) banner.hidden = true;
    }

    function currentLibraryParams() {
      const params = new URLSearchParams();
      if (els.search.value.trim()) params.set("q", els.search.value.trim());
      if (els.kind.value) params.set("kind", els.kind.value);
      if (els.group.value) params.set("group", els.group.value);
      if (els.sort.value && els.sort.value !== "added") params.set("sort", els.sort.value);
      if (state.section && state.section !== "all") params.set("section", state.section);
      if (state.newWindow && state.newWindow !== "refresh") params.set("new_window", state.newWindow);
      return params;
    }

    function libraryHref() {
      const params = currentSeriesId ? pageParams : currentLibraryParams();
      const query = params.toString();
      return query ? `/?${query}` : "/";
    }

    function syncLibraryUrl() {
      if (currentSeriesId) return;
      const query = currentLibraryParams().toString();
      history.replaceState(null, "", query ? `/?${query}` : "/");
    }

    function metadataStatusText() {
      if (state.metadataStatus.error) return `Metadata warm-up error: ${state.metadataStatus.error}`;
      if (state.metadataStatus.running) return `Metadata warming up in background: ${state.metadataStatus.completed}/${state.metadataStatus.total}`;
      if (state.metadataStatus.total && state.metadataStatus.completed >= state.metadataStatus.total) return "Metadata cache is ready.";
      return "";
    }

    function updateGroups(groups) {
      const current = els.group.value;
      state.groups = groups || [];
      els.group.innerHTML = '<option value="">All groups</option>' + state.groups.map(group => `<option value="${esc(group)}">${esc(group)}</option>`).join("");
      els.group.value = state.groups.includes(current) ? current : "";
    }

    function applyStats() {
      els.statTotal.textContent = String(state.total || 0);
      els.statTrending.textContent = String(state.sectionCounts.trending || 0);
      els.statPopular.textContent = String(state.sectionCounts.popular || 0);
      els.statUpcoming.textContent = String(state.sectionCounts.upcoming || 0);
      els.statNew.textContent = String(state.sectionCounts.new || 0);
      els.statFavorites.textContent = String(state.sectionCounts.favorites || 0);
      els.statWatched.textContent = String(state.sectionCounts.watched || 0);
      els.statLastWatched.textContent = String(state.sectionCounts.lastWatched || 0);
      els.statRefresh.textContent = state.lastRefresh ? new Date(state.lastRefresh).toLocaleString() : "Never";
      if (els.newWindow) els.newWindow.value = state.newWindow || "refresh";
      els.statCards.forEach(card => card.classList.toggle("active", card.dataset.section === state.section));
    }

    function metadataMarkup(item) {
      if (!item.metadata_title && !item.release_date && item.kind !== "live") {
        return '<span>Queued for background metadata loading...</span>';
      }
      const title = item.metadata_title || item.title;
      const release = yearOf(item.release_date);
      const rating = item.rating || item.rating === 0 ? Number(item.rating).toFixed(1) : "n/a";
      const description = item.description ? esc(item.description) : "No summary yet.";
      return `
        <div class="metadata-head">
          <span class="metadata-title">${esc(title)}</span>
          ${release ? `<span class="pill">${esc(release)}</span>` : ""}
          ${item.kind !== "live" ? `<span class="rating">&#9733; ${esc(rating)}</span>` : ""}
        </div>
        <div>${description}</div>
      `;
    }

    function sourceTags(sourceTitle) {
      if (!sourceTitle) return "";
      const tags = new Set();
      const yearRe = /^(19|20)\d{2}$/;
      let match;
      const bracketRe = /\[([^\]]+)\]/g;
      while ((match = bracketRe.exec(sourceTitle)) !== null) {
        const tag = match[1].trim().toUpperCase();
        if (tag && !yearRe.test(tag)) tags.add(tag);
      }
      const markerRe = /\b(4K|UHD|FHD|HD|MULTI-SUBS|MULTI SUBS|SUBBED|DUBBED|DE|EN|FR|ES|IT|NL|PL|RU|TR|AR|PT|JA|KO|ZH|HI)\b/gi;
      while ((match = markerRe.exec(sourceTitle)) !== null) {
        tags.add(match[1].toUpperCase());
      }
      if (!tags.size) return "";
      return `<div class="source-tags">${[...tags].map(t => `<span class="source-tag">${esc(t)}</span>`).join("")}</div>`;
    }

    function seriesCardHtml(item) {
      const poster = item.poster_url
        ? `<img src="${esc(item.poster_url)}" alt="">`
        : "SERIES";
      const favoriteClass = item.is_favorite ? "icon-button active-favorite" : "icon-button";
      const watchedClass = item.is_watched ? "icon-button active-watched" : "icon-button";
      const rating = item.rating || item.rating === 0 ? Number(item.rating).toFixed(1) : "n/a";
      return `
        <article class="item" data-series-card="${esc(item.id)}" data-item-id="${esc(item.id)}">
          <div class="poster">${poster}</div>
          <div class="details">
            <div class="card-top">
              <div>
                <div class="title">${esc(item.title)}</div>
                ${sourceTags(item.source_title)}
                <div class="meta">${esc(item.episode_count)} episodes across ${esc(item.season_count || 1)} seasons · ${esc(item.watched_episode_count || 0)} / ${esc(item.episode_count)} watched</div>
              </div>
              <div class="action-group">
                <button class="${favoriteClass}" data-series-favorite="${esc(item.id)}" title="Toggle favorite">&#9733;</button>
                <button class="${watchedClass}" data-series-watched="${esc(item.id)}" title="Toggle watched">&#10003;</button>
              </div>
            </div>
            <div class="row">
              <span class="pill">series</span>
              ${item.is_new ? '<span class="pill pill-new">New</span>' : ""}
              ${item.is_favorite ? '<span class="pill">Favorite</span>' : ""}
              ${item.is_watched ? '<span class="pill">Watched</span>' : ""}
            </div>
            <div class="metadata">
              <div class="metadata-head">
                ${item.release_date ? `<span class="pill">${esc(yearOf(item.release_date))}</span>` : ""}
                <span class="rating">&#9733; ${esc(rating)}</span>
              </div>
              <div>${esc(item.description || "Queued for background metadata loading...")}</div>
            </div>
            <div class="card-actions">
              <div class="action-group">
                <a class="button primary" href="/series/${encodeURIComponent(item.id)}${currentLibraryParams().toString() ? `?${currentLibraryParams().toString()}` : ""}">Open series</a>
              </div>
            </div>
          </div>
        </article>
      `;
    }

    function normalizeHtml(html) {
      return html.replace(/\s+/g, " ").replace(/>\s+</g, "><").trim();
    }

    function renderLibraryIncremental(cardHtmlFn, emptyMessage, statusPrefix = "") {
      applyStats();
      els.status.textContent = metadataStatusText() || `${state.items.length} ${statusPrefix}shown / ${state.matched} matched`;
      els.loadMore.hidden = state.items.length >= state.matched;
      if (!state.items.length) {
        els.library.className = "empty";
        els.library.textContent = emptyMessage;
        return;
      }
      els.library.className = "grid";
      const existing = new Map();
      for (const card of els.library.querySelectorAll("[data-item-id]")) {
        existing.set(card.dataset.itemId, card);
      }
      const fragment = document.createDocumentFragment();
      for (const item of state.items) {
        const html = cardHtmlFn(item);
        const old = existing.get(item.id);
        if (old && normalizeHtml(old.outerHTML) === normalizeHtml(html)) {
          fragment.appendChild(old);
        } else {
          const wrapper = document.createElement("div");
          wrapper.innerHTML = html.trim();
          fragment.appendChild(wrapper.firstElementChild);
        }
      }
      els.library.innerHTML = "";
      els.library.appendChild(fragment);
    }

    function mixedCardHtml(item) {
      if (item.kind === "series") return seriesCardHtml(item);
      const poster = item.poster_url
        ? `<img src="${esc(item.poster_url)}" alt="">`
        : item.logo
          ? `<img src="${esc(item.logo)}" alt="">`
          : esc(item.kind === "live" ? "LIVE" : "MOVIE");
      const favoriteClass = item.is_favorite ? "icon-button active-favorite" : "icon-button";
      const watchedClass = item.is_watched ? "icon-button active-watched" : "icon-button";
      const isExternal = !!item.is_external;
      return `
        <article class="item" data-card="${esc(item.id)}" data-item-id="${esc(item.id)}">
          <div class="poster" data-poster>${poster}</div>
          <div class="details">
            <div class="card-top">
              <div>
                <div class="title">${esc(item.title)}</div>
                ${sourceTags(item.source_title)}
                <div class="meta">${esc(item.group_name || "Uncategorized")}</div>
              </div>
              <div class="action-group"${isExternal ? ' hidden' : ""}>
                <button class="${favoriteClass}" data-favorite="${esc(item.id)}" title="Toggle favorite">&#9733;</button>
                <button class="${watchedClass}" data-watched="${esc(item.id)}" title="Toggle watched">&#10003;</button>
              </div>
            </div>
            <div class="row">
              <span class="pill">${esc(item.kind)}</span>
              ${isExternal ? '<span class="pill">TMDB</span>' : ""}
              ${item.is_new ? '<span class="pill pill-new">New</span>' : ""}
              ${item.is_favorite ? '<span class="pill">Favorite</span>' : ""}
              ${item.is_watched ? '<span class="pill">Watched</span>' : ""}
            </div>
            <div class="metadata" data-metadata>${metadataMarkup(item)}</div>
            <div class="card-actions">
              <div class="action-group">
                ${isExternal
                  ? `<a class="button primary" href="${esc(item.provider_url || "#")}" target="_blank" rel="noreferrer">View on TMDB</a>`
                  : `<a class="button secondary" href="/play/${encodeURIComponent(item.id)}">Browser</a>
                     <a class="button primary" href="/watch/${encodeURIComponent(item.id)}.m3u">Open</a>`}
              </div>
            </div>
          </div>
        </article>
      `;
    }

    function renderMixedItems() {
      const emptyMessage = state.section === "all"
        ? "No items to show. Refresh the library after configuring the environment."
        : state.section === "trending"
          ? "No trending movies from TMDB are currently available in your library."
          : state.section === "popular"
            ? "No popular movies from TMDB are currently available in your library."
            : state.section === "upcoming"
              ? "No upcoming movies are available from TMDB right now."
            : state.section === "lastWatched"
              ? "No recently watched items yet."
          : `No items marked in ${state.section} yet.`;
      renderLibraryIncremental(mixedCardHtml, emptyMessage, "");
    }

    function renderSeriesCards() {
      const emptyMessage = state.section === "trending"
        ? "No trending series from TMDB are currently available in your library."
        : state.section === "popular"
          ? "No popular series from TMDB are currently available in your library."
          : state.section === "upcoming"
            ? "Upcoming is only available for movies."
        : "No series to show for the current filters.";
      renderLibraryIncremental(seriesCardHtml, emptyMessage, "series ");
    }

    function renderLibrary() {
      if (els.kind.value === "series" && state.section !== "lastWatched") renderSeriesCards();
      else renderMixedItems();
    }

    let csrfToken = null;

    async function refreshAuthStatus() {
      try {
        const res = await fetch("/api/auth/status", {cache: "no-store"});
        const data = await res.json();
        if (data.authenticated) csrfToken = data.csrf;
      } catch (error) {
        csrfToken = null;
      }
    }

    async function apiFetch(url, options = {}) {
      const method = (options.method || "GET").toUpperCase();
      const headers = Object.assign({}, options.headers || {});
      if (csrfToken && method !== "GET") headers["X-CSRF-Token"] = csrfToken;
      return fetch(url, {
        cache: "no-store",
        ...options,
        headers
      });
    }

    async function enrichVisibleMetadata() {
      if (els.kind.value === "series" && state.section !== "lastWatched") return;
      const ids = state.items
        .filter(item => item.kind !== "live" && item.kind !== "series" && !item.metadata_title && !item.poster_url)
        .slice(0, 18)
        .map(item => item.id);
      if (!ids.length) return;
      try {
        const res = await apiFetch("/api/metadata/enrich", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(ids)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Metadata enrichment failed");
        const byId = Object.fromEntries((data.items || []).map(item => [item.item_id, item]));
        let changed = false;
        state.items = state.items.map(item => {
          const meta = byId[item.id];
          if (!meta) return item;
          changed = true;
          return { ...item, metadata_title: meta.title, release_date: meta.release_date, rating: meta.rating, description: meta.description, poster_url: meta.poster_url };
        });
        if (changed) renderLibrary();
      } catch (error) {
        console.error(error);
      }
    }

    async function load(append = false) {
      const isSeriesView = els.kind.value === "series";
      let endpoint;
      if (state.section === "lastWatched") {
        const params = new URLSearchParams({
          limit: String(state.limit),
          offset: append ? String(state.items.length) : "0"
        });
        endpoint = `/api/last-watched?${params}`;
      } else {
        const params = new URLSearchParams({
          limit: String(state.limit),
          offset: append ? String(state.items.length) : "0",
          section: state.section,
          sort: els.sort.value,
          new_window: state.newWindow || "refresh"
        });
        if (els.search.value.trim()) params.set("q", els.search.value.trim());
        if (!isSeriesView && els.kind.value) params.set("kind", els.kind.value);
        if (els.group.value && !isSeriesView) params.set("group", els.group.value);
        endpoint = isSeriesView ? `/api/series?${params}` : `/api/items?${params}`;
      }
      syncLibraryUrl();
      els.status.textContent = append ? "Loading more..." : "Loading library...";
      const res = await apiFetch(endpoint);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Load failed");
      state.items = append ? state.items.concat(data.items) : data.items;
      state.matched = data.matched;
      state.total = data.total;
      state.groups = data.groups || [];
      state.sectionCounts = data.section_counts || state.sectionCounts;
      state.lastRefresh = data.last_refresh;
      state.metadataStatus = data.metadata_status || state.metadataStatus;
      if (!isSeriesView) updateGroups(state.groups);
      renderLibrary();
      enrichVisibleMetadata();
      saveCache({
        lastRefresh: state.lastRefresh,
        items: state.items,
        matched: state.matched,
        total: state.total,
        groups: state.groups,
        sectionCounts: state.sectionCounts,
        kind: els.kind.value,
        section: state.section,
        sort: els.sort.value,
        search: els.search.value || "",
        group: els.group.value || "",
        newWindow: state.newWindow,
        seriesQuery: endpoint
      });
    }

    async function refreshSectionCountsOnly() {
      if (!currentSeriesId) return;
      const isSeriesView = els.kind.value === "series";
      const params = new URLSearchParams({
        limit: "1",
        offset: "0",
        section: state.section,
        sort: els.sort.value,
        new_window: state.newWindow || "refresh"
      });
      if (els.search.value.trim()) params.set("q", els.search.value.trim());
      if (!isSeriesView && els.kind.value) params.set("kind", els.kind.value);
      if (els.group.value && !isSeriesView) params.set("group", els.group.value);
      const endpoint = isSeriesView ? `/api/series?${params}` : `/api/items?${params}`;
      const res = await apiFetch(endpoint);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Section refresh failed");
      state.sectionCounts = data.section_counts || state.sectionCounts;
      state.lastRefresh = data.last_refresh || state.lastRefresh;
      applyStats();
    }

    async function refreshMetadataStatus() {
      const res = await apiFetch("/api/metadata/status");
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Metadata status failed");
      state.metadataStatus = data;
      applyStats();
      enrichVisibleMetadata();
    }

    async function bootstrap() {
      const res = await apiFetch("/api/status");
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Status failed");
      state.metadataStatus = data.metadata_status || state.metadataStatus;
      applyStats();
      return data;
    }

    async function refresh() {
      els.refresh.disabled = true;
      els.status.textContent = "Refreshing playlist...";
      try {
        const res = await apiFetch("/api/refresh", { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
          if (res.status === 403) {
            throw new Error("Authentication required — open Settings to log in, then try again.");
          }
          throw new Error(data.detail || "Refresh failed");
        }
        state.lastRefresh = data.last_refresh;
        state.metadataStatus = { running: true, completed: 0, total: 0, error: null };
        applyStats();
        showUpdateBanner();
      } catch (error) {
        els.status.textContent = error.message;
      } finally {
        els.refresh.disabled = false;
      }
    }

    async function toggleItem(id, mode) {
      const res = await apiFetch(`/api/items/${encodeURIComponent(id)}/${mode}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Could not update ${mode}`);
      return data;
    }

    async function toggleSeries(id, mode) {
      const res = await apiFetch(`/api/series/${encodeURIComponent(id)}/${mode}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Could not update ${mode}`);
      return data;
    }

    function activeClassForMode(mode) {
      return mode === "favorite" ? "active-favorite" : "active-watched";
    }

    function countKeyForMode(mode) {
      return mode === "favorite" ? "favorites" : "watched";
    }

    function stateKeyForMode(mode) {
      return mode === "favorite" ? "is_favorite" : "is_watched";
    }

    function updateCardPill(card, pillText, active) {
      const row = card.querySelector(".row");
      if (!row) return;
      const existing = Array.from(row.children).find(el => el.textContent === pillText);
      if (active && !existing) {
        const pill = document.createElement("span");
        pill.className = "pill";
        pill.textContent = pillText;
        row.appendChild(pill);
      } else if (!active && existing) {
        existing.remove();
      }
    }

    // Update the UI immediately, call the API, and revert if it fails.
    // kind is "item" or "series". options.onSuccess / options.onRevert are optional callbacks.
    async function optimisticToggle(id, mode, kind, buttonEl, options = {}) {
      const key = stateKeyForMode(mode);
      const activeClass = activeClassForMode(mode);
      const item = state.items.find(i => i.id === id);
      const oldValue = item ? item[key] : (buttonEl.classList.contains(activeClass) ? 1 : 0);
      const newValue = oldValue ? 0 : 1;
      const pillText = mode === "favorite" ? "Favorite" : "Watched";
      const card = buttonEl.closest(".item");

      // Optimistic UI update.
      buttonEl.classList.toggle(activeClass, !!newValue);
      if (card) updateCardPill(card, pillText, !!newValue);
      if (item) item[key] = newValue;
      if (!currentSeriesId) {
        const countKey = countKeyForMode(mode);
        state.sectionCounts[countKey] = Math.max(0, (state.sectionCounts[countKey] || 0) + (newValue ? 1 : -1));
        applyStats();
      }
      if (options.onOptimisticUpdate) options.onOptimisticUpdate(newValue);

      // Remove card from filtered sections when toggled off.
      let removedCard = false;
      const section = currentSeriesId ? null : state.section;
      const shouldRemove = (section === "favorites" && mode === "favorite" && !newValue) ||
                           ((section === "watched" || section === "lastWatched") && mode === "watched" && !newValue);
      if (shouldRemove) {
        const card = buttonEl.closest(".item");
        if (card) {
          card.remove();
          state.items = state.items.filter(i => i.id !== id);
          state.matched = Math.max(0, state.matched - 1);
          removedCard = true;
          els.status.textContent = metadataStatusText() || `${state.items.length} shown / ${state.matched} matched`;
        }
      }

      try {
        const data = kind === "series" ? await toggleSeries(id, mode) : await toggleItem(id, mode);
        if (item) item[key] = data[key];
        if (options.onSuccess) options.onSuccess(data);
        return data;
      } catch (error) {
        // Revert optimistic changes.
        buttonEl.classList.toggle(activeClass, !!oldValue);
        if (card) updateCardPill(card, pillText, !!oldValue);
        if (item) item[key] = oldValue;
        if (!currentSeriesId) {
          const countKey = countKeyForMode(mode);
          state.sectionCounts[countKey] = Math.max(0, (state.sectionCounts[countKey] || 0) + (oldValue ? 1 : -1));
          applyStats();
        }
        if (options.onRevert) options.onRevert(oldValue);
        if (removedCard) {
          // Card was removed but server failed; reload to restore consistent state.
          load(false).catch(err => console.error(err));
        }
        throw error;
      }
    }

    async function renderSeriesDetail(seriesId) {
      const detailParams = new URLSearchParams({ new_window: state.newWindow || "refresh", _: String(Date.now()) });
      const res = await apiFetch(`/api/series/${encodeURIComponent(seriesId)}?${detailParams}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Series load failed");
      const series = data.series;
      const poster = series.poster_url ? `<img src="${esc(series.poster_url)}" alt="">` : "SERIES";
      const rating = series.rating || series.rating === 0 ? Number(series.rating).toFixed(1) : "n/a";
      const seasons = Object.entries(data.seasons || {}).map(([season, episodes]) => `
        <section class="season-block">
          <div class="season-header">${esc(season)} (${episodes.length})</div>
          ${episodes.map(episode => `
            <div class="episode-row">
              <div>
                <div class="episode-title">${esc(episode.episode_label || episode.title)}</div>
                ${sourceTags(episode.title)}
                <div class="episode-meta">
                  ${episode.episode_number ? `Episode ${esc(episode.episode_number)}` : ""}
                  ${episode.is_new ? ' · New' : ""}
                  ${episode.is_watched ? ' · Watched' : ""}
                </div>
              </div>
              <div class="action-group">
                <button class="${episode.is_watched ? "icon-button active-watched" : "icon-button"}" data-watched="${esc(episode.id)}">&#10003;</button>
                <a class="button secondary" href="/play/${encodeURIComponent(episode.id)}">Browser</a>
                <a class="button primary" href="/watch/${encodeURIComponent(episode.id)}.m3u">Open</a>
              </div>
            </div>
          `).join("")}
        </section>
      `).join("");
      els.main.innerHTML = `
        <section class="hero">
          <div class="series-hero">
            <div class="series-hero-poster">${poster}</div>
            <div class="details">
              <div class="card-top">
                <div>
                  <div class="title">${esc(series.title)}</div>
                  <div class="meta">${esc(data.episode_count)} episodes</div>
                </div>
                <div class="action-group">
                  <button class="${series.is_favorite ? "icon-button active-favorite" : "icon-button"}" data-series-favorite="${esc(series.id)}">&#9733;</button>
                  <button class="${series.is_watched ? "icon-button active-watched" : "icon-button"}" data-series-watched="${esc(series.id)}">&#10003;</button>
                </div>
              </div>
              <div class="row">
                ${series.release_date ? `<span class="pill">${esc(yearOf(series.release_date))}</span>` : ""}
                <span class="rating">&#9733; ${esc(rating)}</span>
                ${series.is_favorite ? '<span class="pill">Favorite</span>' : ""}
                ${series.is_watched ? '<span class="pill" data-series-watched-pill="1">Watched</span>' : ""}
              </div>
              <div class="metadata">${esc(series.description || "No summary yet.")}</div>
              <div class="row"><a class="button secondary" href="${libraryHref()}">Back to library</a></div>
            </div>
          </div>
          ${seasons}
        </section>
      `;
      els.main.onclick = event => {
        const seriesFavorite = event.target.closest("[data-series-favorite]");
        if (seriesFavorite) {
          optimisticToggle(seriesFavorite.dataset.seriesFavorite, "favorite", "series", seriesFavorite).catch(error => {
            console.error(error);
          });
          return;
        }
        const seriesWatched = event.target.closest("[data-series-watched]");
        if (seriesWatched) {
          const updatePill = (isWatched) => {
            let watchedPill = els.main.querySelector("[data-series-watched-pill]");
            if (isWatched) {
              if (!watchedPill) {
                watchedPill = document.createElement("span");
                watchedPill.className = "pill";
                watchedPill.dataset.seriesWatchedPill = "1";
                watchedPill.textContent = "Watched";
                const rowEl = els.main.querySelector(".series-hero .row");
                if (rowEl) rowEl.appendChild(watchedPill);
              }
            } else if (watchedPill) {
              watchedPill.remove();
            }
          };
          optimisticToggle(seriesWatched.dataset.seriesWatched, "watched", "series", seriesWatched, {
            onOptimisticUpdate: (value) => updatePill(value),
            onRevert: () => updatePill(seriesWatched.classList.contains("active-watched"))
          }).catch(error => {
            console.error(error);
          });
          return;
        }
        const watchedButton = event.target.closest("[data-watched]");
        if (watchedButton) {
          const row = watchedButton.closest(".episode-row");
          const meta = row ? row.querySelector(".episode-meta") : null;
          const seriesWatchedButton = els.main.querySelector("[data-series-watched]");
          const updateEpisodeMeta = (isWatched) => {
            if (meta) {
              const watchedTag = " · Watched";
              meta.textContent = meta.textContent.replace(watchedTag, "");
              if (isWatched) meta.textContent += watchedTag;
            }
          };
          const updateSeriesWatched = (isSeriesWatched) => {
            if (seriesWatchedButton) {
              seriesWatchedButton.classList.toggle("active-watched", isSeriesWatched);
            }
            let watchedPill = els.main.querySelector("[data-series-watched-pill]");
            if (isSeriesWatched) {
              if (!watchedPill) {
                watchedPill = document.createElement("span");
                watchedPill.className = "pill";
                watchedPill.dataset.seriesWatchedPill = "1";
                watchedPill.textContent = "Watched";
                const rowEl = els.main.querySelector(".series-hero .row");
                if (rowEl) rowEl.appendChild(watchedPill);
              }
            } else if (watchedPill) {
              watchedPill.remove();
            }
          };
          optimisticToggle(watchedButton.dataset.watched, "watched", "item", watchedButton, {
            onOptimisticUpdate: (value) => updateEpisodeMeta(value),
            onSuccess: (data) => updateSeriesWatched(!!data.series_is_watched),
            onRevert: () => updateEpisodeMeta(watchedButton.classList.contains("active-watched"))
          }).catch(error => {
            console.error(error);
          });
        }
      };
    }

    if (currentSeriesId) {
      renderSeriesDetail(currentSeriesId).catch(error => {
        els.main.innerHTML = `<section class="empty">${esc(error.message)}</section>`;
      });
    } else {
      if (pageParams.has("q")) els.search.value = pageParams.get("q") || "";
      if (pageParams.has("kind")) els.kind.value = pageParams.get("kind") || "";
      if (pageParams.has("sort")) els.sort.value = pageParams.get("sort") || "added";
      if (pageParams.has("section")) state.section = pageParams.get("section") || "all";
      if (pageParams.has("new_window")) state.newWindow = pageParams.get("new_window") || "refresh";
      const initialGroup = pageParams.get("group") || "";
      let timer;
      els.search.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => load(false).catch(error => els.status.textContent = error.message), 250);
      });
      [els.kind, els.group, els.sort].forEach(el => el.addEventListener("change", () => load(false).catch(error => els.status.textContent = error.message)));
      els.newWindow.addEventListener("change", () => {
        state.newWindow = els.newWindow.value || "refresh";
        load(false).catch(error => els.status.textContent = error.message);
      });
      els.statCards.forEach(card => card.addEventListener("click", () => {
        state.section = card.dataset.section;
        load(false).catch(error => els.status.textContent = error.message);
      }));
      els.loadMore.addEventListener("click", () => load(true).catch(error => els.status.textContent = error.message));
      els.refresh.addEventListener("click", refresh);
      els.library.addEventListener("click", event => {
        const favoriteButton = event.target.closest("[data-favorite]");
        if (favoriteButton) {
          optimisticToggle(favoriteButton.dataset.favorite, "favorite", "item", favoriteButton).catch(error => {
            els.status.textContent = error.message;
          });
          return;
        }
        const watchedButton = event.target.closest("[data-watched]");
        if (watchedButton) {
          optimisticToggle(watchedButton.dataset.watched, "watched", "item", watchedButton).catch(error => {
            els.status.textContent = error.message;
          });
          return;
        }
        const seriesFavorite = event.target.closest("[data-series-favorite]");
        if (seriesFavorite) {
          optimisticToggle(seriesFavorite.dataset.seriesFavorite, "favorite", "series", seriesFavorite).catch(error => {
            els.status.textContent = error.message;
          });
          return;
        }
        const seriesWatched = event.target.closest("[data-series-watched]");
        if (seriesWatched) {
          optimisticToggle(seriesWatched.dataset.seriesWatched, "watched", "series", seriesWatched).catch(error => {
            els.status.textContent = error.message;
          });
        }
      });
      setInterval(() => {
        refreshMetadataStatus().catch(error => console.error(error));
      }, 5000);

      document.getElementById("updateBannerAction").addEventListener("click", () => {
        hideUpdateBanner();
        load(false).catch(error => els.status.textContent = error.message);
      });

      await refreshAuthStatus();

      const cache = loadCache();
      const currentParams = {
        kind: els.kind.value,
        section: state.section,
        sort: els.sort.value,
        search: els.search.value || "",
        group: initialGroup,
        newWindow: state.newWindow
      };
      const cacheMatches = cache &&
        cache.kind === currentParams.kind &&
        cache.section === currentParams.section &&
        cache.sort === currentParams.sort &&
        cache.search === currentParams.search &&
        cache.group === currentParams.group &&
        cache.newWindow === currentParams.newWindow;

      let hadUsableCache = false;
      if (cacheMatches) {
        hadUsableCache = true;
        state.items = cache.items;
        state.matched = cache.matched;
        state.total = cache.total;
        state.groups = cache.groups || [];
        state.sectionCounts = cache.sectionCounts || state.sectionCounts;
        state.lastRefresh = cache.lastRefresh;
        updateGroups(state.groups);
        if (initialGroup && state.groups.includes(initialGroup)) els.group.value = initialGroup;
        renderLibrary();
      }

      bootstrap().then(data => {
        const serverLastRefresh = data.last_refresh;
        if (!hadUsableCache) {
          return load(false).then(() => {
            if (initialGroup && state.groups.includes(initialGroup)) {
              els.group.value = initialGroup;
              return load(false);
            }
          });
        }
        if (serverLastRefresh && serverLastRefresh !== state.lastRefresh) {
          showUpdateBanner();
        }
      }).catch(error => els.status.textContent = error.message);
    }
  </script>
</body>
</html>"""


SETTINGS_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>M3U Library — Settings</title>
  <style>
    :root {
      --bg: #f2efe8; --panel: rgba(255, 251, 244, 0.9); --panel-solid: #fffaf2;
      --text: #1f2430; --muted: #6c746f; --line: #ddd1bc;
      --accent: #a74f2f; --accent-strong: #8d3c21;
      --success: #2f7b58; --error: #b3261e;
      --shadow: 0 16px 40px rgba(78, 55, 24, 0.12);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: "Trebuchet MS", "Segoe UI", system-ui, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(212, 166, 42, 0.18), transparent 28%),
        linear-gradient(180deg, #f8f4ec 0%, var(--bg) 40%, #ece3d4 100%);
      min-height: 100vh;
    }
    *:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .page { max-width: 720px; margin: 0 auto; padding: 32px 20px 64px; }
    header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 24px; }
    h1 { margin: 0; font-size: 1.6rem; }
    h2 { font-size: 1.1rem; margin: 0 0 14px; }
    a { color: var(--accent); }
    .card {
      background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
      box-shadow: var(--shadow); padding: 20px; margin-bottom: 20px;
    }
    label { display: block; font-size: 0.9rem; font-weight: 600; margin: 14px 0 4px; }
    label:first-of-type { margin-top: 0; }
    .hint { font-size: 0.8rem; color: var(--muted); font-weight: 400; margin-top: 2px; }
    input[type="password"], input[type="text"] {
      width: 100%; padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px;
      background: var(--panel-solid); color: var(--text); font-size: 0.95rem; font-family: inherit;
    }
    input:focus { border-color: var(--accent); }
    .row { display: flex; gap: 10px; align-items: center; }
    .row input { flex: 1; }
    button {
      padding: 9px 18px; border: none; border-radius: 8px; font-size: 0.95rem;
      cursor: pointer; font-family: inherit; background: var(--accent); color: #fff;
    }
    button:hover { background: var(--accent-strong); }
    button.ghost { background: transparent; color: var(--accent); border: 1px solid var(--accent); }
    button.ghost:hover { background: rgba(167, 79, 47, 0.08); }
    .status { margin-top: 12px; font-size: 0.9rem; min-height: 1.2em; }
    .status.ok { color: var(--success); }
    .status.err { color: var(--error); }
    .badge { font-size: 0.75rem; padding: 2px 8px; border-radius: 99px; border: 1px solid var(--line); color: var(--muted); }
    .badge.set { border-color: var(--success); color: var(--success); }
    .field-head { display: flex; justify-content: space-between; align-items: baseline; }
    .top-actions { display: flex; gap: 10px; align-items: center; }
  </style>
</head>
<body>
  <div class="page">
    <header>
      <h1>M3U Library — Settings</h1>
      <div class="top-actions">
        <a href="/">← Back to library</a>
        <button id="logout" class="ghost" hidden>Log out</button>
      </div>
    </header>

    <!-- Setup / login forms -->
    <div id="authCard" class="card" hidden>
      <h2 id="authTitle">Admin login</h2>
      <form id="authForm">
        <label for="authPassword">Password</label>
        <input type="password" id="authPassword" autocomplete="current-password" required>
        <div id="authPassword2Wrap" hidden>
          <label for="authPassword2">Repeat password</label>
          <input type="password" id="authPassword2" autocomplete="new-password">
        </div>
        <p class="hint" id="authHint"></p>
        <p><button type="submit" class="primary" id="authSubmit">Log in</button></p>
        <div class="status" id="authStatus"></div>
      </form>
    </div>

    <!-- Settings form -->
    <div id="settingsCard" hidden>
      <div class="card">
        <h2>Library &amp; metadata</h2>
        <form id="settingsForm">
          <div class="field-head">
            <label for="M3U_URL">M3U playlist URL</label>
            <span class="badge" id="badge-M3U_URL">not set</span>
          </div>
          <div class="row">
            <input type="password" id="M3U_URL" autocomplete="off" placeholder="https://provider.example/playlist.m3u">
            <button type="button" class="ghost" data-toggle="M3U_URL">Show</button>
          </div>
          <p class="hint">The playlist link provided by your streaming provider. Stored in the server-side .env file (mode 0600), never in Git.</p>

          <div class="field-head">
            <label for="TMDB_API_KEY">TMDB API key (v3)</label>
            <span class="badge" id="badge-TMDB_API_KEY">not set</span>
          </div>
          <div class="row">
            <input type="password" id="TMDB_API_KEY" autocomplete="off" placeholder="optional if bearer token is set">
            <button type="button" class="ghost" data-toggle="TMDB_API_KEY">Show</button>
          </div>

          <div class="field-head">
            <label for="TMDB_BEARER_TOKEN">TMDB bearer token (v4)</label>
            <span class="badge" id="badge-TMDB_BEARER_TOKEN">not set</span>
          </div>
          <div class="row">
            <input type="password" id="TMDB_BEARER_TOKEN" autocomplete="off" placeholder="optional if API key is set">
            <button type="button" class="ghost" data-toggle="TMDB_BEARER_TOKEN">Show</button>
          </div>
          <p class="hint">One of the two TMDB credentials is enough for movie/series metadata. Get them at themoviedb.org → Settings → API.</p>

          <div class="field-head">
            <label for="METADATA_LANGUAGE">Metadata language</label>
            <span class="badge" id="badge-METADATA_LANGUAGE">not set</span>
          </div>
          <input type="text" id="METADATA_LANGUAGE" autocomplete="off" placeholder="en-US">
          <p class="hint">TMDB language tag, e.g. en-US, de-DE, fr-FR.</p>

          <p><button type="submit" class="primary">Save settings</button></p>
          <div class="status" id="settingsStatus"></div>
        </form>
      </div>

      <div class="card">
        <h2>API key for external clients</h2>
        <p class="hint">Scripts such as the systemd refresh timer authenticate against protected endpoints with this key via the <code>X-API-Key</code> header.</p>
        <p>Status: <span class="badge" id="badge-API_KEY">not set</span></p>
        <div class="row">
          <input type="text" id="API_KEY" readonly placeholder="••••">
          <button type="button" class="ghost" id="revealKey">Reveal</button>
          <button type="button" class="ghost" id="regenKey">Regenerate</button>
        </div>
        <div class="status" id="keyStatus"></div>
      </div>

      <div class="card">
        <h2>Change admin password</h2>
        <form id="passwordForm">
          <label for="currentPassword">Current password</label>
          <input type="password" id="currentPassword" autocomplete="current-password" required>
          <label for="newPassword">New password (min. 8 characters)</label>
          <input type="password" id="newPassword" autocomplete="new-password" required>
          <label for="newPassword2">Repeat new password</label>
          <input type="password" id="newPassword2" autocomplete="new-password" required>
          <p><button type="submit" class="primary">Change password</button></p>
          <div class="status" id="passwordStatus"></div>
        </form>
      </div>
    </div>
  </div>

  <script>
    let csrf = null;

    function setStatus(el, message, ok) {
      el.textContent = message || "";
      el.className = "status" + (ok === undefined ? "" : ok ? " ok" : " err");
    }

    async function apiFetch(url, options = {}) {
      const method = (options.method || "GET").toUpperCase();
      const headers = Object.assign({"Content-Type": "application/json"}, options.headers || {});
      if (csrf && method !== "GET") headers["X-CSRF-Token"] = csrf;
      const res = await fetch(url, Object.assign({}, options, {headers}));
      return res;
    }

    function showAuth(setupRequired) {
      document.getElementById("authCard").hidden = false;
      document.getElementById("settingsCard").hidden = true;
      document.getElementById("logout").hidden = true;
      document.getElementById("authTitle").textContent = setupRequired ? "First-run setup — choose an admin password" : "Admin login";
      document.getElementById("authHint").textContent = setupRequired
        ? "This password protects the settings page and all admin actions. It is stored as a bcrypt hash on the server."
        : "";
      document.getElementById("authPassword2Wrap").hidden = !setupRequired;
      document.getElementById("authSubmit").textContent = setupRequired ? "Create password" : "Log in";
      document.getElementById("authForm").onsubmit = (event) => {
        event.preventDefault();
        setupRequired ? doSetup() : doLogin();
      };
    }

    function showSettings() {
      document.getElementById("authCard").hidden = true;
      document.getElementById("settingsCard").hidden = false;
      document.getElementById("logout").hidden = false;
      loadSettings();
    }

    async function doSetup() {
      const pw = document.getElementById("authPassword").value;
      const pw2 = document.getElementById("authPassword2").value;
      const status = document.getElementById("authStatus");
      if (pw !== pw2) return setStatus(status, "Passwords do not match.", false);
      const res = await fetch("/api/auth/setup", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({password: pw})});
      const data = await res.json();
      if (!res.ok) return setStatus(status, data.detail || "Setup failed.", false);
      csrf = data.csrf;
      setStatus(status, "Password created.", true);
      showSettings();
    }

    async function doLogin() {
      const pw = document.getElementById("authPassword").value;
      const status = document.getElementById("authStatus");
      const res = await fetch("/api/auth/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({password: pw})});
      const data = await res.json();
      if (!res.ok) return setStatus(status, data.detail || "Login failed.", false);
      csrf = data.csrf;
      setStatus(status, "Logged in.", true);
      showSettings();
    }

    async function loadSettings() {
      const res = await apiFetch("/api/admin/settings");
      if (!res.ok) return;
      const data = await res.json();
      if (data.csrf) csrf = data.csrf;
      for (const [key, info] of Object.entries(data.keys)) {
        const badge = document.getElementById("badge-" + key);
        if (badge) {
          badge.textContent = info.set ? "set" : "not set";
          badge.className = "badge" + (info.set ? " set" : "");
        }
        const input = document.getElementById(key);
        if (input && key !== "API_KEY") input.value = info.value || "";
      }
    }

    document.getElementById("settingsForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const status = document.getElementById("settingsStatus");
      const body = {};
      for (const key of ["M3U_URL", "TMDB_API_KEY", "TMDB_BEARER_TOKEN", "METADATA_LANGUAGE"]) {
        body[key] = document.getElementById(key).value;
      }
      const res = await apiFetch("/api/admin/settings", {method: "PUT", body: JSON.stringify(body)});
      const data = await res.json();
      if (!res.ok) return setStatus(status, data.detail || "Save failed.", false);
      setStatus(status, "Saved. Changes take effect immediately.", true);
      loadSettings();
    });

    document.getElementById("passwordForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const status = document.getElementById("passwordStatus");
      const current = document.getElementById("currentPassword").value;
      const next = document.getElementById("newPassword").value;
      if (next !== document.getElementById("newPassword2").value) return setStatus(status, "New passwords do not match.", false);
      const res = await apiFetch("/api/admin/settings/password", {method: "POST", body: JSON.stringify({current, new: next})});
      const data = await res.json();
      if (!res.ok) return setStatus(status, data.detail || "Password change failed.", false);
      setStatus(status, "Password changed.", true);
      event.target.reset();
    });

    document.getElementById("revealKey").addEventListener("click", async () => {
      const res = await apiFetch("/api/admin/settings?reveal=1");
      if (!res.ok) return;
      const data = await res.json();
      document.getElementById("API_KEY").value = (data.keys.API_KEY && data.keys.API_KEY.value) || "";
    });

    document.getElementById("regenKey").addEventListener("click", async () => {
      const status = document.getElementById("keyStatus");
      if (!confirm("Regenerate the API key? Clients using the old key (e.g. the refresh timer) must be updated.")) return;
      const res = await apiFetch("/api/admin/settings/api-key/regenerate", {method: "POST", body: "{}"});
      const data = await res.json();
      if (!res.ok) return setStatus(status, data.detail || "Regeneration failed.", false);
      document.getElementById("API_KEY").value = data.api_key;
      setStatus(status, "New API key generated. The refresh timer reads the .env file on every run, so no manual update is needed.", true);
    });

    document.getElementById("logout").addEventListener("click", async () => {
      await fetch("/api/auth/logout", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
      csrf = null;
      location.reload();
    });

    document.querySelectorAll("[data-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const input = document.getElementById(button.dataset.toggle);
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        button.textContent = show ? "Hide" : "Show";
      });
    });

    (async function boot() {
      const res = await fetch("/api/auth/status");
      const data = await res.json();
      if (data.authenticated) {
        csrf = data.csrf;
        showSettings();
      } else {
        showAuth(data.setup_required);
      }
    })();
  </script>
</body>
</html>"""
