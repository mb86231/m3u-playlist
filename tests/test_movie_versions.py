"""Tests for movie version grouping: one card per title, versions picker data."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import m3u_library.db as db_mod
from m3u_library import main


API_KEY = "versions-test-key"


@pytest.fixture(scope="module")
def client():
    mp = pytest.MonkeyPatch()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        db_path = tmpdir_path / "app.db"
        mp.setenv("DATA_DIR", str(tmpdir_path))
        mp.setenv("DATABASE_PATH", str(db_path))
        mp.setenv("API_KEY", API_KEY)
        mp.setattr(db_mod, "DB_PATH", db_path)
        mp.setattr(db_mod, "DATA_DIR", tmpdir_path)
        mp.setattr(main, "DB_PATH", db_path)
        mp.setattr(main, "DATA_DIR", tmpdir_path)
        mp.setattr(main, "run_metadata_warmup", lambda last_refresh=None: None)
        async def _empty_ids(conn):
            return {"movie_ids": set(), "series_ids": set()}
        async def _empty_snapshot(conn):
            return {"items": []}
        mp.setattr(main, "async_trending_library_ids", _empty_ids)
        mp.setattr(main, "async_popular_library_ids", _empty_ids)
        mp.setattr(main, "async_get_upcoming_snapshot", _empty_snapshot)
        db_mod.db.path = db_path
        tmpdir_path.mkdir(parents=True, exist_ok=True)
        with TestClient(main.app) as c:
            yield c
    mp.undo()


def _write_m3u(path: Path, entries):
    lines = ["#EXTM3U"]
    for title, group, url in entries:
        lines.append(f'#EXTINF:-1 tvg-name="{title}" group-title="{group}",{title}')
        lines.append(url)
    path.write_text("\n".join(lines), encoding="utf-8")


def _seed(client, tmp_path, monkeypatch):
    m3u = tmp_path / "source.m3u"
    _write_m3u(m3u, [
        ("Juliet, Naked [DE] [2018]", "Movie: German", "http://x/movie/juliet-de"),
        ("Juliet, Naked [Multi-Subs] [2018]", "Movie: Multi Subtitles/Audio", "http://x/movie/juliet-multi"),
        ("Juliet, Naked [Multi-Subs] [2018] 4K", "Movie: 4K", "http://x/movie/juliet-4k"),
        ("Solo Trip (2020)", "Movie: German", "http://x/movie/solo"),
        ("Sport Channel HD", "Live TV", "http://x/live/sport"),
        ("Sport Channel HD", "Live TV Backup", "http://x/live/sport2"),
    ])
    monkeypatch.setenv("M3U_URL", m3u.as_uri())
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200
    return res.json()


# ---------------------------------------------------------------------------
# Unit: key / rank / tag helpers
# ---------------------------------------------------------------------------

def test_group_key_prefers_metadata_title():
    assert main.movie_group_key("Any [DE] [2018]", "Dune") == "meta:dune"
    assert main.movie_group_key("Dune [Multi-Subs]", "Dune") == "meta:dune"


def test_group_key_strips_version_markers():
    a = main.movie_group_key("Juliet, Naked [DE] [2018]", None)
    b = main.movie_group_key("Juliet, Naked [Multi-Subs] [2018] 4K", None)
    c = main.movie_group_key("Juliet, Naked [2018]", None)
    assert a == b == c


def test_group_key_keeps_distinct_titles_apart():
    assert main.movie_group_key("Back to the 90s [DE]", None) != main.movie_group_key("Back to the 90s 2 [DE]", None)


def test_quality_rank():
    assert main.movie_quality_rank("Film 4K") == 3
    assert main.movie_quality_rank("Film 1080p") == 2
    assert main.movie_quality_rank("Film 720p") == 1
    assert main.movie_quality_rank("Film") == 0


def test_version_tags():
    assert main.version_tags("Juliet, Naked [DE] [2018]", "Movie: German") == ["DE"]
    assert main.version_tags("Tony [Multi-Subs] [2026] 4K", "Movie: 4K") == ["4K", "Multi"]
    assert main.version_tags("Some Film [EN]", "Movie: English") == ["EN"]
    assert main.version_tags("Plain Film", "Movie: German") == ["DE"]


# ---------------------------------------------------------------------------
# API: dedup, versions payload, rollup
# ---------------------------------------------------------------------------

def test_duplicates_collapse_to_one_card(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    data = client.get("/api/items?limit=100").json()
    # 3 Juliet versions -> 1 card, Solo -> 1 card, 2 live channels -> 2 cards
    assert data["total"] == 4
    assert data["matched"] == 4
    juliet = next(i for i in data["items"] if "Juliet" in i["title"])
    assert juliet["version_count"] == 3
    assert len(juliet["versions"]) == 3
    # The 4K version is the representative card.
    assert juliet["id"] == next(v["id"] for v in juliet["versions"] if "4K" in v["tags"])
    all_tags = {tag for v in juliet["versions"] for tag in v["tags"]}
    assert {"4K", "Multi", "DE"} <= all_tags


def _version_id(client, title_part, tag):
    data = client.get("/api/items?limit=100").json()
    group = next(i for i in data["items"] if title_part in i["title"])
    return next(v["id"] for v in group["versions"] if tag in v["tags"])


def test_non_movie_items_not_grouped(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    data = client.get("/api/items?limit=100").json()
    live = [i for i in data["items"] if i["kind"] == "live"]
    assert len(live) == 2


def test_single_version_movie_has_tags(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    data = client.get("/api/items?limit=100").json()
    solo = next(i for i in data["items"] if "Solo" in i["title"])
    assert solo["version_count"] == 1
    assert [v["tags"] for v in solo["versions"]] == [["DE"]]


def test_favorite_rolls_up_to_group(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    # Favorite a hidden version (the German one).
    version_id = _version_id(client, "Juliet", "DE")
    res = client.post(f"/api/items/{version_id}/favorite")
    assert res.status_code == 200
    data = client.get("/api/items?limit=100").json()
    juliet = next(i for i in data["items"] if "Juliet" in i["title"])
    assert juliet["is_favorite"] == 1
    assert data["section_counts"]["favorites"] == 1


def test_watched_rolls_up_to_group(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    version_id = _version_id(client, "Juliet", "Multi")
    res = client.post(f"/api/items/{version_id}/watched")
    assert res.status_code == 200
    data = client.get("/api/items?section=watched&limit=100").json()
    titles = [i["title"] for i in data["items"]]
    assert any("Juliet" in t for t in titles)
    assert data["section_counts"]["watched"] == 1


def test_search_matches_hidden_versions(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    # "Multi" only appears in hidden versions' group/title, not the rep card.
    data = client.get("/api/items?q=Multi&limit=100").json()
    assert data["matched"] == 1
    assert "Juliet" in data["items"][0]["title"]


def test_group_filter_matches_hidden_versions(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    data = client.get("/api/items?group=Movie%3A%204K&limit=100").json()
    assert data["matched"] == 1
    assert "Juliet" in data["items"][0]["title"]


# ---------------------------------------------------------------------------
# Language / 4K filters
# ---------------------------------------------------------------------------

def test_lang_filter_matches_any_version(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    # German: Juliet (has a DE version) + Solo Trip (German) match, live channels don't.
    data = client.get("/api/items?lang=de&limit=100").json()
    titles = [i["title"] for i in data["items"]]
    assert data["matched"] == 2
    assert any("Juliet" in t for t in titles)
    assert any("Solo" in t for t in titles)

    # Multi: only Juliet has a Multi version.
    data = client.get("/api/items?lang=multi&limit=100").json()
    assert data["matched"] == 1
    assert "Juliet" in data["items"][0]["title"]


def test_uhd_filter(client, tmp_path, monkeypatch):
    _seed(client, tmp_path, monkeypatch)
    # Only the Juliet group has a 4K version.
    data = client.get("/api/items?uhd=1&limit=100").json()
    assert data["matched"] == 1
    assert "Juliet" in data["items"][0]["title"]
    # Combined with language.
    data = client.get("/api/items?uhd=1&lang=multi&limit=100").json()
    assert data["matched"] == 1


def test_series_lang_filter(client, tmp_path, monkeypatch):
    m3u = tmp_path / "series.m3u"
    _write_m3u(m3u, [
        ("German Show S01 E01", "Series: German", "http://x/series/gs01e01"),
        ("German Show S01 E02", "Series: German", "http://x/series/gs01e02"),
        ("Multi Show S01 E01", "Series: Multi Subtitles/Audio", "http://x/series/ms01e01"),
    ])
    monkeypatch.setenv("M3U_URL", m3u.as_uri())
    res = client.post("/api/refresh", headers={"X-API-Key": API_KEY})
    assert res.status_code == 200

    data = client.get("/api/series?lang=de&limit=100").json()
    titles = [i["title"] for i in data["items"]]
    assert titles == ["German Show"]
    data = client.get("/api/series?lang=multi&limit=100").json()
    titles = [i["title"] for i in data["items"]]
    assert titles == ["Multi Show"]


def test_series_list_marks_kind(client):
    """/api/series items must carry kind='series' so cards link to the
    series detail page instead of a /watch stream that 404s."""
    data = client.get("/api/series?limit=100").json()
    assert data["items"], "expected series from the previous seed"
    for item in data["items"]:
        assert item["kind"] == "series"
        assert item["episode_count"] > 0


def test_movie_has_tag_helper():
    assert main.movie_has_tag("Film [DE]", "Movie: German", "de") == 1
    assert main.movie_has_tag("Film [DE]", "Movie: German", "multi") == 0
    assert main.movie_has_tag("Tony [Multi-Subs] 4K", "Movie: 4K", "4k") == 1
    assert main.movie_has_tag("Plain", "Movie: German", "") == 1
