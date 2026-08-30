# src/dndmusic/gui/theme/presets.py
"""Built-in themes.  Add an entry here and it appears in the picker."""

from __future__ import annotations

from typing import Dict

from .models import ThemeConfig, VisualStyle

PRESET_THEMES: Dict[str, ThemeConfig] = {
    theme.name: theme
    for theme in (
        ThemeConfig("Cyber Blue", "#00d4ff", ["#0a1628", "#051020", "#000000"], 180,
                    "#0099cc", 0.4, 8, 2, VisualStyle.SCI_FI),
        ThemeConfig("Neon Purple", "#b24bf3", ["#1a0d2e", "#0d0717", "#000000"], 180,
                    "#8b2fc9", 0.4, 8, 2, VisualStyle.SCI_FI),
        ThemeConfig("Medieval Gold", "#d4af37", ["#2a1a0f", "#1a1007", "#0d0803"], 135,
                    "#8b7355", 0.3, 4, 3, VisualStyle.MEDIEVAL),
        ThemeConfig("Forest Green", "#4a8b3e", ["#1a2e17", "#0f1a0d", "#050a04"], 180,
                    "#2d5a27", 0.25, 6, 2, VisualStyle.MEDIEVAL),
        ThemeConfig("Royal Purple", "#6a0dad", ["#2d0a4a", "#1a0529", "#0d0214"], 180,
                    "#4a0976", 0.35, 5, 3, VisualStyle.MEDIEVAL),
        ThemeConfig("Ocean Blue", "#4a90e2", ["#1a3a5a", "#0f1f35", "#050a15"], 135,
                    "#2e5a8b", 0.2, 10, 1, VisualStyle.CASUAL),
        ThemeConfig("Sunset Orange", "#ff8c42", ["#3a1f0f", "#241308", "#120903"], 45,
                    "#cc6f35", 0.25, 12, 1, VisualStyle.CASUAL),
        ThemeConfig("Minimal Dark", "#e0e0e0", ["#2a2a2a", "#1a1a1a", "#0a0a0a"], 180,
                    "#606060", 0.1, 4, 1, VisualStyle.MINIMAL),
    )
}

DEFAULT_THEME_NAME = "Cyber Blue"
