# M3U Library — Roadmap / Future TODOs

This file tracks proposals and improvements that are **not** part of the current architectural refactor. Items are grouped by area and are not ordered by priority.

## Backend

- **Structured logging** — Replace `print()` calls with stdlib `logging` or `structlog`; include request IDs and structured context.
- **Test suite expansion** — Add tests for read endpoints (`/api/items`, `/api/series`, `/api/last-watched`), metadata endpoints, and streaming helpers.
- **Metadata warmup retry/backoff strategy** — Implement exponential backoff and per-provider/per-entity failure tracking instead of fixed 0.25 s delays.
- ~~**Authentication / API keys** — Protect admin endpoints (`POST /api/refresh`, `/api/metadata/*`) with bearer tokens or session auth.~~
- ~~**Schema migration table** — Replace ad-hoc `PRAGMA table_info` checks with a versioned `migrations` table and migration runner.~~
- **FTS5 search** — Add full-text search over titles, descriptions, and series titles.
- **Provider health monitoring** — Track M3U provider fetch success/failure rates and expose a health endpoint.
- **Rate limiting / request throttling** — Add per-IP and global rate limits for public endpoints.
- **Monolith split** — Move metadata fetching into a separate service/worker that communicates via queue or API.
- **Configuration validation** — Pydantic settings model for env vars and `config.json`.
- **Database vacuum/maintenance** — Periodic `VACUUM` and WAL checkpoint scheduling.

## Frontend

- **Accessibility improvements** — ARIA labels, keyboard navigation, focus management, and screen-reader friendly status announcements.
- **Mobile responsive UI overhaul** — Better layouts, touch targets, and navigation for small screens.
- **Offline / PWA local cache** — Service worker + IndexedDB so the library works offline and syncs when reconnected.
- **Batch series actions** — Mark whole seasons or entire series as watched/favorite in one action.
- **Better loading, empty, and error states** — Skeleton loaders, retry buttons, and clearer empty-section messages.
- **Dark/light theme toggle** — User-selectable color scheme.
- **Infinite scroll** — Replace "Load more" button with virtual/infinite scrolling for large libraries.
- **Poster lazy loading** — Native `loading="lazy"` and placeholder handling for large grids.

## DevOps / Operations

- ~~**CI test pipeline** — Run `pytest` on every push in Gitea Actions before deploy.~~
- **Staged deployments** — Deploy to a staging instance before production.
- **Automated DB backups** — Pre-deploy backup step in the deploy script.
- **Metrics and alerting** — Prometheus/OpenTelemetry metrics for endpoint latency, errors, and DB queue depth.
- **Log shipping** — Forward application logs to a central log aggregator.

## Done

- ✅ CI test pipeline in Gitea Actions (tests run before deploy).
- ✅ Versioned `migrations` table and migration runner.
- ✅ API-key auth for admin endpoints (`POST /api/refresh`, `/api/metadata/*`).
- ✅ Stabilize item IDs against provider URL rotation.
- ✅ Async single-writer SQLite concurrency layer.
- ✅ Incremental M3U refresh.
- ✅ Local frontend cache + incremental DOM updates.
- ✅ Basic pytest coverage for IDs, DB concurrency, refresh delta, and ID migration.
