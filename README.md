# M3U Library

A self-hosted FastAPI service for browsing an M3U playlist: it checks the
playlist, lists new movies and series, enriches them with TMDB metadata,
and hands streams off to your local player (one click downloads a
`.m3u` that opens in PotPlayer, VLC, etc.).

All configuration — playlist URL, TMDB credentials, admin password, API
key — is entered in a **settings page** after first start and stored
server-side with restrictive file permissions. Nothing secret ever lives in
Git, and there is no manual file editing required for normal operation.

![M3U Library web UI: dark library view with poster grid, sidebar navigation,
watched progress, and source health](docs/screenshot.jpg)

![Series detail: episode progress, season tabs, watched toggles, and
next-episode handoff](docs/screenshot-series.jpg)

![Settings: tabbed admin page for playlist source, TMDB credentials, API key,
and admin password — secrets stay server-side](docs/screenshot-settings.jpg)

## Features

- **Library browser** — movies, series (grouped with episode navigation),
  and live channels, with search, filters, favorites, and watched tracking
- **Source health check** — server-side validation of the playlist URL
  (reachable, valid, entry count, or the concrete failure), shown in the
  library and on the Settings page; a failed refresh never wipes the
  library
- **New-content windows** — filter for items added in the last refresh,
  week, month, three months, or six months
- **TMDB metadata** — posters, overviews, ratings; cached in SQLite with a
  background warm-up and per-item `Info` dialog
- **External-player handoff** — one click downloads a `.m3u` playlist that
  opens the stream in PotPlayer, VLC, or any local player
- **Daily auto-refresh** — systemd timer posts to `/api/refresh` at noon
- **Admin settings UI** — first-run password setup, then everything is
  configured on the Settings page (`/settings`)

## What you need

This software is a **library browser and player front-end for M3U
playlists** — it brings no content of its own and is not a source of
streams. To use it you need:

1. **A legal IPTV subscription that provides an M3U playlist.** Many
   licensed providers (regional TV-over-IP services, broadcaster
   packages, ISP TV bundles) let you export an M3U URL from the customer
   portal, or issue Xtream Codes login data from which an M3U URL can be
   derived. Check your provider's terms of service before pointing this
   app at the playlist: some providers restrict playback to their own
   apps, and sharing or re-streaming a playlist is almost always
   prohibited. Use it only for yourself, on your own devices — that is
   the scenario this software is built for.
2. **A host** — Python 3.11+ on any machine that can reach the playlist
   URL and that your browser can reach. A small VM or an always-on home
   server works well.
3. **Optionally, a free TMDB API key** for posters and descriptions
   ([themoviedb.org → Settings → API](https://www.themoviedb.org/settings/api)).

Playback happens in your local player (PotPlayer, VLC, …): the app
downloads a small `.m3u` handoff file, and the player fetches the stream
directly from your provider. The server itself only ever fetches the
playlist and text/image metadata.

## Quick start

Prerequisites: Python 3.11+, a Debian/Ubuntu-style host (systemd), and an
M3U playlist URL (see [What you need](#what-you-need)).

```bash
git clone https://github.com/mb86231/m3u-playlist.git
cd m3u-playlist
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
mkdir -p /var/lib/apps/m3u-library   # or any data dir you prefer
export DATA_DIR=/var/lib/apps/m3u-library
uvicorn m3u_library.main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000/settings**:

1. **First run:** choose your admin password (stored as a bcrypt hash).
2. Enter your **M3U playlist URL** and, optionally, a **TMDB API key or
   bearer token** (get one at [themoviedb.org](https://www.themoviedb.org/settings/api)).
3. Back on the main page, press **Refresh Library**.

Secrets you save are written to `$DATA_DIR/.env` (mode `0600`) — the same
file the systemd units load — and take effect immediately, no restart
needed. See [`INSTALL.md`](INSTALL.md) for the full installation guide,
including the systemd service and the daily refresh timer.

## Security model

- Admin password: bcrypt hash in `$DATA_DIR/secrets.json` (mode `0600`)
- Login sessions: HMAC-signed, `HttpOnly` cookie, CSRF token on every
  state-changing request, login brute-force lockout
- External scripts (refresh timer): random `API_KEY`, sent as `X-API-Key`
- Playlist URL and TMDB credentials: `$DATA_DIR/.env` (mode `0600`),
  masked in API responses, revealed only to authenticated admins
- Served values read from the settings store take effect without restart

See [`SECURITY.md`](SECURITY.md) for the full policy and threat model.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

## Documentation

| Document | Purpose |
|----------|---------|
| [`INSTALL.md`](INSTALL.md) | Full installation guide (venv, systemd, timer) |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history (mirrors the GitHub releases) |
| [`SECURITY.md`](SECURITY.md) | Security policy, secret management, threat model |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Backend/frontend design, stable IDs, auth model |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Deployment pipeline, configuration, backups, troubleshooting |
| [`docs/MIGRATION-stable-ids.md`](docs/MIGRATION-stable-ids.md) | Completed one-off stable-ID migration and rollback |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Planned improvements |

## License

[MIT](LICENSE)
