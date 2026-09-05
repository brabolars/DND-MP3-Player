# src/dndmusic/audio/process.py
"""Spawning FFmpeg without a console window popping up.

On Windows, a process started from a GUI app gets its own console unless told
otherwise.  The app is built ``--windowed``, so every track, SFX and loudness
measurement would flash a black box on screen — several per minute during a
session.  ``CREATE_NO_WINDOW`` suppresses that; on other platforms these flags
do not exist and the helper returns nothing.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Dict

#: Documented in the Windows API as 0x08000000.  Exposed by Python 3.7+ as
#: subprocess.CREATE_NO_WINDOW, but guarded so this module imports anywhere.
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def hidden_process_kwargs() -> Dict[str, Any]:
    """Keyword arguments that keep a child process off screen."""
    if sys.platform != "win32":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": CREATE_NO_WINDOW, "startupinfo": startupinfo}
