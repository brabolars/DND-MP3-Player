# src/dndmusic/audio/mixer.py
"""The mixer: one audio source, many voices.

This replaces the old "spawn FFmpeg with the right flags" approach.  A single
:class:`MixingSource` is handed to disnake once per voice session and lives until
the bot leaves the channel.  Everything else — volume, ambient beds, SFX,
crossfades — is a change to the mixing graph, so nothing ever restarts.

Layout::

    voice (envelope gain) ──┐
    voice (envelope gain) ──┼──► bus gain ──┐
    voice (envelope gain) ──┘   (music)     │
                                            ├──► master gain ──► Discord
    voice ──────────────────► bus (ambient) ┤
    voice ──────────────────► bus (sfx)  ───┘

Thread safety: ``read()`` runs on disnake's audio thread every 20 ms; every
other method runs on the bot loop or the UI thread.  All graph mutation happens
under ``_lock``, and finish callbacks are invoked *outside* it so a callback can
safely add another voice.
"""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np

from ..core.debug import DebugLogger
from ..discord_api import AudioSourceBase
from .pcm import (
    FRAME_MS,
    INT16_MAX,
    INT16_MIN,
    FRAME_SAMPLES,
    SILENCE,
    array_to_frame,
    frame_to_array,
    peak,
    spectrum,
)
from .stream import FrameStream

MUSIC_BUS = "music"
AMBIENT_BUS = "ambient"
SFX_BUS = "sfx"
BUSES = (MUSIC_BUS, AMBIENT_BUS, SFX_BUS)

DEFAULT_RAMP_MS = 40      # short ramp on every gain change kills zipper noise
MAX_GAIN = 2.0
SPECTRUM_BANDS = 32
_ids = itertools.count(1)


class GainRamp:
    """A gain value that slides to its target instead of jumping."""

    __slots__ = ("value", "target", "_step")

    def __init__(self, value: float = 1.0) -> None:
        self.value = float(value)
        self.target = float(value)
        self._step = 0.0

    def set(self, target: float, ms: int = DEFAULT_RAMP_MS) -> None:
        target = max(0.0, min(MAX_GAIN, float(target)))
        self.target = target
        if ms <= 0:
            self.value = target
            self._step = 0.0
            return
        frames = max(1, int(ms / FRAME_MS))
        self._step = (target - self.value) / frames

    def advance(self) -> float:
        if self.value != self.target:
            self.value += self._step
            if (self._step >= 0 and self.value >= self.target) or (
                self._step < 0 and self.value <= self.target
            ):
                self.value = self.target
                self._step = 0.0
        return self.value

    @property
    def at_target(self) -> bool:
        return self.value == self.target


@dataclass
class Voice:
    """One playing stream and the three gains applied to it.

    ``gain``      envelope — owned by the engine, drives fades and crossfades
    ``trim``      the user's per-track slider
    ``norm_gain`` static loudness-normalisation multiplier

    Keeping them separate is what lets a track be faded out without losing its
    trim, and lets normalisation be toggled without disturbing either.
    """

    stream: FrameStream
    bus: str
    gain: GainRamp
    trim: GainRamp = field(default_factory=lambda: GainRamp(1.0))
    norm_gain: float = 1.0
    label: str = ""
    loop: bool = False
    paused: bool = False
    stop_when_silent: bool = False
    notify_on_finish: bool = True
    on_finish: Optional[Callable[["Voice"], None]] = None
    id: int = field(default_factory=lambda: next(_ids))

    def fade_to(self, target: float, ms: int) -> None:
        self.gain.set(target, ms)

    def fade_out_and_stop(self, ms: int) -> None:
        self.stop_when_silent = True
        self.notify_on_finish = False
        self.gain.set(0.0, ms)

    def set_trim(self, value: float, ms: int = DEFAULT_RAMP_MS) -> None:
        self.trim.set(value, ms)


