# tests/test_stream.py
"""FFmpegPcmStream against real FFmpeg output."""

import shutil
import subprocess

import pytest

from dndmusic.audio.pcm import FRAME_BYTES, SAMPLE_RATE
from dndmusic.audio.stream import FFmpegPcmStream, SilenceStream

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=0.5", "-ac", "2", "-ar", str(SAMPLE_RATE),
         str(path), "-y"],
        check=True,
    )
    return str(path)


def test_frames_are_exactly_one_discord_frame(tone):
    stream = FFmpegPcmStream(tone)
    try:
        stream.wait_until_ready(3)
        frames = []
        while len(frames) < 5:
            frame = stream.read_frame()
            if frame is None:
                break
            frames.append(frame)
        assert frames, "no audio decoded"
        assert {len(f) for f in frames} == {FRAME_BYTES}
    finally:
        stream.stop()


def test_stream_finishes_and_reports_eof(tone):
    stream = FFmpegPcmStream(tone)
    try:
        stream.wait_until_ready(3)
        count = 0
        while count < 200:
            if stream.read_frame() is None:
                break
            count += 1
        # 0.5s of audio is ~25 frames; allow slack for padding.
        assert 20 <= count <= 40, count
        assert stream.finished
    finally:
        stream.stop()


def test_looping_stream_never_ends(tone):
    stream = FFmpegPcmStream(tone, loop=True)
    try:
        stream.wait_until_ready(3)
        for _ in range(80):  # well past the 0.5s source length
            assert stream.read_frame() is not None
    finally:
        stream.stop()


def test_stop_reaps_the_process(tone):
    stream = FFmpegPcmStream(tone, loop=True)
    stream.wait_until_ready(3)
    stream.stop()
    assert stream._process.returncode is not None, "FFmpeg left as a zombie"
    assert stream.read_frame() is None


def test_url_style_input_options_are_passed_through(tone):
    from dndmusic.audio.stream import NETWORK_INPUT_OPTIONS

    stream = FFmpegPcmStream(tone, input_options=NETWORK_INPUT_OPTIONS)
    try:
        assert "-reconnect" in stream.command
        assert stream.command.index("-reconnect") < stream.command.index("-i")
    finally:
        stream.stop()


def test_missing_file_reports_eof_rather_than_raising(tmp_path):
    stream = FFmpegPcmStream(str(tmp_path / "nope.mp3"))
    try:
        stream.wait_until_ready(2)
        assert stream.read_frame() is None
    finally:
        stream.stop()


def test_silence_stream_is_endless():
    stream = SilenceStream()
    assert len(stream.read_frame()) == FRAME_BYTES
