# tests/test_playlist.py
from dndmusic.core.models import PlaybackMode
from dndmusic.core.playlist import PlaylistManager

from conftest import make_track


def build(count: int = 3) -> PlaylistManager:
    playlist = PlaylistManager()
    playlist.set_tracks([make_track(f"t{i}") for i in range(count)])
    return playlist


def test_single_mode_does_not_advance():
    playlist = build()
    playlist.mode = PlaybackMode.SINGLE
    assert playlist.advance() is None
    assert playlist.index == 0


def test_playlist_mode_wraps_around():
    playlist = build()
    playlist.mode = PlaybackMode.PLAYLIST
    assert playlist.advance().name == "t1"
    assert playlist.advance().name == "t2"
    assert playlist.advance().name == "t0"


def test_go_back_wraps_to_end():
    playlist = build()
    assert playlist.go_back().name == "t2"


def test_move_updates_cursor():
    playlist = build()
    playlist.index = 0
    assert playlist.move(0, 1) == 1
    assert playlist.index == 1
    assert [t.name for t in playlist.tracks] == ["t1", "t0", "t2"]


def test_move_out_of_range_is_noop():
    playlist = build()
    assert playlist.move(0, -1) is None


def test_remove_clamps_index():
    playlist = build()
    playlist.index = 2
    playlist.remove(2)
    assert playlist.index == 1
    assert len(playlist) == 2


def test_advance_on_empty_playlist():
    assert PlaylistManager().advance() is None
