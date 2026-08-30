# tests/test_categories.py
from dndmusic.core.categories import DEFAULT_CATEGORIES, CategoryRegistry


def test_defaults_are_loaded(data_root):
    registry = CategoryRegistry()
    assert len(registry) == len(DEFAULT_CATEGORIES)
    assert "Battle" in registry.names()


def test_display_lookup_round_trip(data_root):
    registry = CategoryRegistry()
    display = registry.display_for("Tavern")
    assert registry.name_for(display) == "Tavern"


def test_unknown_name_falls_back_to_itself(data_root):
    assert CategoryRegistry().display_for("Nope") == "Nope"


def test_add_creates_folder_and_persists(data_root):
    registry = CategoryRegistry()
    added = registry.add("🎻", "Bardic")
    assert added is not None
    assert (data_root / "music_files" / "Bardic").is_dir()

    registry.save_custom()
    reloaded = CategoryRegistry()
    reloaded.load_custom()
    assert "Bardic" in reloaded.names()
    assert reloaded.display_for("Bardic") == "🎻 Bardic"


def test_add_duplicate_is_rejected(data_root):
    registry = CategoryRegistry()
    assert registry.add("📁", "Battle") is None
