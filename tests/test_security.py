# tests/test_security.py
"""Checks for the things that would matter once this repo is public."""

import pytest

from dndmusic.config import paths
from dndmusic.core.categories import CategoryRegistry, sanitise_category
from dndmusic.core.debug import DebugLogger


# ── category names become folder names ──────────────────────────────────────

@pytest.mark.parametrize(
    "hostile",
    ["../../escaped", "..\\..\\escaped", "/tmp/absolute", "C:\\Windows\\System32", ".."],
)
def test_category_names_cannot_escape_the_library(data_root, hostile):
    registry = CategoryRegistry()
    registry.add("📁", hostile)

    for directory in paths.root.parent.iterdir():
        assert "escaped" not in directory.name
    for category in registry.names():
        assert "/" not in category and "\\" not in category
        assert not category.startswith(".")


def test_sanitiser_keeps_ordinary_names(data_root):
    assert sanitise_category("Battle") == "Battle"
    assert sanitise_category("  Boss Fight  ") == "Boss Fight"
    assert sanitise_category("Tavern & Inn") == "Tavern & Inn"


def test_sanitiser_rejects_names_with_nothing_left(data_root):
    assert sanitise_category("../..") == ""
    assert sanitise_category("///") == ""
    assert CategoryRegistry().add("📁", "///") is None


def test_absurdly_long_names_are_truncated(data_root):
    assert len(sanitise_category("A" * 500)) <= 64


def test_a_hostile_saved_category_file_is_sanitised_on_load(data_root):
    import json

    paths.categories_file.write_text(
        json.dumps([{"display": "x", "name": "../../escaped"}]), encoding="utf-8"
    )
    registry = CategoryRegistry()
    registry.load_custom()
    assert all(".." not in name for name in registry.names())


# ── the debug log is sent over Discord ──────────────────────────────────────

def test_debug_dump_redacts_local_paths(data_root):
    log = DebugLogger()
    log.log(f"Loaded from {paths.root}/music_files/Battle/theme.mp3")

    dump = log.dump()
    assert str(paths.root) not in dump
    assert "<data>" in dump


def test_debug_tail_is_redacted_too(data_root):
    log = DebugLogger()
    log.log(f"path: {paths.root}")
    assert str(paths.root) not in log.last(5)


# ── the opus download executes code, so it must be opt-in ───────────────────

def test_opus_download_is_off_by_default(monkeypatch):
    from dndmusic.audio import opus

    monkeypatch.delenv("DND_ALLOW_OPUS_DOWNLOAD", raising=False)
    assert opus.download_allowed() is False

    monkeypatch.setenv("DND_ALLOW_OPUS_DOWNLOAD", "1")
    assert opus.download_allowed() is True


def test_opus_download_url_is_https():
    from dndmusic.audio.opus import OPUS_DOWNLOAD_URL

    assert OPUS_DOWNLOAD_URL.startswith("https://")


# ── ffmpeg is never invoked through a shell ─────────────────────────────────

def test_ffmpeg_commands_are_argument_lists(tmp_path):
    """A filename with a quote or semicolon must not become shell syntax."""
    from dndmusic.audio.stream import FFmpegPcmStream

    nasty = tmp_path / 'evil"; touch pwned; ".mp3'
    nasty.write_bytes(b"\x00" * 16)

    stream = FFmpegPcmStream(str(nasty))
    try:
        assert isinstance(stream.command, list)
        assert str(nasty) in stream.command       # passed as one argv entry
        assert not (tmp_path / "pwned").exists()
    finally:
        stream.stop()
    assert not (tmp_path / "pwned").exists()