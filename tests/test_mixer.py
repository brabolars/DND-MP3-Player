# tests/test_mixer.py
"""The mixing graph: gains, buses, crossfades, voice lifecycle."""

import numpy as np
import pytest

from dndmusic.audio.mixer import (
    AMBIENT_BUS,
    MUSIC_BUS,
    SFX_BUS,
    GainRamp,
    MixingSource,
    Voice,
)
from dndmusic.audio.pcm import FRAME_BYTES, FRAME_SAMPLES, SILENCE, array_to_frame, frame_to_array


class ConstantStream:
    """Emits a fixed sample value; finite length so lifecycle can be tested."""

    def __init__(self, value: int, frames: int = 1000) -> None:
        self.frame = array_to_frame(np.full(FRAME_SAMPLES, value, dtype=np.int32))
        self.remaining = frames
        self.stopped = False

    def read_frame(self):
        if self.remaining <= 0:
            return None
        self.remaining -= 1
        return self.frame

    def stop(self):
        self.stopped = True


def first_sample(frame: bytes) -> int:
    return int(frame_to_array(frame)[0])


def add(source, value, bus=MUSIC_BUS, gain=1.0, frames=1000, **kwargs):
    return source.add_voice(
        Voice(stream=ConstantStream(value, frames), bus=bus, gain=GainRamp(gain), **kwargs)
    )


# ── ramps ────────────────────────────────────────────────────────────────────

def test_gain_ramp_reaches_target_and_stops():
    ramp = GainRamp(0.0)
    ramp.set(1.0, 100)  # 100ms = 5 frames
    values = [ramp.advance() for _ in range(5)]
    assert values[-1] == pytest.approx(1.0)
    assert ramp.advance() == 1.0  # doesn't overshoot


def test_gain_ramp_zero_ms_is_instant():
    ramp = GainRamp(0.0)
    ramp.set(0.7, 0)
    assert ramp.value == 0.7


def test_gain_ramp_clamps():
    ramp = GainRamp(1.0)
    ramp.set(99.0, 0)
    assert ramp.value <= 2.0
    ramp.set(-5.0, 0)
    assert ramp.value == 0.0


# ── mixing ───────────────────────────────────────────────────────────────────

def test_idle_mixer_emits_silence_never_empty():
    source = MixingSource()
    for _ in range(3):
        frame = source.read()
        assert frame == SILENCE
        assert len(frame) == FRAME_BYTES


def test_voices_sum():
    source = MixingSource()
    add(source, 1000)
    add(source, 2500)
    assert first_sample(source.read()) == 3500


def test_output_is_clipped_not_wrapped():
    source = MixingSource()
    for _ in range(4):
        add(source, 20_000)
    assert first_sample(source.read()) == 32_767


def test_bus_gain_scales_only_its_bus():
    source = MixingSource()
    add(source, 10_000, bus=MUSIC_BUS)
    add(source, 10_000, bus=AMBIENT_BUS)
    source.set_bus_gain(MUSIC_BUS, 0.0, 0)
    assert first_sample(source.read()) == 10_000  # ambient survives


def test_master_gain_scales_everything():
    source = MixingSource()
    add(source, 10_000)
    source.set_master_gain(0.5, 0)
    assert first_sample(source.read()) == 5_000


def test_volume_change_does_not_touch_the_stream():
    source = MixingSource()
    voice = add(source, 10_000)
    stream = voice.stream
    source.read()
    source.set_bus_gain(MUSIC_BUS, 0.25, 0)
    source.read()
    assert source.voices(MUSIC_BUS)[0].stream is stream  # same decoder, no restart
    assert not stream.stopped


# ── lifecycle ────────────────────────────────────────────────────────────────

def test_finished_voice_is_reaped_and_callback_fires():
    source = MixingSource()
    seen = []
    add(source, 500, frames=2, on_finish=seen.append)
    for _ in range(4):
        source.read()
    assert source.voice_count() == 0
    assert len(seen) == 1


def test_fade_out_and_stop_removes_without_notifying():
    source = MixingSource()
    seen = []
    voice = add(source, 10_000, on_finish=seen.append)
    voice.fade_out_and_stop(100)
    for _ in range(8):
        source.read()
    assert source.voice_count() == 0
    assert seen == []  # a replaced track must not trigger auto-advance


def test_crossfade_hands_over_between_voices():
    source = MixingSource()
    outgoing = add(source, 10_000)
    incoming = add(source, 10_000, gain=0.0)
    incoming.fade_to(1.0, 200)
    outgoing.fade_out_and_stop(200)

    for _ in range(12):
        source.read()

    assert incoming.gain.value == pytest.approx(1.0)
    assert source.voices(MUSIC_BUS) == [incoming]


def test_sfx_plays_alongside_music():
    source = MixingSource()
    add(source, 5_000, bus=MUSIC_BUS)
    add(source, 5_000, bus=AMBIENT_BUS)
    add(source, 5_000, bus=SFX_BUS, frames=3)
    assert first_sample(source.read()) == 15_000
    assert source.voice_count() == 3

    for _ in range(5):
        source.read()
    assert source.voice_count(SFX_BUS) == 0
    assert source.voice_count(MUSIC_BUS) == 1  # music untouched by SFX ending


def test_cleanup_stops_every_stream():
    source = MixingSource()
    voices = [add(source, 100), add(source, 100, bus=SFX_BUS)]
    source.cleanup()
    assert all(v.stream.stopped for v in voices)
    assert source.read() == b""  # only after cleanup may the source end


def test_metering_tracks_the_mix():
    source = MixingSource()
    add(source, 16_000)
    source.read()
    assert 0.4 < source.level < 0.6
    for _ in range(3):
        source.read()
    assert isinstance(source.spectrum(), np.ndarray)
