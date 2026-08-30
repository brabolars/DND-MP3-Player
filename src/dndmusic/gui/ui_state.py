# src/dndmusic/gui/ui_state.py
"""Persisted UI state: chosen theme, window geometry, dock layout.

Separate from ``mixer_settings.json`` on purpose — audio settings are the thing
you tune once and want to survive anything, while layout is disposable and gets
reset when someone drags a panel into the void.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..config import paths


@dataclass
class UiState:
    theme: str = ""
    #: Qt's QMainWindow.saveGeometry()/saveState(), base64-encoded.
    geometry: str = ""
    dock_state: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)

    # ── Qt byte arrays ───────────────────────────────────────────────────

    @staticmethod
    def encode(data) -> str:
        if data is None:
            return ""
        return base64.b64encode(bytes(data)).decode("ascii")

    @staticmethod
    def decode(text: str) -> Optional[bytes]:
        if not text:
            return None
        try:
            return base64.b64decode(text.encode("ascii"))
        except Exception:
            return None

    # ── persistence ──────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "theme": self.theme,
            "geometry": self.geometry,
            "dock_state": self.dock_state,
            "extras": self.extras,
        }

    @classmethod
    def load(cls) -> "UiState":
        file = paths.ui_state_file
        if not file.exists():
            return cls()
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        state = cls()
        state.theme = str(data.get("theme", ""))
        state.geometry = str(data.get("geometry", ""))
        state.dock_state = str(data.get("dock_state", ""))
        extras = data.get("extras")
        state.extras = extras if isinstance(extras, dict) else {}
        return state

    def save(self) -> bool:
        try:
            paths.ui_state_file.write_text(
                json.dumps(self.to_dict(), indent=2), encoding="utf-8"
            )
            return True
        except Exception:
            return False
