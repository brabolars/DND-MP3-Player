# tests/test_ffmpeg_path.py
"""The configurable FFmpeg path — the fallback when bundling fails."""

import shutil

import pytest

from dndmusic.audio import ffmpeg

REAL_FFMPEG = shutil.which("ffmpeg")


@pytest.fixture(autouse=True)
def reset_override():
    yield
    ffmpeg.set_executable(None)


def test_default_is_plain_ffmpeg_so_path_is_used():
    """A bundled copy is found because the bundle dir is prepended to PATH."""
    assert ffmpeg.executable() == "ffmpeg"


@pytest.mark.skipif(REAL_FFMPEG is None, reason="ffmpeg not installed")
def test_override_is_used_when_it_exists():
    ffmpeg.set_executable(REAL_FFMPEG)
    assert ffmpeg.executable() == REAL_FFMPEG


def test_override_pointing_at_nothing_falls_back():
    """A stale saved path must not break playback outright."""
    ffmpeg.set_executable("/definitely/not/here/ffmpeg.exe")
    assert ffmpeg.executable() == "ffmpeg"


def test_empty_override_clears_it():
    ffmpeg.set_executable("")
    assert ffmpeg.executable() == "ffmpeg"


@pytest.mark.skipif(REAL_FFMPEG is None, reason="ffmpeg not installed")
def test_validation_accepts_ffmpeg_and_rejects_anything_else():
    assert ffmpeg.looks_like_ffmpeg(REAL_FFMPEG) is True
    assert ffmpeg.looks_like_ffmpeg(shutil.which("ls") or "/bin/ls") is False
    assert ffmpeg.looks_like_ffmpeg("/no/such/file") is False


@pytest.mark.skipif(REAL_FFMPEG is None, reason="ffmpeg not installed")
def test_discover_finds_one_on_path():
    assert ffmpeg.discover() == REAL_FFMPEG


@pytest.mark.skipif(REAL_FFMPEG is None, reason="ffmpeg not installed")
def test_streams_use_the_override(tmp_path):
    """Everything that shells out must go through executable(), not "ffmpeg"."""
    from dndmusic.audio.stream import FFmpegPcmStream

    ffmpeg.set_executable(REAL_FFMPEG)
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"\x00" * 16)

    stream = FFmpegPcmStream(str(audio))
    try:
        assert stream.command[0] == REAL_FFMPEG
    finally:
        stream.stop()


@pytest.mark.skipif(REAL_FFMPEG is None, reason="ffmpeg not installed")
def test_loudness_measurement_uses_the_override(tmp_path, monkeypatch):
    from dndmusic.audio import loudness

    ffmpeg.set_executable(REAL_FFMPEG)
    seen = {}

    def fake_run(command, **kwargs):
        seen["binary"] = command[0]
        raise RuntimeError("stop here")

    monkeypatch.setattr(loudness.subprocess, "run", fake_run)
    loudness.measure(str(tmp_path / "x.mp3"))
    assert seen["binary"] == REAL_FFMPEG


def test_path_persists(data_root):
    from dndmusic.engine.player import PlaybackSettings

    settings = PlaybackSettings()
    settings.ffmpeg_path = "D:/tools/ffmpeg/bin/ffmpeg.exe"
    settings.save()
    assert PlaybackSettings().load().ffmpeg_path == "D:/tools/ffmpeg/bin/ffmpeg.exe"
