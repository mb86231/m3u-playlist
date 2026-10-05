# Security Policy

## Security Features

### Architecture

1. **Minimal persistence** — a single SQLite database; schema migrations
   are versioned and transactional
2. **No shell execution from user input** — ffmpeg/ffprobe invocations use
   fixed argument lists, never a shell
3. **Parameterized SQL everywhere** — no string-built queries

### Admin authentication

- **First-run setup**: until an admin password exists, the settings page
  shows a one-time setup form. After that, setup is closed (`409`).
- **Password storage**: bcrypt hash in `secrets.json` (mode `0600`), never
  the plaintext password, never in `.env`, never in Git.
- **Sessions**: HMAC-SHA256-signed tokens (`HttpOnly`, `SameSite=Lax`,
  7-day expiry), stored server-side secrets only. With an HTTPS reverse
  proxy, set `SECURE_COOKIES=true` to add the `Secure` flag.
- **CSRF**: every state-changing request authenticated via session must
  carry the `X-CSRF-Token` header matching the token issued at login;
  login/setup additionally reject cross-origin `Origin` headers.
- **Brute-force lockout**: after 5 failed logins from one IP, further
  attempts are rejected for 30 seconds.

### Secret management

| Secret | Storage | Notes |
|--------|---------|-------|
| M3U playlist URL | `DATA_DIR/.env`, mode `0600` | entered in the settings UI |
| TMDB API key / bearer token | `DATA_DIR/.env`, mode `0600` | entered in the settings UI |
| `API_KEY` (external clients) | `DATA_DIR/.env`, mode `0600` | reveal/regenerate on the settings page |
| Admin password | `secrets.json` (bcrypt), mode `0600` | changeable in the settings UI |
| Session signing secret | `secrets.json`, mode `0600` | generated automatically |

- Secrets saved in the UI are applied to the running process immediately;
  the `.env` file keeps them across restarts (it is the systemd
  `EnvironmentFile`).
- API responses never return secrets unmasked, except to authenticated
  admins explicitly requesting reveal (`GET /api/admin/settings?reveal=1`).
- Nothing secret is committed: `.gitignore` covers `.env`, `.env.*`, and
  `secrets.json`.

### Endpoint protection

Protected: `POST /api/refresh`, `POST /api/metadata/enrich`,
`POST /api/metadata/warmup`, and everything under `/api/admin/*`.

Access is granted by either:

1. a valid admin **session** (browser, after login), with CSRF header on
   state-changing requests, or
2. a matching **`X-API-Key`** header (for scripts such as the systemd
   refresh timer).

If neither an admin password nor `API_KEY` is configured, the app is
unprotected — this state exists only to enable the first-run setup and
should be completed immediately.

## Threat Model

### Protected against

✅ **Credential exposure in Git** — secrets live outside the repo; ignore rules cover them
✅ **Password theft via disk read** — only the bcrypt hash is stored
✅ **Session forgery/tampering** — HMAC-signed tokens with server-side secret
✅ **CSRF** — per-session CSRF token required on state-changing requests
✅ **Login brute force** — per-IP lockout with exponential failure counting
✅ **SQL injection** — parameterized queries only
✅ **Command injection** — no shell execution of user input

### Residual risks

⚠️ **Filesystem access**: an attacker with shell access as the service user
can read `.env` and `secrets.json`.
- Mitigation: keep the host patched, restrict SSH, audit permissions
  (both files are `0600` owned by the service user)

⚠️ **Plain HTTP on untrusted networks**: session cookies travel unencrypted.
- Mitigation: the app is designed for LAN/trusted networks; put it behind
  an HTTPS reverse proxy (and set `SECURE_COOKIES=true`) if you expose it

⚠️ **LAN trust model**: anyone who can reach the app can see your library
catalog (posters, titles) once you are logged in or if no password is set.
- Mitigation: set the admin password during first-run setup

⚠️ **No per-user accounts**: a single admin account protects everything;
there is no multi-user or read-only mode.

## Reporting Vulnerabilities

If you discover a security vulnerability:

1. **Do NOT** open a public issue
2. Contact the repository owner privately
3. Include: description, reproduction steps, potential impact, suggested
   fix (if any)

## Security Checklist for Deployment

- [ ] Admin password chosen during first-run setup (min. 8 characters)
- [ ] `.env` and `secrets.json` are mode `0600` and owned by the service user
- [ ] HTTPS reverse proxy (with `SECURE_COOKIES=true`) when exposed beyond localhost
- [ ] Host is patched; SSH access restricted
- [ ] API key rotated if it may have leaked (settings page → Regenerate)
- [ ] Backups of the data dir are stored with the same care as the live files
