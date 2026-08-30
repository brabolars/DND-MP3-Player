# tests/conftest.py
"""Shared fixtures.  Every test runs against a throwaway data root."""

from __future__ import annotations

import pytest

from dndmusic.config import ensure_directories, init_data_root
from dndmusic.core.categories import CategoryRegistry
from dndmusic.core.library import MediaLibrary
from dndmusic.core.models import MusicTrack


@pytest.fixture()
def data_root(tmp_path):
    init_data_root(tmp_path)
    ensure_directories(CategoryRegistry().names())
    return tmp_path


@pytest.fixture()
def audio_file(data_root):
    def _make(name: str = "track.mp3") -> str:
        file = data_root / name
        file.write_bytes(b"\x00" * 2048)
        return str(file)

    return _make


def make_track(name: str, category: str = "Battle") -> MusicTrack:
    return MusicTrack(f"{name}.mp3", f"/tmp/{name}.mp3", name, category, 1024)


@pytest.fixture()
def library(data_root):
    return MediaLibrary()