class MixingSource(AudioSourceBase):
    """A disnake AudioSource that mixes an arbitrary number of voices."""

    def __init__(self, debug: Optional[DebugLogger] = None) -> None:
        self.debug = debug
        self._lock = threading.RLock()
        self._voices: List[Voice] = []
        self.master = GainRamp(1.0)
        self.buses: Dict[str, GainRamp] = {name: GainRamp(1.0) for name in BUSES}

        self._peak = 0.0
        self._spectrum = np.zeros(SPECTRUM_BANDS, dtype=np.float32)
        self._active = True
        self.frames_mixed = 0
        #: Frames that exceeded int16 range before clipping — i.e. audible
        #: distortion.  Surfaced in the UI so overload is diagnosable.
        self.clipped_frames = 0
        #: Consecutive frames with nothing to mix.  The engine uses this to stop
        #: transmitting entirely when idle, rather than sending encoded silence.
        self.idle_frames = 0
        #: When False, per-voice ``norm_gain`` is ignored (instant, no restart).
        self.normalise = True

    # ── graph mutation ───────────────────────────────────────────────────

    def add_voice(self, voice: Voice) -> Voice:
        with self._lock:
            self._voices.append(voice)
        self.idle_frames = 0
        return voice

    def voices(self, bus: Optional[str] = None) -> List[Voice]:
        with self._lock:
            if bus is None:
                return list(self._voices)
            return [v for v in self._voices if v.bus == bus]

    def voice_count(self, bus: Optional[str] = None) -> int:
        return len(self.voices(bus))

    def find_voice(self, voice_id: int) -> Optional[Voice]:
        with self._lock:
            return next((v for v in self._voices if v.id == voice_id), None)

    def set_voice_paused(self, voice_id: int, paused: bool) -> bool:
        voice = self.find_voice(voice_id)
        if voice is None:
            return False
        voice.paused = paused
        return True

    def pause_bus(self, bus: str, paused: bool) -> int:
        voices = [v for v in self.voices(bus) if not v.stop_when_silent]
        for voice in voices:
            voice.paused = paused
        return len(voices)

    def bus_is_paused(self, bus: str) -> bool:
        voices = [v for v in self.voices(bus) if not v.stop_when_silent]
        return bool(voices) and all(v.paused for v in voices)

    def set_voice_trim(self, voice_id: int, value: float, ms: int = DEFAULT_RAMP_MS) -> bool:
        voice = self.find_voice(voice_id)
        if voice is None:
            return False
        voice.set_trim(value, ms)
        return True

    def remove_voice(self, voice: Voice) -> None:
        with self._lock:
            if voice in self._voices:
                self._voices.remove(voice)
        voice.stream.stop()

    def stop_bus(self, bus: str, fade_ms: int = 0) -> None:
        for voice in self.voices(bus):
            if fade_ms > 0:
                voice.fade_out_and_stop(fade_ms)
            else:
                self.remove_voice(voice)

    def stop_all(self, fade_ms: int = 0) -> None:
        for bus in BUSES:
            self.stop_bus(bus, fade_ms)

    def set_bus_gain(self, bus: str, gain: float, ms: int = DEFAULT_RAMP_MS) -> None:
        """Live volume change — no restart, no click."""
        self.buses[bus].set(gain, ms)

    def bus_gain(self, bus: str) -> float:
        return self.buses[bus].target

    def set_master_gain(self, gain: float, ms: int = DEFAULT_RAMP_MS) -> None:
        self.master.set(gain, ms)

    # ── metering ─────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def idle_seconds(self) -> float:
        return self.idle_frames * FRAME_MS / 1000.0

    @property
    def level(self) -> float:
        return self._peak

    def spectrum(self) -> np.ndarray:
        return self._spectrum

    # ── audio thread ─────────────────────────────────────────────────────

    def read(self) -> bytes:
        """Called every 20 ms by disnake.  Must never return b"" while active."""
        if not self._active:
            return b""

        master = self.master.advance()
        bus_gains = {name: ramp.advance() for name, ramp in self.buses.items()}

        accumulator = np.zeros(FRAME_SAMPLES, dtype=np.int32)
        finished: List[Voice] = []

        with self._lock:
            voices = list(self._voices)

        audible = [v for v in voices if not v.paused]
        self.idle_frames = self.idle_frames + 1 if not audible else 0

        for voice in voices:
            if voice.paused:
                if voice.stop_when_silent:
                    # Being discarded anyway: reap it now rather than waiting for
                    # a fade that can never advance while paused.  Otherwise a
                    # pause followed by a track change leaks the old voice, its
                    # FFmpeg process, and blocks the idle suspend forever.
                    finished.append(voice)
                    continue
                # Don't pull a frame: the stream's position is held exactly where
                # it is, so resuming continues rather than restarting.  The
                # decoder blocks on its full queue, which is harmless.
                continue

            frame = voice.stream.read_frame()
            if frame is None:
                finished.append(voice)
                continue

            envelope = voice.gain.advance()
            trim = voice.trim.advance()
            if voice.stop_when_silent and envelope <= 0.0:
                finished.append(voice)
                continue

            gain = envelope * trim * bus_gains.get(voice.bus, 1.0)
            if self.normalise:
                gain *= voice.norm_gain
            if gain <= 0.0:
                continue  # still consumed the frame, so timing stays correct
            samples = frame_to_array(frame)
            if gain == 1.0:
                accumulator += samples
            else:
                accumulator += (samples * gain).astype(np.int32)

        if master != 1.0:
            accumulator = (accumulator * master).astype(np.int32)

        self.frames_mixed += 1
        if accumulator.max(initial=0) > INT16_MAX or accumulator.min(initial=0) < INT16_MIN:
            self.clipped_frames += 1
        self._peak = peak(accumulator)
        if self.frames_mixed % 2 == 0:  # 25 Hz is plenty for a visualiser
            self._spectrum = spectrum(accumulator, SPECTRUM_BANDS)

        for voice in finished:
            self.remove_voice(voice)
            if voice.notify_on_finish and voice.on_finish:
                try:
                    voice.on_finish(voice)
                except Exception as exc:  # never let a callback kill the mixer
                    self._log(f"Voice finish callback failed: {exc}", "ERR")

        return array_to_frame(accumulator) if accumulator.any() else SILENCE

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        if not self._active:
            return  # disnake also calls this after stop(); don't log twice
        self._active = False
        with self._lock:
            voices = list(self._voices)
            self._voices.clear()
        for voice in voices:
            voice.stream.stop()
        self._log(f"Mixer stopped after {self.frames_mixed} frames")

    def _log(self, message: str, category: str = "MIX") -> None:
        if self.debug:
            self.debug.log(message, category)
