# src/dndmusic/core/models.py
"""Core data types shared by every layer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class PlaybackMode(Enum):
    SINGLE = "Single Track"
    PLAYLIST = "Playlist"
    SHUFFLE = "Shuffle"
    #: Playing a track *adds* it alongside whatever is going, instead of
    #: crossfading over it.  For stacking a battle theme over a rain bed, etc.
    MULTITRACK = "Multi-track (layer)"


class OutputMode(Enum):
    """Where the mixer sends audio.

    Mutually exclusive: each frame can only be consumed once, so sending to both
    at the same time would have the two sinks stealing frames from each other.
    """

    DISCORD = "Discord bot"
    LOCAL = "This PC (MP3 player)"


class MediaKind(Enum):
    """Which library a track belongs to."""

    MUSIC = "music"
    SFX = "sfx"
    AMBIENT = "ambient"


def enum_from_value(enum_cls, value, default=None):
    """Look an enum member up by its ``.value`` (used for combo boxes)."""
    for member in enum_cls:
        if member.value == value:
            return member
    return default


@dataclass
class MusicTrack:
    filename: str
    path: str
    name: str
    category: str
    size: int
    display_name: str = ""
    #: Cached EBU R128 measurement, as {"lufs", "true_peak", "lra"}.  Measuring
    #: costs an FFmpeg pass, so it is stored with the track and reused forever.
    loudness: Optional[Dict[str, float]] = None

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name

    @property
    def is_measured(self) -> bool:
        return bool(self.loudness)

    @property
    def loudness_label(self) -> str:
        if not self.loudness:
            return "unmeasured"
        return f"{self.loudness['lufs']:.1f} LUFS"

    @property
    def size_label(self) -> str:
        if self.size > 1024 * 1024:
            return f"{self.size / (1024 * 1024):.1f}MB"
        return f"{self.size // 1024}KB"

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "path": self.path,
            "name": self.name,
            "category": self.category,
            "size": self.size,
            "display_name": self.display_name,
        }
        if self.loudness:
            payload["loudness"] = self.loudness
        return payload

    @classmethod
    def from_dict(cls, filename: str, data: Dict[str, Any], default_category: str) -> "MusicTrack":
        name = data.get("name", "")
        return cls(
            filename=filename,
            path=data.get("path", ""),
            name=name,
            category=data.get("category", default_category),
            size=int(data.get("size", 0)),
            display_name=data.get("display_name", name),
            loudness=data.get("loudness"),
        )
