# src/dndmusic/services.py
"""Composition root.

Builds every service object and wires them together.  Deliberately Qt-free so
that headless tools (tests, a future web front end, a CLI) can build the exact
same object graph the desktop app uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .audio.ffmpeg import FfmpegStatus, ffmpeg_status
from .audio.ffmpeg import discover as discover_ffmpeg
from .audio.ffmpeg import set_executable as set_ffmpeg_executable
from .audio.opus import ensure_opus
from .bot.auth import load_dotenv_if_available
from .cli import AppArgs
from .config import (
    APP_NAME,
    APP_VERSION,
    add_bundle_to_path,
    ensure_directories,
    init_data_root,
    paths,
)
from .core.categories import CategoryRegistry
from .core.debug import DebugLogger
from .core.library import MediaLibrary
from .core.playlist import PlaylistManager
from . import discord_api
from .discord_api import DISCORD_AVAILABLE, opus_loaded, voice_encryption_available
from .engine.player import MusicEngine, PlaybackSettings


@dataclass
class Services:
    debug: DebugLogger
    categories: CategoryRegistry
    library: MediaLibrary
    playlist: PlaylistManager
    engine: MusicEngine
    ffmpeg: FfmpegStatus
    discord_enabled: bool = True
    dev_mode: bool = False


def environment_report(ffmpeg: FfmpegStatus) -> List[str]:
    return [
        f"{APP_NAME} v{APP_VERSION}",
        f"Data root: {paths.root}",
        f"FFmpeg: {ffmpeg.label}",
        f"Disnake: {'OK' if DISCORD_AVAILABLE else 'NOT INSTALLED'}",
        f"Opus: {'OK' if opus_loaded() else 'MISSING'}",
        f"PyNaCl: {'OK' if voice_encryption_available() else 'MISSING — voice will fail'}"
        + (f" [{discord_api.voice_encryption_error}]" if not voice_encryption_available() else ""),
    ]


def missing_requirements(ffmpeg: FfmpegStatus, discord_enabled: bool = True) -> List[str]:
    """Anything absent that will stop the app doing its job.

    Used for the startup warning: a windowed .exe has no console, so a missing
    dependency has to be visible in the window or it just looks broken.
    """
    missing = []
    if not ffmpeg.found:
        missing.append("FFmpeg — nothing will decode or play")
    if discord_enabled:
        if not DISCORD_AVAILABLE:
            missing.append("disnake — the Discord bot cannot start")
        else:
            if not opus_loaded():
                missing.append("Opus — voice output will be silent")
            if not voice_encryption_available():
                reason = discord_api.voice_encryption_error
                detail = f" ({reason})" if reason else ""
                missing.append(f"PyNaCl — !join will fail with a voice error{detail}")
    return missing


def build_services(args: AppArgs) -> Services:
    init_data_root(args.data_dir)
    # Must happen before ffmpeg detection, or a bundled ffmpeg.exe is invisible.
    add_bundle_to_path()
    load_dotenv_if_available()

    debug = DebugLogger()

    categories = CategoryRegistry()
    categories.load_custom()
    ensure_directories(categories.names())

    # Settings first: the saved FFmpeg path has to be applied before anything
    # probes for the binary.
    settings = PlaybackSettings().load()

    # Apply the saved FFmpeg path before probing, and fall back to a scan of the
    # usual install locations so most people never touch the setting.
    if settings.ffmpeg_path:
        set_ffmpeg_executable(settings.ffmpeg_path)
    ffmpeg = ffmpeg_status()
    if not ffmpeg.found:
        discovered = discover_ffmpeg()
        if discovered:
            debug.log(f"Found FFmpeg at {discovered}", "SYS")
            set_ffmpeg_executable(discovered)
            settings.ffmpeg_path = discovered
            settings.save()
            ffmpeg = ffmpeg_status(refresh=True)
    if DISCORD_AVAILABLE:
        ensure_opus(
            lambda message: debug.log(message, "OPUS"),
            preferred=settings.opus_path or None,
        )
    debug.log_environment(environment_report(ffmpeg))

    library = MediaLibrary(debug)
    library.load()
    # Pick up anything dropped into the folders since last run.
    library.sync_with_disk()
    library.save()

    playlist = PlaylistManager()
    debug.log(
        f"Levels: music {settings.music_volume:.2f} master {settings.master_volume:.2f} "
        f"| norm {'on' if settings.normalise else 'off'} @ {settings.target_lufs:.1f} LUFS",
        "SET",
    )
    engine = MusicEngine(playlist, debug, settings=settings, library=library)

    return Services(
        debug=debug,
        categories=categories,
        library=library,
        playlist=playlist,
        engine=engine,
        ffmpeg=ffmpeg,
        discord_enabled=args.discord_enabled,
        dev_mode=args.dev,
    )