# Architecture

## Overview

m3u-library is a single-process FastAPI app backed by SQLite. It fetches an
M3U playlist, normalizes entries into a local library, enriches them with
TMDB metadata, and serves a small vanilla-JS web UI.

Runtime layout on the LXC (`apps`, 198.51.100.49):

```text
/opt/apps/m3u-library          application code (git checkout of main)
/opt/apps/m3u-library/.venv    Python virtualenv
/var/lib/apps/m3u-library      data + secrets
/var/lib/apps/m3u-library/app.db
/var/lib/apps/m3u-library/.env
```

Service: `m3u-library.service` (systemd, runs as `codex`, port 8000).

## Backend

### Async single-writer SQLite (`m3u_library/db.py`)

All writes go through one `Database` singleton:

- A dedicated writer asyncio task owns one `aiosqlite` connection and drains
  a queue of write jobs (`write_db(fn)`). This serializes writes and avoids
  `database is locked` errors under concurrent requests.
- Reads use short-lived independent connections (`read_db()`) so WAL mode
  keeps them concurrent with writes.
- `Database.init()` runs schema migrations via `m3u_library/migrations.py`.

### Versioned migrations (`m3u_library/migrations.py`)

Schema changes are tracked in a `migrations` table `(version, name,
applied_at)`. `run_migrations()` applies every migration newer than the
recorded max version inside a transaction and records it. Existing
databases that predate the table are migrated idempotently by migration 1
(`CREATE TABLE IF NOT EXISTS` + additive column/index checks). Add future
schema changes as migration 2, 3, ... — never edit an already-applied
migration.

### Stable item IDs (`item_id()` in `m3u_library/main.py`)

IDs are content-derived, not URL-derived, so provider URL rotation does not
orphan user state:

- series episode: `sha256("series\n{series_id}\n{season}\n{episode}")[:20]`
- movie: `sha256("movie\n{title.lower().strip()}")[:20]`
- live/other: `sha256("{title}\n{stream_url}")[:20]`

`POST /api/refresh` computes `to_insert` / `to_update` / `to_remove` deltas
against these IDs and only touches changed rows, preserving watched /
favorite state across URL changes.

### Authentication and settings (`require_api_key`, `require_admin`, `m3u_library/settings.py`)

Protected endpoints: `POST /api/refresh`, `POST /api/metadata/enrich`,
`POST /api/metadata/warmup`, and all `/api/admin/*` routes.

Access model:

- **Admin session** (browser): login on `/settings` with the admin
  password. The session is an HMAC-signed cookie (7-day expiry); the
  password is stored as a bcrypt hash in `secrets.json` (mode `0600`).
  State-changing requests must carry the session's CSRF token in the
  `X-CSRF-Token` header. Login has a per-IP lockout (5 failures / 30 s).
- **API key** (scripts): a random `API_KEY` sent as `X-API-Key`, used by
  the systemd refresh timer. Configured in `.env` or via the settings UI
  (reveal / regenerate).
- **Unprotected fallback**: if neither an admin password nor `API_KEY` is
  set, requests pass. This state exists only to enable the first-run
  setup and is closed once a password is chosen (`POST /api/auth/setup`
  returns `409` afterwards).

Settings storage (`m3u_library/settings.py`):

- `DATA_DIR/.env` (mode `0600`) holds the UI-managed keys: `M3U_URL`,
  `TMDB_API_KEY`, `TMDB_BEARER_TOKEN`, `METADATA_LANGUAGE`, `API_KEY`.
  The settings UI rewrites this file atomically and mirrors values into
  the process environment, so saved changes take effect immediately;
  because the file is also the systemd `EnvironmentFile`, they survive
  restarts.
- `DATA_DIR/secrets.json` (mode `0600`) holds authentication material
  only: the bcrypt admin-password hash and the session-signing secret.

Values are read through `settings.effective_value()`, which resolves the
process environment (loaded at startup from the `.env` files and the
systemd `EnvironmentFile`). API responses mask secrets; only an
authenticated admin can reveal them (`GET /api/admin/settings?reveal=1`).

The systemd refresh timer authenticates with the key from
`/var/lib/apps/m3u-library/.env`.

## Frontend

The UI is embedded in `m3u_library/main.py` (single-file vanilla JS):

- `localStorage` cache of `/api/items` for instant first paint.
- Incremental DOM diffing — only changed cards are re-rendered.
- "new content available" banner instead of a full reload when the server
  data changes underneath the cache.

## Tests

`pytest` with `pytest-asyncio` and `httpx` (`requirements-dev.txt`).
Run locally:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

The suite covers stable IDs, the single-writer DB layer, refresh deltas and
watched-state preservation, the schema-migration runner, and auth
(key required / same-origin allowed / cross-origin rejected).
