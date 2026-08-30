# tests/test_looping.py
"""LoopingStream — repeat playback with a mutable loop flag."""

import shutil
import subprocess

import pytest

from dndmusic.audio.pcm import FRAME_BYTES, FRAME_SAMPLES, array_to_frame
from dndmusic.audio.stream import FFmpegPcmStream, LoopingStream


class FiniteStream:
    """N frames then EOF, with a decoder_finished flag like the real thing."""

    def __init__(self, frames: int = 5, value: int = 1000) -> None:
        self.frame = array_to_frame([value] * FRAME_SAMPLES)
        self.remaining = frames
        self.stopped = False

    def read_frame(self):
        if self.remaining <= 0:
            return None
        self.remaining -= 1
        return self.frame

    @property
    def decoder_finished(self) -> bool:
        return self.remaining <= 1

    def stop(self):
        self.stopped = True


class BrokenStream:
    """Yields nothing at all — a deleted or unreadable file."""

    def read_frame(self):
        return None

    def stop(self):
        return None


def test_loop_repeats_past_the_end_of_the_source():
    stream = LoopingStream(lambda: FiniteStream(5), loop=True)
    frames = [stream.read_frame() for _ in range(18)]
    assert all(f is not None for f in frames)
    assert stream.passes > 3


def test_frames_stay_the_right_size_across_the_boundary():
    stream = LoopingStream(lambda: FiniteStream(2), loop=True)
    for _ in range(10):
        assert len(stream.read_frame()) == FRAME_BYTES


def test_no_loop_ends_after_one_pass():
    stream = LoopingStream(lambda: FiniteStream(4), loop=False)
    assert len([1 for _ in range(4) if stream.read_frame() is not None]) == 4
    assert stream.read_frame() is None
    assert stream.passes == 1


def test_loop_can_be_switched_off_mid_playback():
    """The current pass finishes; it just isn't repeated again."""
    stream = LoopingStream(lambda: FiniteStream(4), loop=True)
    for _ in range(6):
        stream.read_frame()
    assert stream.passes == 2

    stream.loop = False
    remaining = 0
    while stream.read_frame() is not None and remaining < 20:
        remaining += 1
    assert remaining < 20, "should have stopped at the end of the pass"


def test_loop_can_be_switched_on_mid_playback():
    stream = LoopingStream(lambda: FiniteStream(3), loop=False)
    stream.read_frame()
    stream.loop = True
    for _ in range(9):
        assert stream.read_frame() is not None
    assert stream.passes > 1


def test_next_pass_is_prepared_before_it_is_needed():
    """Gapless handover: the successor exists before the current pass ends."""
    stream = LoopingStream(lambda: FiniteStream(4), loop=True)
    stream.read_frame()
    assert stream._next is None
    stream.read_frame()
    stream.read_frame()  # decoder_finished becomes true here
    stream.read_frame()
    assert stream._next is not None, "successor should be spawned ahead of the boundary"


def test_unreadable_source_does_not_spin_forever():
    stream = LoopingStream(BrokenStream, loop=True)
    assert stream.read_frame() is None


def test_stop_stops_current_and_pending():
    made = []

    def factory():
        stream = FiniteStream(3)
        made.append(stream)
        return stream

    stream = LoopingStream(factory, loop=True)
    for _ in range(3):
        stream.read_frame()
    stream.stop()
    assert all(s.stopped for s in made)
    assert stream.read_frame() is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_loops_a_real_file(tmp_path):
    path = tmp_path / "short.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=0.3", "-ac", "2", "-ar", "48000",
         str(path), "-y"],
        check=True,
    )
    stream = LoopingStream(lambda: FFmpegPcmStream(str(path)), loop=True)
    try:
        stream.wait_until_ready(3)
        # 0.3s source, ask for 2s of audio
        for _ in range(100):
            assert stream.read_frame() is not None
        assert stream.passes > 1
    finally:
        stream.stop()
