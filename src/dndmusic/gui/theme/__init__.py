# src/dndmusic/gui/theme/__init__.py
"""Theming: data model, presets, stylesheet generation, editor dialog.

``models``, ``presets`` and ``stylesheet`` are pure Python — no Qt — so they can
be imported and tested anywhere.  ``ThemeManager`` needs Qt (it composites
background images), so it is imported lazily: reading a colour shouldn't require
a GUI toolkit to be installed.
"""

from typing import TYPE_CHECKING, Any

from .models import ThemeConfig, VisualStyle
from .presets import PRESET_THEMES
from .stylesheet import build_stylesheet

if TYPE_CHECKING:  # pragma: no cover - import for type checkers only
    from .manager import ThemeManager

__all__ = [
    "ThemeManager",
    "ThemeConfig",
    "VisualStyle",
    "PRESET_THEMES",
    "build_stylesheet",
]


def __getattr__(name: str) -> Any:
    """PEP 562 lazy import, so Qt is only required if you ask for it."""
    if name == "ThemeManager":
        from .manager import ThemeManager

        return ThemeManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")