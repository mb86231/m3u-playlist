# Stable item IDs migration (one-off, completed 2026-09-22)

## Background

Item IDs used to be derived from the stream URL. When the provider rotated
URLs, items were deleted and re-inserted with new IDs, orphaning watched /
favorite state and metadata. The app now uses content-derived stable IDs
(see `docs/ARCHITECTURE.md`). This document records the production migration
for history and rollback reference.

## One-off migration workflow

`.gitea/workflows/migrate-stable-ids.yml` (triggered by pushes touching the
workflow or the migration script):

1. Stops `m3u-library.service`.
2. Restores the **earliest** `app.db.pre-stable-ids-*` backup — the one
   taken before any failed attempt touched the database.
3. Takes a fresh timestamped backup.
4. Runs `scripts/migrate_to_stable_ids.py`, which:
   - backs up the DB,
   - computes stable IDs for every row,
   - merges rows that collide under the new ID scheme (keeping earliest
     `added_at`, latest `last_seen_at`, best metadata),
   - swaps in new `items` / `metadata` tables, recreates indexes, and
     recomputes `series_groups` stats.
5. Restarts the service and verifies `/api/items` is non-empty; on failure
   it rolls back to the backup taken in step 3.

This workflow is intentionally inert now — it only runs if the workflow
file or the migration script changes again. Do not re-run it against the
already-migrated database.

## Incident notes (why the restore step exists)

The first attempts failed partway (`ModuleNotFoundError`, then a leftover
`items_old` table), which left the live DB with an empty `items` table while
the real data sat in `items_old`. The third run succeeded only because the
workflow was changed to restore the clean pre-migration backup first.
Lesson: always restore a known-good backup before re-running a partially
failed destructive migration, and never drop `*_old` tables until the new
tables are verified.

## Post-migration state

- `/api/items` returned ~15,018 items with watched/favorite state intact.
- Admin endpoints now require `API_KEY` (with a same-origin exemption for
  the web UI) — see `docs/ARCHITECTURE.md`.

## Rollback

If the migration had to be undone:

```bash
sudo systemctl stop m3u-library.service
sudo cp /var/lib/apps/m3u-library/app.db.pre-stable-ids-<TS> /var/lib/apps/m3u-library/app.db
sudo rm -f /var/lib/apps/m3u-library/app.db-wal /var/lib/apps/m3u-library/app.db-shm
sudo systemctl start m3u-library.service
```
