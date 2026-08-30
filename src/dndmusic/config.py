# src/dndmusic/config.py
"""Filesystem layout, constants and runtime configuration.

Everything that used to be a hard-coded relative path (``music_files/``,
``music_data.json``, ...) lives here, so no other module needs to know where
data is stored.  Paths derive from a single ``root`` that is resolved once at
startup, which is what makes the app work when frozen into an .exe.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union

APP_NAME = "D&D Music Manager"
APP_VERSION = "3.0.0"
COMMAND_PREFIX = "!"

AUDIO_FILE_FILTER = "Audio (*.mp3 *.wav *.ogg *.m4a)"
AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".m4a")

#: Optional remote token broker.  Empty string = local/.env mode.
AUTH_SERVER_URL = os.getenv("AUTH_SERVER_URL", "")


@dataclass
class Paths:
    """Every path the app touches, derived from one root directory."""

    root: Path

    @property
    def music(self) -> Path:
        return self.root / "music_files"

    @property
    def sfx(self) -> Path:
        return self.root / "sound_effects"

    @property
    def ambient(self) -> Path:
        return self.root / "ambient_sounds"

    @property
    def playlists(self) -> Path:
        return self.root / "playlists"

    @property
    def temp_mixes(self) -> Path:
        return self.root / "temp_mixes"

    @property
    def library_file(self) -> Path:
        return self.root / "music_data.json"

    @property
    def categories_file(self) -> Path:
        return self.root / "custom_categories.json"

    @property
    def themes_file(self) -> Path:
        return self.root / "custom_themes.json"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    @property
    def settings_file(self) -> Path:
        return self.root / "mixer_settings.json"

    @property
    def ui_state_file(self) -> Path:
        """Selected theme, window geometry and dock layout."""
        return self.root / "ui_state.json"

    @property
    def backgrounds(self) -> Path:
        """Images the user has picked as theme backgrounds."""
        return self.root / "backgrounds"

    def directories(self) -> list[Path]:
        return [self.music, self.sfx, self.ambient, self.playlists, self.temp_mixes,
                self.backgrounds]


#: Module-level singleton.  Mutated in place by :func:`init_data_root` so that
#: ``from ..config import paths`` stays valid no matter when it is imported.
paths = Paths(root=Path.cwd())


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Directory holding bundled resources (PyInstaller-aware)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def init_data_root(root: Optional[Union[str, os.PathLike]] = None) -> Path:
    """Resolve where user data lives.  Call once, early, before anything else.

    Priority: explicit argument, ``DND_DATA_DIR``, the .exe's folder when
    frozen, otherwise the current working directory.
    """
    chosen: Optional[Union[str, os.PathLike]] = root or os.getenv("DND_DATA_DIR")
    if chosen is None:
        chosen = Path(sys.executable).parent if is_frozen() else Path.cwd()
    paths.root = Path(chosen).expanduser().resolve()
    return paths.root


def ensure_directories(categories: Iterable[str] = ()) -> None:
    """Create the data directories (and one sub-folder per music category)."""
    for directory in paths.directories():
        directory.mkdir(parents=True, exist_ok=True)
    for category in categories:
        (paths.music / category).mkdir(parents=True, exist_ok=True)
