# src/dndmusic/audio/ffmpeg.py
"""FFmpeg detection."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


#: Set by the app at startup from the saved setting.  Everything that shells
#: out to FFmpeg goes through :func:`executable`, so there is exactly one place
#: that decides which binary is used.
_override: Optional[str] = None


def set_executable(path: Optional[str]) -> None:
    """Point FFmpeg at a specific binary, or back to PATH with None/empty."""
    global _override, _cached
    cleaned = (path or "").strip()
    _override = cleaned or None
    _cached = None          # force re-detection with the new binary


def executable() -> str:
    """The FFmpeg to run.

    A configured path wins; otherwise plain ``ffmpeg``, which finds a bundled
    copy because the bundle directory is prepended to PATH at startup.
    """
    if _override and Path(_override).is_file():
        return _override
    return "ffmpeg"


def looks_like_ffmpeg(path: str) -> bool:
    """Cheap validation for a user-chosen file, before saving it."""
    candidate = Path(path)
    if not candidate.is_file():
        return False
    try:
        result = subprocess.run(
            [str(candidate), "-version"], capture_output=True, text=True, timeout=10
        )
    except Exception:
        return False
    return result.returncode == 0 and "ffmpeg version" in result.stdout.lower()


def discover() -> Optional[str]:
    """Look in the obvious places, so most people never need the file picker."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    guesses = [
        Path(os.getcwd()) / "ffmpeg.exe",
        Path(r"C:/ffmpeg/bin/ffmpeg.exe"),
        Path(r"C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/ffmpeg.exe",
    ]
    for guess in guesses:
        try:
            if guess.is_file():
                return str(guess)
        except OSError:
            continue
    return None


@dataclass
class FfmpegStatus:
    found: bool = False
    path: Optional[str] = None
    version: Optional[str] = None
    error: Optional[str] = None

    @property
    def label(self) -> str:
        return "OK" if self.found else "MISSING"


def detect_ffmpeg(timeout: int = 10) -> FfmpegStatus:
    status = FfmpegStatus()
    candidates = [executable()]
    if candidates[0] == "ffmpeg":
        candidates.append("ffmpeg.exe")
    for name in candidates:
        try:
            result = subprocess.run(
                [name, "-version"], capture_output=True, text=True, timeout=timeout
            )
            if result.returncode == 0:
                status.found = True
                status.path = name
                status.version = result.stdout.split("\n")[0]
                return status
        except FileNotFoundError:
            continue
        except Exception as exc:
            status.error = str(exc)
    return status


_cached: Optional[FfmpegStatus] = None


def ffmpeg_status(refresh: bool = False) -> FfmpegStatus:
    """Cached lookup — probing ffmpeg on every call is needlessly slow."""
    global _cached
    if _cached is None or refresh:
        _cached = detect_ffmpeg()
    return _cached
