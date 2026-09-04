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
from .audio.opus import ensure_opus
from .bot.auth import load_dotenv_if_available
from .cli import AppArgs
from .config import APP_NAME, APP_VERSION, ensure_directories, init_data_root, paths
from .core.categories import CategoryRegistry
from .core.debug import DebugLogger
from .core.library import MediaLibrary
from .core.playlist import PlaylistManager
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
        f"PyNaCl: {'OK' if voice_encryption_available() else 'MISSING — voice will fail'}",
    ]


def build_services(args: AppArgs) -> Services:
    init_data_root(args.data_dir)
    load_dotenv_if_available()

    debug = DebugLogger()

    categories = CategoryRegistry()
    categories.load_custom()
    ensure_directories(categories.names())

    ffmpeg = ffmpeg_status()
    if DISCORD_AVAILABLE:
        ensure_opus(lambda message: debug.log(message, "OPUS"))
    debug.log_environment(environment_report(ffmpeg))

    library = MediaLibrary(debug)
    library.load()
    # Pick up anything dropped into the folders since last run.
    library.sync_with_disk()
    library.save()

    playlist = PlaylistManager()
    settings = PlaybackSettings().load()
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