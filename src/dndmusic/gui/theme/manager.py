# src/dndmusic/gui/theme/manager.py
"""Theme lookup, persistence and application."""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from ...config import paths
from .background import composite
from .models import ThemeConfig
from .presets import DEFAULT_THEME_NAME, PRESET_THEMES
from .stylesheet import build_stylesheet

CUSTOM_PREFIX = "★ "


class ThemeManager:
    def __init__(self) -> None:
        self.custom: Dict[str, ThemeConfig] = {}
        self.current: ThemeConfig = PRESET_THEMES[DEFAULT_THEME_NAME]

    # ── lookup ───────────────────────────────────────────────────────────

    def entries(self) -> List[str]:
        """Combo-box labels: presets first, then custom themes marked with a star."""
        return list(PRESET_THEMES) + [f"{CUSTOM_PREFIX}{name}" for name in self.custom]

    def label_for(self, cfg: ThemeConfig) -> str:
        return f"{CUSTOM_PREFIX}{cfg.name}" if cfg.name in self.custom else cfg.name

    def resolve(self, label: str) -> Optional[ThemeConfig]:
        name = label.replace(CUSTOM_PREFIX, "")
        return PRESET_THEMES.get(name) or self.custom.get(name)

    # ── persistence ──────────────────────────────────────────────────────

    def load(self) -> None:
        file = paths.themes_file
        if not file.exists():
            return
        try:
            for payload in json.loads(file.read_text(encoding="utf-8")):
                theme = ThemeConfig.from_dict(payload)
                self.custom[theme.name] = theme
        except Exception as exc:
            print(f"  Failed to load custom themes: {exc}")

    def save(self) -> None:
        payload = [theme.to_dict() for theme in self.custom.values()]
        paths.themes_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def remember(self, cfg: ThemeConfig) -> None:
        self.custom[cfg.name] = cfg
        self.save()

    def forget(self, name: str) -> bool:
        if name not in self.custom:
            return False
        del self.custom[name]
        self.save()
        return True

    # ── application ──────────────────────────────────────────────────────

    def apply(self, widget, cfg: ThemeConfig) -> None:
        self.current = cfg
        widget.setStyleSheet(build_stylesheet(cfg, composite(cfg) or ""))
