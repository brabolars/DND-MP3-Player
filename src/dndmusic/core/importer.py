# src/dndmusic/core/importer.py
"""Bulk import: whole folders, or a library file from an older install.

Two ways in, both idempotent — importing the same source twice adds nothing the
second time, because files already known by path are skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from ..config import AUDIO_EXTENSIONS, paths
from .categories import FALLBACK_CATEGORY, CategoryRegistry
from .library import LibraryError, MediaLibrary
from .models import MediaKind, MusicTrack

Progress = Callable[[int, int, str], None]


@dataclass
class ImportResult:
    imported: List[MusicTrack] = field(default_factory=list)
    skipped: int = 0
    failed: List[str] = field(default_factory=list)
    categories_created: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.imported)

    def __str__(self) -> str:
        parts = [f"{self.total} imported"]
        if self.skipped:
            parts.append(f"{self.skipped} already present")
        if self.categories_created:
            parts.append(f"{len(self.categories_created)} new folder(s)")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        return ", ".join(parts)


def _known_paths(library: MediaLibrary, kind: MediaKind) -> set:
    known = set()
    for track in library.tracks(kind):
        try:
            known.add(Path(track.path).resolve())
        except OSError:
            continue
    return known


def _audio_files(root: Path, recursive: bool = True) -> List[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )


def import_folder(
    library: MediaLibrary,
    categories: CategoryRegistry,
    root: Path,
    kind: MediaKind = MediaKind.MUSIC,
    default_category: str = FALLBACK_CATEGORY,
    use_subfolders_as_categories: bool = True,
    progress: Optional[Progress] = None,
) -> ImportResult:
    """Copy every audio file under ``root`` into the library.

    With ``use_subfolders_as_categories`` the immediate parent folder name
    becomes the category, creating it if needed — which is what makes an old
    ``music_files/`` tree import back exactly as it was.
    """
    result = ImportResult()
    root = Path(root)
    if not root.is_dir():
        result.failed.append(f"{root} is not a folder")
        return result

    files = _audio_files(root)
    known = _known_paths(library, kind)

    for index, source in enumerate(files, start=1):
        if progress:
            progress(index, len(files), source.name)

        category = default_category
        if kind is MediaKind.MUSIC and use_subfolders_as_categories:
            parent = source.parent.name
            if source.parent != root and parent:
                category = parent

        destination = library.target_dir(kind, category) / source.name

        # Skip if we already have this file — either the source itself, or the
        # copy we would make of it.  That is what makes re-importing a folder
        # harmless rather than duplicating the whole library.
        try:
            if source.resolve() in known or destination.resolve() in known:
                result.skipped += 1
                continue
        except OSError:
            pass

        if kind is MediaKind.MUSIC and not categories.has(category):
            if categories.add("📁", category) is not None:
                result.categories_created.append(category)
                destination = library.target_dir(kind, category) / source.name

        try:
            if destination.exists() and destination.resolve() == source.resolve():
                # Already sitting in the library folder; just register it.
                track = MusicTrack(
                    filename=source.name,
                    path=str(source),
                    name=source.stem,
                    category=category,
                    size=source.stat().st_size,
                    display_name=source.stem,
                )
                library.store(kind)[library._key_for(kind, track)] = track
            else:
                track = library.import_file(str(source), kind, category)
            result.imported.append(track)
            known.add(Path(track.path).resolve())
        except (LibraryError, OSError) as exc:
            result.failed.append(f"{source.name}: {exc}")

    return result


def import_legacy_library(
    library: MediaLibrary,
    categories: CategoryRegistry,
    data_file: Path,
    progress: Optional[Progress] = None,
) -> ImportResult:
    """Import an older install's ``music_data.json``.

    The format has not changed, so this mostly means resolving each entry's path
    and copying the file across.  Entries whose file has gone are reported rather
    than silently dropped.
    """
    result = ImportResult()
    data_file = Path(data_file)
    try:
        data = json.loads(data_file.read_text(encoding="utf-8"))
    except Exception as exc:
        result.failed.append(f"Could not read {data_file.name}: {exc}")
        return result

    sections = {
        "music_library": (MediaKind.MUSIC, FALLBACK_CATEGORY),
        "sound_effects_library": (MediaKind.SFX, "SFX"),
        "ambient_library": (MediaKind.AMBIENT, "AMBIENT"),
    }

    entries = [
        (kind, default, name, info)
        for section, (kind, default) in sections.items()
        for name, info in data.get(section, {}).items()
    ]

    known = {kind: _known_paths(library, kind) for kind in MediaKind}

    for index, (kind, default, name, info) in enumerate(entries, start=1):
        if progress:
            progress(index, len(entries), name)

        source = Path(info.get("path", ""))
        if not source.exists():
            # Old libraries often point at a moved drive; try the file next to
            # the data file before giving up.
            candidate = data_file.parent / source.name
            if candidate.exists():
                source = candidate
            else:
                result.failed.append(f"{name}: file not found")
                continue

        category = info.get("category", default)
        destination = library.target_dir(kind, category) / source.name
        try:
            if source.resolve() in known[kind] or destination.resolve() in known[kind]:
                result.skipped += 1
                continue
        except OSError:
            pass

        if kind is MediaKind.MUSIC and not categories.has(category):
            if categories.add("📁", category) is not None:
                result.categories_created.append(category)

        try:
            track = library.import_file(str(source), kind, category)
            display = info.get("display_name")
            if display:
                track.display_name = display
            if info.get("loudness"):
                track.loudness = info["loudness"]   # keep the old measurement
            result.imported.append(track)
            known[kind].add(Path(track.path).resolve())
        except (LibraryError, OSError) as exc:
            result.failed.append(f"{name}: {exc}")

    return result
