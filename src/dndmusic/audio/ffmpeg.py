# src/dndmusic/audio/ffmpeg.py
"""FFmpeg detection."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional


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
    for name in ("ffmpeg", "ffmpeg.exe"):
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
