# src/dndmusic/core/categories.py
"""Music categories (the folders in the library tree)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

from ..config import paths

DEFAULT_CATEGORIES: Sequence[Tuple[str, str]] = (
    ("⚔️ Battle", "Battle"),
    ("🗺️ Exploration", "Exploration"),
    ("🏘️ Town", "Town"),
    ("🍺 Tavern", "Tavern"),
    ("💀 Boss", "Boss"),
    ("💔 Emotional", "Emotional"),
    ("🔮 Mystery", "Mystery"),
    ("🏃 Chase", "Chase"),
    ("🎉 Victory", "Victory"),
    ("😢 Defeat", "Defeat"),
    ("🌿 Ambient", "Ambient"),
    ("📁 Other", "Other"),
)

FALLBACK_CATEGORY = "Other"


@dataclass(frozen=True)
class Category:
    display: str
    name: str


class CategoryRegistry:
    """Ordered list of categories, with JSON persistence for custom ones."""

    def __init__(self, defaults: Iterable[Tuple[str, str]] = DEFAULT_CATEGORIES) -> None:
        self._defaults = tuple(defaults)
        self._items: List[Category] = [Category(display, name) for display, name in self._defaults]

    def __iter__(self) -> Iterator[Category]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def names(self) -> List[str]:
        return [item.name for item in self._items]

    def displays(self) -> List[str]:
        return [item.display for item in self._items]

    def display_for(self, name: str) -> str:
        for item in self._items:
            if item.name == name:
                return item.display
        return name

    def name_for(self, display: str) -> str:
        for item in self._items:
            if item.display == display:
                return item.name
        return display

    def has(self, name: str) -> bool:
        return any(item.name == name for item in self._items)

    def add(self, emoji: str, name: str) -> Optional[Category]:
        name = name.strip()
        if not name or self.has(name):
            return None
        category = Category(f"{emoji} {name}".strip(), name)
        self._items.append(category)
        (paths.music / name).mkdir(parents=True, exist_ok=True)
        return category

    # ── persistence ──────────────────────────────────────────────────────

    def custom(self) -> List[Category]:
        default_names = {name for _, name in self._defaults}
        return [item for item in self._items if item.name not in default_names]

    def load_custom(self) -> None:
        file = paths.categories_file
        if not file.exists():
            return
        try:
            for entry in json.loads(file.read_text(encoding="utf-8")):
                if not self.has(entry["name"]):
                    self._items.append(Category(entry["display"], entry["name"]))
                    (paths.music / entry["name"]).mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # corrupt file shouldn't kill startup
            print(f"  Failed to load custom categories: {exc}")

    def save_custom(self) -> None:
        payload = [{"display": c.display, "name": c.name} for c in self.custom()]
        paths.categories_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
