# src/dndmusic/engine/__init__.py
"""Playback engine — the part that actually pushes audio into a voice channel."""

from .player import MusicEngine, PlaybackSettings

__all__ = ["MusicEngine", "PlaybackSettings"]
