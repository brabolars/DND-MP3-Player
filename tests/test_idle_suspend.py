# tests/test_idle_suspend.py
"""Idle suspension: transmit nothing when silent, without killing a start.

A persistent mixer would otherwise send encoded silence forever (audible as idle
hiss, and the bot shows as permanently speaking).  Suspending it is easy; the
hard part is not tearing it down while a track is still being prepared.
"""

import pytest

from dndmusic.audio.mixer import MUSIC_BUS, GainRamp, Voice
from dndmusic.core.debug import DebugLogger
from dndmusic.core.playlist import PlaylistManager
from dndmusic.engine.player import IDLE_SUSPEND_SECONDS, MusicEngine


class StubVoiceClient:
    def __init__(self) -> None:
        self.source = None
        self.plays = 0
        self.stops = 0

    def is_connected(self) -> bool:
        return True

    def is_playing(self) -> bool:
        return self.source is not None

    def play(self, source, after=None) -> None:
        self.source = source
        self.plays += 1

    def stop(self) -> None:
        self.source = None
        self.stops += 1


class SilentStream:
    def read_frame(self):
        return b"\x00" * 3840

    def stop(self):
        return None


@pytest.fixture()
def engine(data_root):
    return MusicEngine(PlaylistManager(), DebugLogger())


def test_attaching_does_not_transmit(engine):
    client = StubVoiceClient()
    engine.attach_voice_client(client)
    assert client.plays == 0
    assert engine.source is None


def test_mixer_starts_on_demand_and_is_reused(engine):
    client = StubVoiceClient()
    engine.attach_voice_client(client)

    first = engine._ensure_source()
    assert first is not None and client.plays == 1
    assert engine._ensure_source() is first  # idempotent
    assert client.plays == 1


def test_suspend_fires_after_the_threshold(engine):
    client = StubVoiceClient()
    engine.attach_voice_client(client)
    source = engine._ensure_source()

    for _ in range(3):
        source.read()
    assert engine.suspend_if_idle() is False  # not idle long enough

    source.idle_frames = int(IDLE_SUSPEND_SECONDS * 1000 / 20) + 1
    assert engine.suspend_if_idle() is True
    assert client.stops == 1
    assert engine.source is None


def test_suspend_refuses_while_a_voice_exists(engine):
    client = StubVoiceClient()
    engine.attach_voice_client(client)
    source = engine._ensure_source()
    source.add_voice(Voice(stream=SilentStream(), bus=MUSIC_BUS, gain=GainRamp(1.0)))

    source.idle_frames = 10_000  # even with a huge idle count
    assert engine.suspend_if_idle() is False
    assert engine.source is source


def test_suspend_refuses_while_a_start_is_in_flight(engine):
    """The regression: measuring loudness takes seconds, and the mixer is empty
    for all of it.  Suspending then would pull it out from under the start."""
    client = StubVoiceClient()
    engine.attach_voice_client(client)
    source = engine._ensure_source()
    source.idle_frames = 10_000

    engine._track_start(+1)
    assert engine.suspend_if_idle() is False, "a pending start must block suspension"
    assert engine.source is source

    engine._track_start(-1)
    assert engine.suspend_if_idle() is True


def test_pending_counter_never_goes_negative(engine):
    engine._track_start(-1)
    engine._track_start(-1)
    assert engine._pending_starts == 0


def test_suspend_is_a_noop_without_a_session(engine):
    assert engine.suspend_if_idle() is False
