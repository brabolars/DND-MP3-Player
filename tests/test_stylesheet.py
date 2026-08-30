# tests/test_stylesheet.py
from dndmusic.gui.theme.models import ThemeConfig, VisualStyle
from dndmusic.gui.theme.presets import PRESET_THEMES
from dndmusic.gui.theme.stylesheet import build_stylesheet, hex_to_rgba, make_gradient


def test_hex_to_rgba():
    assert hex_to_rgba("#00d4ff", 0.5) == "rgba(0,212,255,0.5)"


def test_single_colour_gradient_is_flat():
    assert make_gradient(["#000000"], 180) == "#000000"


def test_theme_round_trips_through_dict():
    original = PRESET_THEMES["Cyber Blue"]
    clone = ThemeConfig.from_dict(original.to_dict())
    assert clone == original
    assert clone.visual_style is VisualStyle.SCI_FI


def test_every_preset_builds_a_stylesheet():
    for theme in PRESET_THEMES.values():
        sheet = build_stylesheet(theme)
        assert theme.primary in sheet
        assert "QMainWindow" in sheet
