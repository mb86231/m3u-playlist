# Operations

## Deployment pipeline

Push to `main` on `git.example.com/<owner>/m3u-playlist` triggers
`.gitea/workflows/deploy.yml` on the `m3u-library-deploy` runner (label
`self-hosted`):

1. **test** — clones the repo into `/tmp/m3u-test`, installs
   `requirements-dev.txt`, runs `pytest -q`. Deploy is skipped on failure.
2. **deploy** — syncs `deploy-m3u-library.sh` from the repo to
   `/home/<deploy-user>/deploy-m3u-library.sh`, then runs it:
   - updates `/opt/apps/m3u-library` to `origin/main`
   - (re)creates the venv and installs `requirements.txt`
   - regenerates a fresh random `API_KEY` in `/var/lib/apps/m3u-library/.env`
   - installs `m3u-library.service` and `m3u-library-refresh.service`,
     `daemon-reload`, restarts `m3u-library.service`
3. **Smoke test** — asserts `POST /api/metadata/warmup` without a key
   returns `403` (auth enforced) and `/api/status` responds.

The deploy script is the source of truth and lives in the repo; the copy at
`/home/<deploy-user>/deploy-m3u-library.sh` is refreshed from the repo on every
deploy.

Note: `deploy-m3u-library.sh` enables `m3u-library-refresh.service` but not
its `.timer`. Enable the timer once manually (see README → *Daily
auto-refresh*).

## Configuration

All runtime configuration is managed on the **Settings page**
(`http://198.51.100.49:8000/settings`) after logging in with the admin
password. The UI writes two files, both mode `0600`, owner `codex:codex`:

- `/var/lib/apps/m3u-library/.env` — `M3U_URL` (required),
  `TMDB_BEARER_TOKEN` / `TMDB_API_KEY` (metadata; either is enough),
  `METADATA_LANGUAGE`, `API_KEY`. Also the systemd `EnvironmentFile`.
- `/var/lib/apps/m3u-library/secrets.json` — bcrypt hash of the admin
  password and the session-signing secret. Never returned by any API.

UI saves apply immediately (the running process is updated in place) and
persist across restarts via the `.env` file.

`API_KEY` is rewritten on each deploy, so any external client using the
key must re-read it after a deploy (the refresh timer reads the `.env`
file on every run, so it needs no manual update).

## Backups and restore

There is no automated backup yet (see ROADMAP). The database is a single
SQLite file; back it up while the service is stopped (or use the SQLite
online backup API) to avoid copying a hot WAL file:

```bash
sudo systemctl stop m3u-library.service
TS=$(date +%Y%m%d-%H%M%S)
sudo cp /var/lib/apps/m3u-library/app.db /var/lib/apps/m3u-library/app.db.bak-${TS}
sudo systemctl start m3u-library.service
```

Restore:

```bash
sudo systemctl stop m3u-library.service
sudo cp /var/lib/apps/m3u-library/app.db.bak-<TS> /var/lib/apps/m3u-library/app.db
sudo rm -f /var/lib/apps/m3u-library/app.db-wal /var/lib/apps/m3u-library/app.db-shm
sudo systemctl start m3u-library.service
```

Timestamped pre-migration backups (`app.db.pre-stable-ids-*`) may still
exist in the data dir from the stable-ID migration.

## Watched/favorite state snapshots

After every successful refresh the app writes a compact snapshot of all
watched/favorite state to `$DATA_DIR/state-snapshots/`: `latest.json` plus
`snapshot-<refresh-timestamp>.json` (30 kept). This protects user state
(watched episodes, favorites) independent of full database backups — a
refresh glitch or a bad migration can no longer silently lose it.

```bash
# list available snapshots (needs the API key)
curl -s -H "X-API-Key: <key>" http://198.51.100.49:8000/api/state/snapshots

# restore watched/favorite state (only state columns are written;
# ids missing from the current library are reported as missing)
curl -s -X POST -H "X-API-Key: <key>" \
  "http://198.51.100.49:8000/api/state/restore?file=latest.json"
```

Server-side helper (runs directly against the SQLite database, so stop
the service first):

```bash
sudo systemctl stop m3u-library.service
sudo python3 scripts/restore_state.py [snapshot-name]   # default: latest.json
sudo systemctl start m3u-library.service
```

After a restore, `last_refresh` is bumped (API restore) resp. should be
refreshed so open browser tabs pick up the restored state.

## Useful commands

```bash
systemctl status m3u-library.service
journalctl -u m3u-library.service -f
curl -s http://198.51.100.49:8000/api/status | python3 -m json.tool

# admin call (needs the current key from .env)
curl -X POST -H "X-API-Key: <key>" http://198.51.100.49:8000/api/refresh
```

Scheduled refresh: `m3u-library-refresh.timer` (daily 12:00, persistent).
Check with `systemctl list-timers m3u-library-refresh.timer`.

## Troubleshooting

- **`Invalid or missing API key` / `403` in the web UI** — log in on the
  Settings page first; browsers authenticate with the session cookie, and
  state-changing requests additionally need the CSRF header (the built-in
  UI sends it automatically). Scripted clients use `X-API-Key`.
- **UI shows stale data** — the page caches in `localStorage`; force
  reload, or press the refresh banner.
- **Deploy fails at smoke test** — auth not enforced; check the deploy log
  and that `API_KEY` was written to `.env`.
- **`database is locked`** — should be gone after the single-writer
  refactor; if it returns, check for a leftover second process.
