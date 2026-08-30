# src/dndmusic/audio/opus.py
"""libopus discovery and loading.

Voice output silently does nothing without opus, so this tries every sane
location before giving up: bundled next to the .exe, inside the disnake
package, system library names, ctypes' finder, and finally a download.
"""

from __future__ import annotations

import ctypes.util
import io
import os
import sys
from pathlib import Path
from typing import Callable, List

from ..config import bundle_dir
from ..discord_api import DISCORD_AVAILABLE, disnake

OPUS_DOWNLOAD_URL = (
    "https://github.com/xiph/opus/releases/download/v1.5.2/opus-1.5.2-win-x64.zip"
)

Logger = Callable[[str], None]


def _candidate_paths() -> List[Path]:
    candidates: List[Path] = []
    if DISCORD_AVAILABLE:
        try:
            candidates.append(Path(disnake.__file__).parent / "bin" / "libopus-0.x64.dll")
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


def download_allowed() -> bool:
    """Fetching a DLL and loading it is code execution, so it is opt-in.

    disnake ships libopus in its own package, which is where it is found on
    virtually every install — so this path is a rarely-needed last resort, and
    defaulting it off costs almost nothing.  Set DND_ALLOW_OPUS_DOWNLOAD=1 to
    enable it.
    """
    return os.getenv("DND_ALLOW_OPUS_DOWNLOAD", "").strip() not in ("", "0", "false", "False")


def ensure_opus(log: Logger = print, allow_download: bool = False) -> bool:
    """Return True if opus is loaded (or was already)."""
    if not DISCORD_AVAILABLE:
        return False
    if disnake.opus.is_loaded():
        return True

    for path in _candidate_paths():
        if path.exists():
            try:
                disnake.opus.load_opus(str(path))
                if disnake.opus.is_loaded():
                    log(f"Opus loaded from: {path}")
                    return True
            except Exception:
                continue

    for name in ("libopus-0.x64", "libopus-0", "opus", "libopus", "libopus.so.0"):
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

    if (allow_download or download_allowed()) and sys.platform == "win32":
        if download_opus(log):
            return disnake.opus.is_loaded()
    elif sys.platform == "win32":
        log(
            "Opus not found. Place libopus-0.dll next to the app, or set "
            "DND_ALLOW_OPUS_DOWNLOAD=1 to fetch it automatically."
        )

    log("OPUS NOT LOADED — voice audio will NOT work. Place libopus-0.dll next to the app.")
    return False


def download_opus(log: Logger = print) -> bool:
    """Last resort on Windows: fetch the DLL from the official xiph release.

    There is no signature to verify against, so this is only as trustworthy as
    the transport and the host.  It is therefore opt-in, HTTPS-only, and the
    result is sanity-checked before being loaded.
    """
    try:
        import urllib.request
        import zipfile

        if not OPUS_DOWNLOAD_URL.lower().startswith("https://"):
            log("Refusing to download Opus over a non-HTTPS URL")
            return False

        dest = Path(os.getcwd()) / "libopus-0.dll"
        log(f"Downloading Opus from {OPUS_DOWNLOAD_URL}")
        with urllib.request.urlopen(OPUS_DOWNLOAD_URL, timeout=15) as response:
            archive = zipfile.ZipFile(io.BytesIO(response.read()))
            for entry in archive.namelist():
                if entry.endswith(".dll") and "opus" in entry.lower():
                    dest.write_bytes(archive.read(entry))
                    break

        if dest.exists() and dest.stat().st_size > 10_000:
            with dest.open("rb") as handle:
                if handle.read(2) != b"MZ":     # not a Windows DLL at all
                    log("Downloaded file is not a DLL; discarding it")
                    dest.unlink(missing_ok=True)
                    return False
            disnake.opus.load_opus(str(dest))
            if disnake.opus.is_loaded():
                log("Opus downloaded and loaded!")
                return True
    except Exception as exc:
        log(f"Opus auto-download failed: {exc}")
    return False