import hashlib

from m3u_library.main import item_id


def _expected_series_id(series_id: str, season: int | None, episode: int | None) -> str:
    key = f"series\n{series_id}\n{season}\n{episode}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _expected_movie_id(title: str) -> str:
    key = f"movie\n{title.strip().lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _expected_live_id(title: str, stream_url: str) -> str:
    key = f"{title}\n{stream_url}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def test_series_id_stable_across_url_change():
    series_id = "abc123"
    old_id = item_id(
        kind="series",
        title="My Show S01 E01",
        stream_url="http://old.example.com/episode.mp4",
        series_id=series_id,
        season_number=1,
        episode_number=1,
    )
    new_id = item_id(
        kind="series",
        title="My Show S01 E01",
        stream_url="http://new.example.com/episode.mp4",
        series_id=series_id,
        season_number=1,
        episode_number=1,
    )
    assert old_id == new_id == _expected_series_id(series_id, 1, 1)


def test_series_id_differs_by_season_or_episode():
    base = dict(kind="series", title="My Show S01 E01", stream_url="http://x.com/a.mp4", series_id="abc123")
    id1 = item_id(**base, season_number=1, episode_number=1)
    id2 = item_id(**base, season_number=1, episode_number=2)
    id3 = item_id(**base, season_number=2, episode_number=1)
    assert id1 != id2
    assert id1 != id3
    assert id2 != id3


def test_movie_id_stable_across_url_change():
    old_id = item_id(
        kind="movie",
        title="Test Movie",
        stream_url="http://old.example.com/movie.mp4",
    )
    new_id = item_id(
        kind="movie",
        title="Test Movie",
        stream_url="http://new.example.com/movie.mp4",
    )
    assert old_id == new_id == _expected_movie_id("Test Movie")


def test_movie_id_normalized():
    id1 = item_id(kind="movie", title="  Test Movie  ", stream_url="http://x.com/a.mp4")
    id2 = item_id(kind="movie", title="test movie", stream_url="http://x.com/b.mp4")
    assert id1 == id2


def test_live_id_changes_with_url():
    id1 = item_id(kind="live", title="Live Channel", stream_url="http://old.example.com/live.m3u8")
    id2 = item_id(kind="live", title="Live Channel", stream_url="http://new.example.com/live.m3u8")
    assert id1 != id2
