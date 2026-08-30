# tests/test_ui_state.py
"""Theme choice and window layout persistence."""

from dndmusic.config import paths
from dndmusic.gui.ui_state import UiState


def test_round_trip(data_root):
    state = UiState()
    state.theme = "★ Tavern Night"
    state.geometry = UiState.encode(b"\x01\x02\x03")
    state.dock_state = UiState.encode(b"\x04\x05")
    assert state.save()

    loaded = UiState.load()
    assert loaded.theme == "★ Tavern Night"
    assert UiState.decode(loaded.geometry) == b"\x01\x02\x03"
    assert UiState.decode(loaded.dock_state) == b"\x04\x05"


def test_missing_file_gives_defaults(data_root):
    state = UiState.load()
    assert state.theme == "" and state.geometry == ""


def test_corrupt_file_gives_defaults(data_root):
    paths.ui_state_file.write_text("{ not json", encoding="utf-8")
    assert UiState.load().theme == ""


def test_bad_base64_decodes_to_none(data_root):
    assert UiState.decode("not base64 !!") is None
    assert UiState.decode("") is None
