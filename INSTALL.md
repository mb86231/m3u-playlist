# Installation Guide

A complete, self-hosted M3U playlist library with a web UI. Everything
after the first boot is configured in the settings page — no manual secret
file editing is required.

## 1. Prerequisites

- Python 3.11+ (Debian 12 ships 3.11)
- systemd (for service + daily refresh timer)
- An M3U playlist URL from your streaming provider
- Optional: a TMDB API key or bearer token for metadata
  ([themoviedb.org → Settings → API](https://www.themoviedb.org/settings/api))

## 2. Install the application

```bash
sudo install -d -m 0755 -o <user> -g <group> /opt/apps/m3u-library
git clone https://github.com/mb86231/m3u-playlist.git /opt/apps/m3u-library
cd /opt/apps/m3u-library
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

`<user>` is the account the service will run as (this guide uses `apps`).

## 3. Create the data directory

Runtime data and secrets live outside the code directory:

```bash
sudo install -d -m 0750 -o apps -g apps /var/lib/apps/m3u-library
sudo -u apps cp /opt/apps/m3u-library/.env.example /var/lib/apps/m3u-library/.env
sudo -u apps chmod 0600 /var/lib/apps/m3u-library/.env
```

## 4. systemd service

Install the units from the repo:

```bash
sudo cp systemd/m3u-library.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now m3u-library.service
```

The unit loads `/var/lib/apps/m3u-library/.env` as its `EnvironmentFile`.
If your user/data dir differs from the defaults, adjust `User`, `Group`,
`WorkingDirectory`, and `EnvironmentFile` in the unit first. The packaged
unit expects:

- app code in `/opt/apps/m3u-library`
- data in `/var/lib/apps/m3u-library`

## 5. First-run setup and configuration

Open **http://<host>:8000/settings**:

1. **Choose the admin password** (first run only; minimum 8 characters).
   It is stored as a bcrypt hash in `/var/lib/apps/m3u-library/secrets.json`
   (mode `0600`).
2. **M3U playlist URL** — your provider's playlist link.
3. **TMDB API key or bearer token** — one of the two is enough.
4. **Metadata language** — e.g. `en-US`, `de-DE`.

Press *Save settings*. The values are written to the `.env` file (mode
`0600`) **and** the running process, so they take effect immediately.
`POST /api/refresh`, metadata warm-up, and all admin actions are now
protected: browsers use the login session, scripts use the API key.

Then open **http://<host>:8000/** and press **Refresh Library**.

## 6. Daily auto-refresh (systemd timer)

```bash
sudo cp systemd/m3u-library-refresh.service /etc/systemd/system/
sudo cp systemd/m3u-library-refresh.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now m3u-library-refresh.timer
```

The timer posts to `/api/refresh` daily at 12:00, authenticating with the
`API_KEY` from the `.env` file. If you regenerate the API key on the
settings page, update it in the `.env` file — the timer reads the file on
every run, so no further action is needed after the file is updated.

Check status:

```bash
systemctl list-timers m3u-library-refresh.timer
systemctl status m3u-library-refresh.service
```

## 7. Optional: API key for external clients

Scripts that call protected endpoints (the refresh timer, custom cron
jobs) authenticate with `X-API-Key`. Find or regenerate the key on the
settings page (*API key for external clients* → *Reveal* / *Regenerate*).

```bash
curl -X POST -H "X-API-Key: <key>" http://<host>:8000/api/refresh
```

## 8. Optional: HTTPS reverse proxy

The app serves plain HTTP, which is fine on a trusted LAN. If you expose
it beyond localhost, put it behind an HTTPS reverse proxy (Caddy, nginx,
Traefik) and set `SECURE_COOKIES=true` in the `.env` file so session
cookies get the `Secure` flag.

## Where things live

| Path | Content | Permissions |
|------|---------|-------------|
| `/var/lib/apps/m3u-library/.env` | playlist URL, TMDB credentials, API key | `0600` |
| `/var/lib/apps/m3u-library/secrets.json` | admin password hash, session secret | `0600` |
| `/var/lib/apps/m3u-library/app.db` | SQLite library + metadata cache | — |

Neither file is ever written to Git or included in backups you publish.
