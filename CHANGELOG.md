# Changelog

All notable changes to this project are recorded here. Format:
[Keep a Changelog](https://keepachangelog.com/), newest on top.
Versions correspond to [GitHub releases](https://github.com/mb86231/m3u-playlist/releases).

## [v1.1.3] - 2026-10-25

### Added
- **Update check (GitHub releases)** - a background thread polls the public
  GitHub releases API once a day (stdlib urllib, no new dependency) and a
  dismissible chip in the library header announces a newer release next to
  the source-status chips. Purely informational like the kraken-dca-bot
  updater: nothing is downloaded or updated automatically. New admin
  settings toggle "Update check (GitHub)" (persisted in the server .env as
  `UPDATE_CHECK_ENABLED`, applied live without restart); the installed
  version is shown in Settings. The first check runs 30 s after startup
  (so a boot-time network race cannot silently void the check) and a
  failed fetch is retried once

### Changed
- **Season-based watched-new rule** - a series now also surfaces in
  "watched - new episodes" when at least one season is fully watched and
  a newer season has unwatched episodes (the Marshals case: S01 done,
  S02 open), even if the series as a whole was never completed. Migration
  5 adds `has_completed_season` with backfill; continue watching excludes
  these series so nothing appears in both sections

[v1.1.3]: https://github.com/mb86231/m3u-playlist/releases/tag/v1.1.3

## [v1.1.2] - 2026-10-23

### Added
- **Period selector in the New section** - the sorting field is replaced
  by a period selector there: last refresh, last week, last month. The
  view title carries the chosen period (e.g. "New · Last week"), the
  selection is kept in the URL, and the ordering is fixed to recently
  added

### Changed
- **Playlist refresh without login** - `POST /api/refresh` is now public:
  rebuilding the catalog exposes no secrets and must be available to
  anyone browsing the library. The `X-API-Key` header remains accepted
  (systemd timer); metadata endpoints and `/api/admin/*` stay protected

### Fixed
- **Episode watched mark lost on season switch** - marking an episode on a
  series detail page updated a flat copy of the episode list while the
  season re-render read from the original data, so switching the season
  tab and back showed the stale state until the next page load; the
  source episode is now updated along with the copy
- **Series hero stats stale after episode toggles** - the progress bar,
  watched counter, percentage, and next-episode button were rendered once
  from the state at page load and stayed stale after toggling episodes;
  they are now recomputed from the season data after every toggle

## [v1.1.1] - 2026-10-18

### Changed
- **Favorites sort by most recently favorited** - migration 4 adds
  `favorited_at` to `items` and `series_groups` and stamps it on every
  favorite toggle; the favorites sections order by it, newest first.
  Favorites set before this change fall back to the addition date.
  Continue watching and watched already ordered by most recently watched;
  the ordering is now consistent across all personal sections

## [v1.1.0] - 2026-10-18

### Added
- **Watched - New Episodes section** - main-nav list of series that were
  fully watched before and have unwatched episodes again (new season or new
  episode arrivals). The database now remembers the completion moment
  (`series_groups.completed_at`, migration 3 with backfill for already
  completed series); Continue Watching is reserved for started,
  never-completed series
- **Back button on detail pages** - series and movie info pages have a
  «Back» button that returns to the exact referring library page (filters
  and section preserved), falling back to the default library view

### Fixed
- **Series posters missing in the library** - opening a series detail page
  fetched missing TMDB metadata but stored it on a read-only database
  connection that never commits; the poster stayed absent from library
  cards until the next refresh. Metadata fetched on the detail page is now
  persisted (`write_db`), so cards show the poster immediately
- The sqlite writer connection is now closed cleanly on app shutdown

### Changed
- Navigation order: Favorites - Continue watching - Watched - New
  Episodes - Watched

[v1.1.2]: https://github.com/mb86231/m3u-playlist/releases/tag/v1.1.2
[v1.1.1]: https://github.com/mb86231/m3u-playlist/releases/tag/v1.1.1
[v1.1.0]: https://github.com/mb86231/m3u-playlist/releases/tag/v1.1.0

## [v1.0.0] - 2026-10-14

First public release.

### Added
- **Web library** - Movies, Series, and Live TV as first-class sections, with
  search, sorting, language and 4K filters, and infinite-scroll pagination
- **Duplicate collapsing** - German / Multi-Subs / 4K variants of the same
  title collapse into a single card with a version picker
- **Movie info pages** - TMDB description, rating, and a version table with
  per-version watched toggles; clicking a poster opens the info page instead
  of forcing a download
- **Series tracking** - per-episode watched toggles, season overview, and a
  *Continue Watching* section with episode progress and reset
- **Watched & favorites** - group-wide watched for movies, favorite stars on
  posters, and automatic state snapshots (30 kept) with an API restore
  endpoint
- **Secure settings UI** - all secrets (playlist URL, TMDB keys, session
  secret) are managed through a masked admin settings page, validated, and
  stored on the server only - never rendered into the UI
- **Poster proxy** - TMDB posters are fetched same-origin through
  `/api/poster` so they survive ad-blockers, DNS filtering, and browser
  throttling
- **Bilingual UI** - English (default) and Deutsch, switchable in the settings
- **CI/CD** - pytest suite plus sanitized public mirror sync

[v1.0.0]: https://github.com/mb86231/m3u-playlist/releases/tag/v1.0.0
