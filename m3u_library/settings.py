"""Secure settings and admin-auth storage for M3U Library.

Two storage locations, deliberately separated:

* ``DATA_DIR/.env`` — application configuration and secrets managed through
  the admin settings UI (M3U_URL, TMDB credentials, API_KEY, ...). The file
  is also the systemd ``EnvironmentFile``, so values written here survive
  restarts and are visible to the daily refresh timer. Mode 0600.
* ``DATA_DIR/secrets.json`` — authentication material only (bcrypt hash of
  the admin password and the session-signing secret). Mode 0600. Never
  returned by any API.

Values already present in the process environment (real environment
variables, or the same file loaded at startup) act as fallback defaults.
Changes written through the settings UI update the file *and* the running
process, so they take effect immediately without a restart.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets as secrets_mod
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

import bcrypt

# Keys the admin settings UI may read and write in the .env file.
UI_KEYS = (
    "M3U_URL",
    "TMDB_API_KEY",
    "TMDB_BEARER_TOKEN",
    "METADATA_LANGUAGE",
    "API_KEY",
)

_ADMIN_USER = "admin"
_PASSWORD_MIN_LENGTH = 8
_HASH_KEY = "admin_password_hash"
_SESSION_SECRET_KEY = "session_secret"


def data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "/var/lib/apps/m3u-library"))


def env_path() -> Path:
    return data_dir() / ".env"


def secrets_path() -> Path:
    return data_dir() / "secrets.json"


# ---------------------------------------------------------------------------
# .env file management
# ---------------------------------------------------------------------------

def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def update_env_file(path: Path, updates: dict[str, str | None]) -> None:
    """Apply ``updates`` to an .env-style file.

    ``str`` values set or replace the key, ``None`` removes it. Comments and
    unrelated lines are preserved. The file is rewritten atomically with
    mode 0600.
    """
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
        if key is not None and key in remaining:
            value = remaining.pop(key)
            if value is not None:
                out.append(f"{key}={value}")
            continue
        out.append(line)
    for key, value in remaining.items():
        if value is not None:
            out.append(f"{key}={value}")

    content = "\n".join(out).rstrip("\n") + "\n"
    _atomic_write(path, content)


def effective_value(key: str, default: str = "") -> str:
    """The value the running app uses: process environment first.

    The settings UI writes both the file and ``os.environ``, so after a UI
    save the environment is authoritative and changes apply immediately.
    """
    return os.getenv(key, default).strip()


def apply_updates(updates: dict[str, str | None], path: Path | None = None) -> None:
    """Persist UI updates to the .env file and the current process."""
    target = path or env_path()
    update_env_file(target, updates)
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def env_file_mode() -> int:
    path = env_path()
    if not path.exists():
        return 0
    return stat.S_IMODE(path.stat().st_mode)


# ---------------------------------------------------------------------------
# secrets.json — authentication material
# ---------------------------------------------------------------------------

def _load_secrets() -> dict[str, Any]:
    path = secrets_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_secrets(data: dict[str, Any]) -> None:
    _atomic_write(secrets_path(), json.dumps(data, indent=2, sort_keys=True) + "\n")


def has_admin_password() -> bool:
    return bool(_load_secrets().get(_HASH_KEY))


def admin_password_set() -> bool:
    return has_admin_password()


def set_admin_password(password: str) -> None:
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters")
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    data = _load_secrets()
    data[_HASH_KEY] = hashed
    _save_secrets(data)


def verify_admin_password(password: str) -> bool:
    hashed = _load_secrets().get(_HASH_KEY)
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def rotate_session_secret() -> str:
    data = _load_secrets()
    data[_SESSION_SECRET_KEY] = secrets_mod.token_hex(32)
    _save_secrets(data)
    return data[_SESSION_SECRET_KEY]


def _session_secret() -> str:
    data = _load_secrets()
    secret = data.get(_SESSION_SECRET_KEY)
    if isinstance(secret, str) and secret:
        return secret
    return rotate_session_secret()


# ---------------------------------------------------------------------------
# Signed session tokens (HMAC-SHA256, stdlib only)
# ---------------------------------------------------------------------------

def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_session_token() -> tuple[str, str]:
    """Return ``(token, csrf_token)`` for a new admin session."""
    csrf = secrets_mod.token_hex(16)
    payload = json.dumps(
        {"u": _ADMIN_USER, "csrf": csrf, "exp": int(time.time()) + 7 * 86400},
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(_session_secret().encode("ascii"), payload, hashlib.sha256).digest()
    return _b64encode(payload) + "." + _b64encode(signature), csrf


def verify_session_token(token: str) -> dict[str, Any] | None:
    """Return the session payload (with ``csrf``) or ``None`` if invalid."""
    try:
        payload_part, signature_part = token.split(".", 1)
        payload = _b64decode(payload_part)
        signature = _b64decode(signature_part)
    except (ValueError, TypeError):
        return None
    expected = hmac.new(_session_secret().encode("ascii"), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("u") != _ADMIN_USER:
        return None
    exp = data.get("exp")
    if not isinstance(exp, (int, float)) or exp < time.time():
        return None
    return data
