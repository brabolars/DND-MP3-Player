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


# ── opus is loaded as a library, so its source matters ──────────────────────

def test_there_is_no_opus_download():
    """An earlier version fetched a DLL and loaded it — code execution with no
    signature to verify.  It also pointed at a URL that 404s, so it promised a
    recovery it could never perform.  Both reasons to have removed it."""
    from dndmusic.audio import opus

    assert not hasattr(opus, "download_opus")
    assert not hasattr(opus, "OPUS_DOWNLOAD_URL")


def test_opus_is_searched_for_in_predictable_places(data_root):
    from dndmusic.audio import opus

    opus.set_library(None)
    paths = [str(p) for p in opus._candidate_paths()]
    assert any("libopus" in p for p in paths)
    # A configured path must be tried first.
    opus.set_library("/tmp/chosen/libopus-0.dll")
    assert str(opus._candidate_paths()[0]) == "/tmp/chosen/libopus-0.dll"
    opus.set_library(None)


def test_opus_validation_rejects_a_missing_file():
    from dndmusic.audio import opus

    assert opus.looks_like_opus("/no/such/libopus-0.dll") is False


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


# ── diagnosability: a windowed .exe has no console ──────────────────────────

def test_debug_logger_writes_a_session_file(data_root):
    from dndmusic.config import paths
    from dndmusic.core.debug import DebugLogger

    log = DebugLogger()
    log.log("something happened", "SYS")
    log.close()

    files = list(paths.logs.glob("session-*.log"))
    assert len(files) == 1
    assert "something happened" in files[0].read_text(encoding="utf-8")


def test_log_file_is_redacted_too(data_root):
    from dndmusic.config import paths
    from dndmusic.core.debug import DebugLogger

    log = DebugLogger()
    log.log(f"reading {paths.root}/music_files/x.mp3", "SYS")
    log.close()

    text = next(paths.logs.glob("session-*.log")).read_text(encoding="utf-8")
    assert str(paths.root) not in text
    assert "<data>" in text


def test_old_logs_are_pruned(data_root):
    from dndmusic.config import paths
    from dndmusic.core.debug import MAX_LOG_FILES, DebugLogger

    paths.logs.mkdir(parents=True, exist_ok=True)
    for index in range(MAX_LOG_FILES + 5):
        (paths.logs / f"session-2020010{index % 10}-00000{index}.log").write_text("old")

    DebugLogger().close()
    assert len(list(paths.logs.glob("session-*.log"))) <= MAX_LOG_FILES


def test_logging_survives_an_unwritable_folder(data_root, monkeypatch):
    """A read-only folder must not stop the app starting."""
    from dndmusic.core.debug import DebugLogger

    monkeypatch.setattr(
        "pathlib.Path.mkdir", lambda *a, **k: (_ for _ in ()).throw(PermissionError())
    )
    log = DebugLogger()
    log.log("still works", "SYS")
    assert log.log_file is None


def test_missing_requirements_names_each_gap():
    from dndmusic.audio.ffmpeg import FfmpegStatus
    from dndmusic.services import missing_requirements

    absent = missing_requirements(FfmpegStatus(found=False), discord_enabled=True)
    assert any("FFmpeg" in item for item in absent)

    # With Discord off, only the playback requirements matter.
    local_only = missing_requirements(FfmpegStatus(found=True), discord_enabled=False)
    assert local_only == []


def test_bundle_dir_is_added_to_path_when_frozen(monkeypatch, tmp_path):
    """Regression: a bundled ffmpeg.exe was invisible to subprocess.

    PyInstaller extracts --add-binary files to sys._MEIPASS, which is neither on
    PATH nor beside the .exe, so shelling out to "ffmpeg" could never find it.
    """
    import os

    from dndmusic import config

    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")

    assert config.add_bundle_to_path() is True
    assert os.environ["PATH"].split(os.pathsep)[0] == str(tmp_path)

    # and calling it twice must not stack duplicates
    config.add_bundle_to_path()
    assert os.environ["PATH"].split(os.pathsep).count(str(tmp_path)) == 1


def test_adding_bundle_to_path_is_a_noop_from_source(monkeypatch):
    import os

    from dndmusic import config

    monkeypatch.setattr(config.sys, "frozen", False, raising=False)
    monkeypatch.setenv("PATH", "/usr/bin")
    assert config.add_bundle_to_path() is False
    assert os.environ["PATH"] == "/usr/bin"


def test_voice_encryption_failure_records_the_reason(monkeypatch):
    """"PyNaCl missing" and "PyNaCl bundled without its cffi backend" need
    different fixes, so the reason is kept rather than swallowed."""
    import builtins

    from dndmusic import discord_api

    real_import = builtins.__import__

    def broken(name, *args, **kwargs):
        if name.startswith("nacl"):
            raise ModuleNotFoundError("No module named '_cffi_backend'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken)
    assert discord_api.voice_encryption_available() is False
    assert "_cffi_backend" in discord_api.voice_encryption_error


def test_successful_check_clears_the_reason():
    from dndmusic import discord_api

    if discord_api.voice_encryption_available():
        assert discord_api.voice_encryption_error == ""