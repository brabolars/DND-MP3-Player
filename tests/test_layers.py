# tests/test_layers.py
"""Multiple simultaneous tracks, each with an independent fader."""

import numpy as np
import pytest

from dndmusic.audio.mixer import AMBIENT_BUS, MUSIC_BUS, GainRamp, MixingSource, Voice
from dndmusic.audio.pcm import SILENCE as SILENCE_FRAME
from dndmusic.audio.pcm import FRAME_SAMPLES, array_to_frame, frame_to_array


class ConstantStream:
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


def add(source, value, bus=MUSIC_BUS, trim=1.0, norm=1.0, label=""):
    return source.add_voice(
        Voice(
            stream=ConstantStream(value),
            bus=bus,
            gain=GainRamp(1.0),
            trim=GainRamp(trim),
            norm_gain=norm,
            label=label,
        )
    )


def first(frame: bytes) -> int:
    return int(frame_to_array(frame)[0])


def settle(source, frames=6):
    for _ in range(frames):
        frame = source.read()
    return frame


# ── layering ────────────────────────────────────────────────────────────────

def test_several_music_voices_play_together():
    source = MixingSource()
    for value in (1000, 2000, 3000):
        add(source, value)
    assert source.voice_count(MUSIC_BUS) == 3
    assert first(source.read()) == 6000


def test_each_layer_has_an_independent_fader():
    source = MixingSource()
    a = add(source, 10_000, label="A")
    b = add(source, 10_000, label="B")

    source.set_voice_trim(a.id, 0.0, ms=0)
    assert first(settle(source)) == 10_000  # only B remains audible

    source.set_voice_trim(b.id, 0.5, ms=0)
    source.set_voice_trim(a.id, 1.0, ms=0)
    assert first(settle(source)) == 15_000


def test_trim_is_addressed_by_voice_id():
    source = MixingSource()
    voice = add(source, 5_000)
    assert source.set_voice_trim(voice.id, 0.5, ms=0) is True
    assert source.set_voice_trim(999_999, 0.5) is False


def test_trim_survives_a_fade():
    """A fade must not clobber the user's fader position."""
    source = MixingSource()
    voice = add(source, 10_000, trim=0.5)
    voice.fade_to(0.0, 100)
    settle(source, 6)
    assert voice.gain.value == pytest.approx(0.0)
    assert voice.trim.target == 0.5

    voice.fade_to(1.0, 100)
    settle(source, 6)
    assert first(source.read()) == 5_000  # back to trim, not to full


def test_trim_ramps_rather_than_jumping():
    """A fader move must glide, or it clicks."""
    source = MixingSource()
    voice = add(source, 20_000)
    source.set_voice_trim(voice.id, 0.0, ms=200)  # 10 frames
    values = [first(source.read()) for _ in range(10)]
    assert values == sorted(values, reverse=True), values
    assert values[0] < 20_000 and values[0] > 0     # started moving
    assert values[3] > 0                            # still audible mid-glide
    assert values[-1] == 0                          # arrived


def test_default_trim_ramp_is_short_but_not_instant():
    source = MixingSource()
    voice = add(source, 20_000)
    source.set_voice_trim(voice.id, 0.0)  # DEFAULT_RAMP_MS
    assert 0 < first(source.read()) < 20_000


def test_layers_on_different_buses_coexist():
    source = MixingSource()
    add(source, 4_000, bus=MUSIC_BUS)
    add(source, 4_000, bus=MUSIC_BUS)
    add(source, 4_000, bus=AMBIENT_BUS)
    source.set_bus_gain(MUSIC_BUS, 0.5, ms=0)
    assert first(source.read()) == 4_000 + 4_000  # 8000*0.5 + 4000


# ── normalisation ───────────────────────────────────────────────────────────

def test_normalisation_gain_is_applied():
    source = MixingSource()
    add(source, 10_000, norm=0.5)
    assert first(source.read()) == 5_000


def test_normalisation_can_be_toggled_live():
    source = MixingSource()
    add(source, 10_000, norm=0.5)
    assert first(source.read()) == 5_000

    source.normalise = False
    assert first(source.read()) == 10_000  # same voice, same stream

    source.normalise = True
    assert first(source.read()) == 5_000


def test_normalisation_balances_two_layers():
    """A quiet and a loud track, each normalised, come out level."""
    source = MixingSource()
    add(source, 2_000, norm=4.0)   # quiet file, boosted
    add(source, 16_000, norm=0.5)  # loud file, cut
    frame = frame_to_array(source.read())
    # 8000 + 8000, so both contribute equally.
    assert int(frame[0]) == 16_000


