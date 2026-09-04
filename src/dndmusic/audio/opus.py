# src/dndmusic/audio/opus.py
"""libopus discovery and loading.

Unlike FFmpeg, Opus is not a subprocess — it is a shared library loaded into
this process by disnake through ctypes.  So there is no PATH involved and no
executable to run: a specific file has to be found and handed to
``disnake.opus.load_opus()``.  Without it, disnake refuses to start a voice
connection and audio is silent.

The good news is that **disnake ships libopus itself** (``disnake/bin/
libopus-0.x64.dll``), which is where it is found on virtually every install.
The search order below tries that first, then anything bundled beside the .exe,
then system library names, then an explicitly configured path.

There is deliberately no download.  An earlier version tried to fetch a DLL from
the xiph GitHub releases, but those contain source only — the URL 404s, so the
code promised a recovery it could never perform.
"""

from __future__ import annotations

import ctypes.util
import os
import sys
from pathlib import Path
from typing import Callable, List, Optional

from ..config import bundle_dir
from ..discord_api import DISCORD_AVAILABLE, disnake

Logger = Callable[[str], None]

#: Names to try via the system loader, once explicit paths are exhausted.
SYSTEM_NAMES = ("libopus-0.x64", "libopus-0", "opus", "libopus", "libopus.so.0")

#: Set from the saved setting, same idea as the FFmpeg override.
_override: Optional[str] = None


def set_library(path: Optional[str]) -> None:
    """Point Opus at a specific DLL, or back to the search order with None."""
    global _override
    cleaned = (path or "").strip()
    _override = cleaned or None


def configured_library() -> Optional[str]:
    return _override


def _candidate_paths() -> List[Path]:
    """Explicit files to try, best first."""
    candidates: List[Path] = []

    if _override:
        candidates.append(Path(_override))

    # disnake bundles libopus; this is the normal answer.
    if DISCORD_AVAILABLE:
        try:
            package_bin = Path(disnake.__file__).parent / "bin"
            candidates += [
                package_bin / "libopus-0.x64.dll",
                package_bin / "libopus-0.x86.dll",
            ]
        except Exception:
            pass

    base = bundle_dir()
    candidates += [
        base / "libopus-0.dll",
        base / "vendor" / "libopus-0.dll",
        Path(sys.executable).parent / "libopus-0.dll",
        Path(os.getcwd()) / "libopus-0.dll",
    ]
    return candidates


def looks_like_opus(path: str) -> bool:
    """Validate a user-chosen file before saving it.

    Loading is the only real test, and it is safe: disnake ignores a second
    successful load, and a failed one raises rather than corrupting anything.
    """
    candidate = Path(path)
    if not candidate.is_file():
        return False
    if not DISCORD_AVAILABLE:
        # Cannot load it without disnake; settle for "is it a library file".
        return candidate.suffix.lower() in (".dll", ".so", ".dylib")
    try:
        disnake.opus.load_opus(str(candidate))
    except Exception:
        return False
    return disnake.opus.is_loaded()


def ensure_opus(log: Logger = print, preferred: Optional[str] = None) -> bool:
    """Find and load libopus.  Returns True if it is loaded (or already was)."""
    if not DISCORD_AVAILABLE:
        return False
    if disnake.opus.is_loaded():
        return True

    if preferred:
        set_library(preferred)

    for path in _candidate_paths():
        try:
            if not path.exists():
                continue
            disnake.opus.load_opus(str(path))
            if disnake.opus.is_loaded():
                log(f"Opus loaded from: {path}")
                return True
        except Exception:
            continue

    for name in SYSTEM_NAMES:
        try:
            disnake.opus.load_opus(name)
            if disnake.opus.is_loaded():
                log(f"Opus loaded: {name}")
                return True
        except Exception:
            continue

    found = ctypes.util.find_library("opus")
    if found:
        try:
            disnake.opus.load_opus(found)
            if disnake.opus.is_loaded():
                log(f"Opus loaded via system: {found}")
                return True
        except Exception:
            pass

    log(
        "Opus not found — voice audio will NOT work. It normally comes with "
        'disnake (pip install "disnake[voice]"); otherwise put libopus-0.dll '
        "beside the app, or use Locate libopus in the Bot Status panel."
    )
    return False
