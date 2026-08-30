# src/dndmusic/core/library.py
"""The media library: import, rename, re-categorise, delete, persist."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ..audio.loudness import Loudness, measure
from ..config import AUDIO_EXTENSIONS, paths
from .categories import FALLBACK_CATEGORY
from .debug import DebugLogger
from .models import MediaKind, MusicTrack

#: kind -> (json section name, default category)
_SECTIONS = {
    MediaKind.MUSIC: ("music_library", FALLBACK_CATEGORY),
    MediaKind.SFX: ("sound_effects_library", "SFX"),
    MediaKind.AMBIENT: ("ambient_library", "AMBIENT"),
}


@dataclass
class SyncResult:
    """What changed when the library was reconciled with the filesystem."""

    added: List[MusicTrack] = field(default_factory=list)
    removed: List[MusicTrack] = field(default_factory=list)
    recategorised: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed or self.recategorised)

    def __str__(self) -> str:
        return (
            f"+{len(self.added)} added, -{len(self.removed)} removed, "
            f"{self.recategorised} recategorised"
        )


class LibraryError(RuntimeError):
    """Raised for user-facing library problems (import failed, rename clash...)."""


class MediaLibrary:
    """Owns the three track stores and the ``music_data.json`` file."""

    def __init__(self, debug: Optional[DebugLogger] = None) -> None:
        self.debug = debug
        self._stores: Dict[MediaKind, Dict[str, MusicTrack]] = {
            MediaKind.MUSIC: {},
            MediaKind.SFX: {},
            MediaKind.AMBIENT: {},
        }

    # ── access ───────────────────────────────────────────────────────────

    def store(self, kind: MediaKind) -> Dict[str, MusicTrack]:
        return self._stores[kind]

    @property
    def music(self) -> Dict[str, MusicTrack]:
        return self._stores[MediaKind.MUSIC]

    @property
    def sfx(self) -> Dict[str, MusicTrack]:
        return self._stores[MediaKind.SFX]

    @property
    def ambient(self) -> Dict[str, MusicTrack]:
        return self._stores[MediaKind.AMBIENT]

    def tracks(self, kind: MediaKind) -> List[MusicTrack]:
        return list(self._stores[kind].values())

    def sorted_tracks(self, kind: MediaKind) -> List[MusicTrack]:
        if kind is MediaKind.MUSIC:
            return sorted(self.music.values(), key=lambda t: (t.category, t.display_name.lower()))
        return sorted(self._stores[kind].values(), key=lambda t: t.display_name.lower())

    def find(self, kind: MediaKind, filename: str) -> Optional[MusicTrack]:
        return self._stores[kind].get(filename)

    def find_by_display_name(self, kind: MediaKind, display_name: str) -> Optional[MusicTrack]:
        return next(
            (t for t in self._stores[kind].values() if t.display_name == display_name), None
        )

    def target_dir(self, kind: MediaKind, category: str) -> Path:
        if kind is MediaKind.MUSIC:
            return paths.music / category
        if kind is MediaKind.SFX:
            return paths.sfx
        return paths.ambient

    # ── mutation ─────────────────────────────────────────────────────────

    def import_file(self, source: str, kind: MediaKind, category: str) -> MusicTrack:
        src = Path(source)
        dest_dir = self.target_dir(kind, category)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        try:
            shutil.copy2(src, dest)
        except Exception as exc:
            raise LibraryError(f"Could not import {src.name}: {exc}") from exc

        track = MusicTrack(
            filename=dest.name,
            path=str(dest),
            name=src.stem,
            category=category,
            size=dest.stat().st_size,
            display_name=src.stem,
        )
        self._stores[kind][self._key_for(kind, track)] = track
        self._log(f"Imported {track.display_name} -> {kind.value}/{category}")
        return track

    def rename(self, track: MusicTrack, display_name: str) -> None:
        display_name = display_name.strip()
        if not display_name:
            raise LibraryError("Name cannot be empty.")
        track.display_name = display_name

    def move_to_category(self, track: MusicTrack, category: str) -> None:
        old = Path(track.path)
        new_dir = paths.music / category
        new_dir.mkdir(parents=True, exist_ok=True)
        new = new_dir / old.name
        try:
            old.rename(new)
        except Exception as exc:
            raise LibraryError(f"Could not move {track.display_name}: {exc}") from exc
        track.category = category
        track.path = str(new)
        self._log(f"Moved {track.display_name} -> {category}")

    def delete(self, kind: MediaKind, track: MusicTrack) -> None:
        try:
            Path(track.path).unlink(missing_ok=True)
        except Exception as exc:
            raise LibraryError(f"Could not delete {track.display_name}: {exc}") from exc
        for key, existing in list(self._stores[kind].items()):
            if existing is track or existing.path == track.path:
                del self._stores[kind][key]
        self._log(f"Deleted {track.display_name}")

    # ── disk synchronisation ─────────────────────────────────────────────

    def scan_dirs(self, kind: MediaKind) -> List[Tuple[Path, str]]:
        """Every audio file on disk for this kind, as (path, category)."""
        found: List[Tuple[Path, str]] = []
        if kind is MediaKind.MUSIC:
            root = paths.music
            if root.is_dir():
                for entry in sorted(root.iterdir()):
                    if entry.is_dir():
                        found += [
                            (f, entry.name)
                            for f in sorted(entry.iterdir())
                            if f.suffix.lower() in AUDIO_EXTENSIONS
                        ]
                    elif entry.suffix.lower() in AUDIO_EXTENSIONS:
                        # Loose file at the top level — treat as uncategorised.
                        found.append((entry, FALLBACK_CATEGORY))
            return found

        root = paths.sfx if kind is MediaKind.SFX else paths.ambient
        default = "SFX" if kind is MediaKind.SFX else "AMBIENT"
        if root.is_dir():
            found = [
                (f, default)
                for f in sorted(root.iterdir())
                if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
            ]
        return found

    def sync_with_disk(self, kinds: Optional[Iterable[MediaKind]] = None) -> SyncResult:
        """Reconcile the library with what is actually on disk.

        Adds files copied in by hand, forgets entries whose file is gone, and
        corrects paths for files that were moved between category folders.  This
        is what makes drag-and-drop into ``music_files/`` work.
        """
        result = SyncResult()

        for kind in kinds or list(MediaKind):
            store = self._stores[kind]
            on_disk = self.scan_dirs(kind)
            disk_paths = {str(path.resolve()): category for path, category in on_disk}

            # Index what we already know, by resolved path.
            known: Dict[str, str] = {}
            for key, track in list(store.items()):
                try:
                    resolved = str(Path(track.path).resolve())
                except OSError:
                    resolved = track.path
                known[resolved] = key

            # New files.
            for path, category in on_disk:
                resolved = str(path.resolve())
                if resolved in known:
                    key = known[resolved]
                    track = store[key]
                    if track.category != category:
                        track.category = category
                        result.recategorised += 1
                    continue
                track = MusicTrack(
                    filename=path.name,
                    path=str(path),
                    name=path.stem,
                    category=category,
                    size=path.stat().st_size,
                    display_name=path.stem,
                )
                store[self._key_for(kind, track)] = track
                result.added.append(track)

            # Vanished files.
            for key, track in list(store.items()):
                if not Path(track.path).exists():
                    del store[key]
                    result.removed.append(track)

        if result.changed:
            self._log(str(result), "SYNC")
        return result

    def _key_for(self, kind: MediaKind, track: MusicTrack) -> str:
        """Storage key — qualified by category only when the name collides."""
        if track.filename not in self._stores[kind]:
            return track.filename
        return f"{track.category}/{track.filename}"

    # ── loudness ─────────────────────────────────────────────────────────

    def loudness_of(self, track: MusicTrack) -> Optional[Loudness]:
        return Loudness.from_dict(track.loudness)

    def measure_track(self, track: MusicTrack, force: bool = False) -> Optional[Loudness]:
        """Measure and cache one track.  Blocking — keep it off the UI thread."""
        if track.loudness and not force:
            return Loudness.from_dict(track.loudness)
        result = measure(track.path)
        if result is None:
            self._log(f"Could not measure {track.display_name}", "ERR")
            return None
        track.loudness = result.to_dict()
        self._log(f"{track.display_name}: {result.lufs:.1f} LUFS, peak {result.true_peak:.1f} dBTP")
        return result

    def unmeasured(self, kinds: Optional[Iterable[MediaKind]] = None) -> List[MusicTrack]:
        pending: List[MusicTrack] = []
        for kind in kinds or list(MediaKind):
            pending += [t for t in self._stores[kind].values() if not t.loudness]
        return pending

    # ── persistence ──────────────────────────────────────────────────────

    def load(self) -> None:
        file = paths.library_file
        if not file.exists():
            return
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log(f"Library load error: {exc}", "ERR")
            return

        for kind, (section, default_category) in _SECTIONS.items():
            store = self._stores[kind]
            store.clear()
            for filename, info in data.get(section, {}).items():
                track = MusicTrack.from_dict(filename, info, default_category)
                if track.path and Path(track.path).exists():
                    store[filename] = track

        self._log(
            f"Loaded {len(self.music)} music, {len(self.sfx)} sfx, {len(self.ambient)} ambient",
            "LOAD",
        )

    def save(self) -> None:
        payload = {
            section: {fn: t.to_dict() for fn, t in self._stores[kind].items()}
            for kind, (section, _) in _SECTIONS.items()
        }
        tmp = paths.library_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(paths.library_file)  # atomic-ish: never leaves a half-written library

    # ── internals ────────────────────────────────────────────────────────

    def _log(self, message: str, category: str = "LIB") -> None:
        if self.debug:
            self.debug.log(message, category)
