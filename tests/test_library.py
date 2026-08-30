# tests/test_library.py
import json

from dndmusic.config import paths
from dndmusic.core.library import MediaLibrary
from dndmusic.core.models import MediaKind


def test_import_copies_file_and_registers_track(library, audio_file):
    source = audio_file("Goblin Ambush.mp3")
    track = library.import_file(source, MediaKind.MUSIC, "Battle")

    assert (paths.music / "Battle" / "Goblin Ambush.mp3").exists()
    assert track.display_name == "Goblin Ambush"
    assert library.find(MediaKind.MUSIC, "Goblin Ambush.mp3") is track


def test_move_to_category_moves_the_file(library, audio_file):
    track = library.import_file(audio_file(), MediaKind.MUSIC, "Battle")
    library.move_to_category(track, "Tavern")

    assert track.category == "Tavern"
    assert (paths.music / "Tavern" / "track.mp3").exists()
    assert not (paths.music / "Battle" / "track.mp3").exists()


def test_save_and_load_round_trip(library, audio_file):
    library.import_file(audio_file("a.mp3"), MediaKind.MUSIC, "Battle")
    library.import_file(audio_file("b.mp3"), MediaKind.SFX, "SFX")
    library.save()

    payload = json.loads(paths.library_file.read_text())
    assert "music_library" in payload and "sound_effects_library" in payload

    reloaded = MediaLibrary()
    reloaded.load()
    assert len(reloaded.music) == 1
    assert len(reloaded.sfx) == 1


def test_load_skips_missing_files(library, audio_file):
    track = library.import_file(audio_file(), MediaKind.MUSIC, "Battle")
    library.save()

    (paths.music / "Battle" / track.filename).unlink()
    reloaded = MediaLibrary()
    reloaded.load()
    assert reloaded.music == {}


def test_delete_removes_file_and_entry(library, audio_file):
    track = library.import_file(audio_file(), MediaKind.MUSIC, "Battle")
    library.delete(MediaKind.MUSIC, track)
    assert library.music == {}
    assert not (paths.music / "Battle" / "track.mp3").exists()
