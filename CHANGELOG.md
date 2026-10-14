# Changelog

All notable changes to this project are recorded here. Format:
[Keep a Changelog](https://keepachangelog.com/), newest on top.
Versions correspond to [GitHub releases](https://github.com/mb86231/m3u-playlist/releases).

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
