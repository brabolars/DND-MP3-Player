# tests/test_importer.py
"""Bulk import from a folder tree or an older install's library file."""

import json

from dndmusic.config import paths
from dndmusic.core.categories import CategoryRegistry
from dndmusic.core.importer import import_folder, import_legacy_library
from dndmusic.core.models import MediaKind


def make_tree(root, layout):
    for relative in layout:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00" * 2048)
    return root


def test_subfolders_become_categories(library, data_root, tmp_path):
    source = make_tree(tmp_path / "old", ["Battle/Ambush.mp3", "Bardic/Lute.mp3"])
    registry = CategoryRegistry()

    result = import_folder(library, registry, source)

    assert result.total == 2
    assert "Bardic" in result.categories_created
    assert registry.has("Bardic")
    assert (paths.music / "Bardic" / "Lute.mp3").exists()


def test_loose_files_land_in_the_default_category(library, data_root, tmp_path):
    source = make_tree(tmp_path / "old", ["Loose.mp3"])
    import_folder(library, CategoryRegistry(), source)
    track = library.find_by_display_name(MediaKind.MUSIC, "Loose")
    assert track is not None and track.category == "Other"


def test_non_audio_is_ignored(library, data_root, tmp_path):
    source = tmp_path / "old"
    source.mkdir()
    (source / "readme.txt").write_text("not audio")
    assert import_folder(library, CategoryRegistry(), source).total == 0


def test_importing_twice_changes_nothing(library, data_root, tmp_path):
    source = make_tree(tmp_path / "old", ["Battle/A.mp3", "Battle/B.mp3"])
    registry = CategoryRegistry()

    first = import_folder(library, registry, source)
    second = import_folder(library, registry, source)

    assert first.total == 2
    assert second.total == 0 and second.skipped == 2
    assert len(library.tracks(MediaKind.MUSIC)) == 2


def test_missing_folder_is_reported_not_raised(library, data_root, tmp_path):
    result = import_folder(library, CategoryRegistry(), tmp_path / "nope")
    assert result.total == 0 and result.failed


def test_legacy_library_keeps_names_and_measurements(library, data_root, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "Theme.mp3").write_bytes(b"\x00" * 4096)
    (old / "music_data.json").write_text(
        json.dumps(
            {
                "music_library": {
                    "Theme.mp3": {
                        "path": str(old / "Theme.mp3"),
                        "name": "Theme",
                        "category": "Tavern",
                        "size": 4096,
                        "display_name": "The Old Theme",
                        "loudness": {"lufs": -12.0, "true_peak": -1.0, "lra": 5.0},
                    }
                }
            }
        )
    )

    result = import_legacy_library(library, CategoryRegistry(), old / "music_data.json")
    assert result.total == 1

    track = library.find_by_display_name(MediaKind.MUSIC, "The Old Theme")
    assert track is not None
    assert track.category == "Tavern"
    assert track.loudness["lufs"] == -12.0    # no need to re-analyse


def test_legacy_entries_with_missing_files_are_reported(library, data_root, tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "music_data.json").write_text(
        json.dumps({"music_library": {"Gone.mp3": {"path": "/nowhere/Gone.mp3"}}})
    )
    result = import_legacy_library(library, CategoryRegistry(), old / "music_data.json")
    assert result.total == 0 and len(result.failed) == 1


def test_corrupt_legacy_file_is_reported(library, data_root, tmp_path):
    bad = tmp_path / "music_data.json"
    bad.write_text("{not json")
    result = import_legacy_library(library, CategoryRegistry(), bad)
    assert result.failed and result.total == 0
