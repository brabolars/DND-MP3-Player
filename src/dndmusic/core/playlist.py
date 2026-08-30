# src/dndmusic/core/playlist.py
"""Playlist state and on-disk playlist files."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import List, Optional

from ..config import paths
from .models import MusicTrack, PlaybackMode


class PlaylistManager:
    """The ordered queue plus the cursor into it.  No I/O, no UI."""

    def __init__(self) -> None:
        self.tracks: List[MusicTrack] = []
        self.index: int = 0
        self.mode: PlaybackMode = PlaybackMode.SINGLE

    def __len__(self) -> int:
        return len(self.tracks)

    def add(self, track: MusicTrack) -> None:
        self.tracks.append(track)

    def set_tracks(self, tracks: List[MusicTrack]) -> None:
        self.tracks = list(tracks)
        self.index = 0

    def clear(self) -> None:
        self.tracks.clear()
        self.index = 0

    def remove(self, position: int) -> None:
        if 0 <= position < len(self.tracks):
            self.tracks.pop(position)
            self.index = min(self.index, max(0, len(self.tracks) - 1))

    def move(self, position: int, offset: int) -> Optional[int]:
        """Move an entry up/down; returns its new position."""
        target = position + offset
        if not (0 <= position < len(self.tracks)) or not (0 <= target < len(self.tracks)):
            return None
        self.tracks.insert(target, self.tracks.pop(position))
        if self.index == position:
            self.index = target
        return target

    @property
    def current(self) -> Optional[MusicTrack]:
        if 0 <= self.index < len(self.tracks):
            return self.tracks[self.index]
        return None

    def advance(self) -> Optional[MusicTrack]:
        if not self.tracks:
            return None
        if self.mode is PlaybackMode.SINGLE:
            return None  # looping is handled by ffmpeg -stream_loop
        if self.mode is PlaybackMode.SHUFFLE:
            self.index = random.randint(0, len(self.tracks) - 1)
        else:
            self.index = (self.index + 1) % len(self.tracks)
        return self.current

    def go_back(self) -> Optional[MusicTrack]:
        if not self.tracks:
            return None
        self.index = (self.index - 1) % len(self.tracks)
        return self.current


def save_playlist(name: str, tracks: List[MusicTrack]) -> Path:
    paths.playlists.mkdir(parents=True, exist_ok=True)
    payload = [
        {"name": t.display_name, "category": t.category, "filename": t.filename} for t in tracks
    ]
    target = paths.playlists / f"{name}.json"
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def load_playlist(file: Path, music: dict) -> List[MusicTrack]:
    """Resolve a saved playlist against the current music library.

    Entries whose file no longer exists are skipped rather than failing.
    """
    entries = json.loads(Path(file).read_text(encoding="utf-8"))
    resolved: List[MusicTrack] = []
    for entry in entries:
        wanted = entry.get("filename")
        track = music.get(wanted)
        if track is None:
            # Library keys may be category-qualified; fall back to the filename.
            track = next((t for t in music.values() if t.filename == wanted), None)
        if track:
            resolved.append(track)
    return resolved
