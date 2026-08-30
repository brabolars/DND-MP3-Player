# tests/test_library_sync.py
"""Disk synchronisation — files copied in by hand must appear in the library."""

from dndmusic.config import paths
from dndmusic.core.library import MediaLibrary
from dndmusic.core.models import MediaKind


def drop(directory, name: str = "dropped.mp3", size: int = 4096):
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / name
    file.write_bytes(b"\x00" * size)
    return file


def test_files_copied_into_a_category_folder_are_picked_up(library):
    drop(paths.music / "Battle", "Ambush.mp3")
    result = library.sync_with_disk()

    assert [t.display_name for t in result.added] == ["Ambush"]
    track = library.find_by_display_name(MediaKind.MUSIC, "Ambush")
    assert track is not None
    assert track.category == "Battle"


def test_sfx_and_ambient_folders_are_scanned(library):
    drop(paths.sfx, "door.wav")
    drop(paths.ambient, "rain.ogg")
    library.sync_with_disk()

    assert library.find_by_display_name(MediaKind.SFX, "door") is not None
    assert library.find_by_display_name(MediaKind.AMBIENT, "rain") is not None


def test_non_audio_files_are_ignored(library):
    (paths.music / "Battle").mkdir(parents=True, exist_ok=True)
    (paths.music / "Battle" / "notes.txt").write_text("not audio")
    assert library.sync_with_disk().added == []


def test_deleted_files_are_forgotten(library, audio_file):
    track = library.import_file(audio_file(), MediaKind.MUSIC, "Battle")
    (paths.music / "Battle" / track.filename).unlink()

    result = library.sync_with_disk()
    assert [t.display_name for t in result.removed] == [track.display_name]
    assert library.music == {}


def test_moving_a_file_between_folders_updates_its_category(library, audio_file):
    track = library.import_file(audio_file(), MediaKind.MUSIC, "Battle")
    destination = paths.music / "Tavern"
    destination.mkdir(parents=True, exist_ok=True)
    (paths.music / "Battle" / track.filename).rename(destination / track.filename)

    library.sync_with_disk()
    remaining = library.sorted_tracks(MediaKind.MUSIC)
    assert len(remaining) == 1
    assert remaining[0].category == "Tavern"


def test_same_filename_in_two_categories_both_survive(library):
    drop(paths.music / "Battle", "theme.mp3")
    drop(paths.music / "Tavern", "theme.mp3")
    library.sync_with_disk()

    tracks = library.sorted_tracks(MediaKind.MUSIC)
    assert len(tracks) == 2
    assert {t.category for t in tracks} == {"Battle", "Tavern"}


def test_sync_is_idempotent(library):
    drop(paths.music / "Battle", "one.mp3")
    library.sync_with_disk()
    second = library.sync_with_disk()
    assert not second.changed


def test_sync_survives_a_round_trip_through_disk(library):
    drop(paths.music / "Battle", "one.mp3")
    library.sync_with_disk()
    library.save()

    reloaded = MediaLibrary()
    reloaded.load()
    assert len(reloaded.music) == 1
    assert not reloaded.sync_with_disk().changed