def test_toggling_normalisation_does_not_touch_streams():
    source = MixingSource()
    voice = add(source, 8_000, norm=0.5)
    stream = voice.stream
    source.read()
    source.normalise = False
    source.read()
    assert source.voices(MUSIC_BUS)[0].stream is stream
    assert not stream.stopped


def test_clipping_is_counted():
    """Overload must be visible in diagnostics, not just audible."""
    source = MixingSource()
    for _ in range(5):
        add(source, 20_000)
    source.read()
    assert source.clipped_frames == 1

    source.set_master_gain(0.1, ms=0)
    source.read()
    assert source.clipped_frames == 1  # no further clipping once turned down


# ── pause ───────────────────────────────────────────────────────────────────

def test_pause_holds_position_instead_of_restarting():
    """The whole point: a paused stream is not read, so nothing is lost."""
    source = MixingSource()
    voice = add(source, 10_000)
    stream = voice.stream

    for _ in range(3):
        source.read()
    consumed = 1000 - stream.remaining

    source.set_voice_paused(voice.id, True)
    for _ in range(10):
        assert source.read() == SILENCE_FRAME
    assert 1000 - stream.remaining == consumed, "paused stream must not advance"

    source.set_voice_paused(voice.id, False)
    source.read()
    assert 1000 - stream.remaining == consumed + 1  # continued, not restarted
    assert voice.stream is stream                   # same decoder throughout


def test_pause_bus_reports_state():
    source = MixingSource()
    add(source, 5_000)
    add(source, 5_000)
    assert source.bus_is_paused(MUSIC_BUS) is False

    assert source.pause_bus(MUSIC_BUS, True) == 2
    assert source.bus_is_paused(MUSIC_BUS) is True

    source.pause_bus(MUSIC_BUS, False)
    assert source.bus_is_paused(MUSIC_BUS) is False


def test_pausing_music_leaves_ambient_running():
    source = MixingSource()
    add(source, 6_000, bus=MUSIC_BUS)
    ambient = add(source, 6_000, bus=AMBIENT_BUS)
    source.pause_bus(MUSIC_BUS, True)

    assert first(source.read()) == 6_000        # only ambient
    assert ambient.stream.remaining < 1000      # and it is still advancing


def test_empty_bus_pause_is_a_noop():
    source = MixingSource()
    assert source.pause_bus(MUSIC_BUS, True) == 0
    assert source.bus_is_paused(MUSIC_BUS) is False


def test_idle_frames_accrue_only_when_nothing_is_audible():
    source = MixingSource()
    for _ in range(3):
        source.read()
    assert source.idle_frames == 3
    assert source.idle_seconds == pytest.approx(0.06)

    voice = add(source, 5_000)
    source.read()
    assert source.idle_frames == 0

    # A paused voice is not audible, so idle still accrues.
    source.set_voice_paused(voice.id, True)
    for _ in range(4):
        source.read()
    assert source.idle_frames == 4


def test_adding_a_voice_clears_the_idle_counter():
    source = MixingSource()
    for _ in range(5):
        source.read()
    assert source.idle_frames == 5
    add(source, 100)
    assert source.idle_frames == 0


def test_paused_voice_marked_for_stop_is_reaped_immediately():
    """Regression: pause then change track leaked the old voice forever.

    A paused voice is skipped before its gain ramp advances, so a fade-out could
    never complete — the voice stayed, held its decoder, and blocked the idle
    suspend.  Something being discarded shouldn't wait for a fade.
    """
    source = MixingSource()
    old = add(source, 8_000, label="old")
    source.pause_bus(MUSIC_BUS, True)
    old.fade_out_and_stop(2000)
    new = add(source, 8_000, label="new")

    for _ in range(5):
        source.read()

    assert source.voices(MUSIC_BUS) == [new]
    assert old.stream.stopped


def test_pause_still_holds_a_voice_that_is_not_stopping():
    source = MixingSource()
    voice = add(source, 8_000)
    source.pause_bus(MUSIC_BUS, True)
    for _ in range(10):
        source.read()
    assert source.voices(MUSIC_BUS) == [voice]   # held, not reaped


def test_cleanup_is_idempotent():
    source = MixingSource()
    add(source, 100)
    source.cleanup()
    assert source.is_active is False
    source.cleanup()          # disnake calls this too; must not double-act
    assert source.read() == b""
