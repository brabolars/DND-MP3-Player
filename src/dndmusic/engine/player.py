# src/dndmusic/engine/player.py
"""The music engine.

Owns one :class:`MixingSource` per voice session.  Every control the DM touches
— volume, ambient level, SFX, crossfade length, next track — is a mutation of
that live graph, so **nothing restarts the music**.

Still Qt-free: the UI subscribes through plain callables that the GUI bridge
turns into queued Qt signals.
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
import traceback
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np

from ..audio.mixer import (
    AMBIENT_BUS,
    MUSIC_BUS,
    SFX_BUS,
    GainRamp,
    MixingSource,
    Voice,
)
from ..audio.loudness import (
    DEFAULT_ALLOW_BOOST,
    DEFAULT_CEILING_DBTP,
    DEFAULT_TARGET_LUFS,
    Loudness,
    gain_db_for_target,
    normalisation_gain,
)
from ..audio.stream import FFmpegPcmStream, LoopingStream
from ..core.debug import DebugLogger
from ..core.library import MediaLibrary
from ..core.models import MediaKind, MusicTrack, OutputMode, PlaybackMode
from ..core.playlist import PlaylistManager

MAX_SFX_VOICES = 8
MAX_MUSIC_LAYERS = 6
INSTANT_MS = 0

#: Stop transmitting after this long with nothing playing.  A persistent mixer
#: would otherwise send 50 Opus packets a second of encoded silence forever,
#: which keeps the bot permanently "speaking" and is audible as a faint idle
#: hiss.  Playback resumes transparently the moment something is queued.
IDLE_SUSPEND_SECONDS = 3.0

#: What to assume about an unmeasured track so playback can start immediately.
#: Measuring means decoding the whole file — 25 seconds for a 10-minute track on
#: a fast machine, far worse on a slow one — and sampling the first minute is not
#: an option: on material that varies it can be 9 dB out, which is exactly the
#: inconsistency normalisation exists to remove.
#:
#: So we guess *loud* (a loudness-war master) and correct once the real figure
#: arrives.  Guessing loud means the provisional gain is a large cut: a quiet
#: track starts too quiet and comes up, which is far kinder than the reverse.
PROVISIONAL_LUFS = -9.0

#: How long the correction takes to glide in, once measured.
NORMALISATION_CORRECTION_MS = 800


@dataclass
class LayerInfo:
    """A snapshot of one playing voice, for the UI to render a strip from."""

    voice_id: int
    label: str
    bus: str
    trim: float
    normalisation_db: float
    looping: bool
    paused: bool
    is_primary: bool


def _noop(*_args, **_kwargs) -> None:
    return None


@dataclass
class PlaybackSettings:
    """Mixer levels and behaviour.  All applied live."""

    music_volume: float = 0.5
    ambient_volume: float = 0.3
    sfx_volume: float = 0.8
    master_volume: float = 1.0
    fade_enabled: bool = True
    fade_seconds: int = 2
    #: Loudness normalisation — balances tracks against each other.
    normalise: bool = True
    target_lufs: float = DEFAULT_TARGET_LUFS
    ceiling_dbtp: float = DEFAULT_CEILING_DBTP
    #: When False, normalisation only ever attenuates — it cannot make a track
    #: louder than the file itself.
    allow_boost: bool = DEFAULT_ALLOW_BOOST
    #: Repeat toggles, applied to new voices and to the playing one.
    loop_music: bool = True
    loop_ambient: bool = True
    #: Discord, or straight out of this machine's speakers.
    output_mode: str = OutputMode.DISCORD.value
    #: Local output device by name; empty follows the system default.
    output_device: str = ""
    #: Explicit path to ffmpeg.exe.  Empty means "use PATH", which finds the
    #: bundled copy.  This is the escape hatch when bundling fails or someone
    #: has FFmpeg installed somewhere unusual.
    ffmpeg_path: str = ""
    #: Explicit path to libopus-0.dll.  Empty means "use the search order",
    #: which normally finds the copy disnake ships.
    opus_path: str = ""
    #: Manual +/- dB nudge applied after everything else.  An escape hatch for
    #: "the target is right in principle but this room/rig needs a bit more".
    trim_db: float = 0.0

    @property
    def fade_ms(self) -> int:
        return int(self.fade_seconds * 1000) if self.fade_enabled else 0

    # ── persistence ──────────────────────────────────────────────────────
    #
    # Levels are the kind of thing you get right once and never want to set
    # again, so they survive restarts.

    @property
    def output(self) -> OutputMode:
        for mode in OutputMode:
            if mode.value == self.output_mode:
                return mode
        return OutputMode.DISCORD

    def to_dict(self) -> dict:
        return {
            "music_volume": self.music_volume,
            "ambient_volume": self.ambient_volume,
            "sfx_volume": self.sfx_volume,
            "master_volume": self.master_volume,
            "fade_enabled": self.fade_enabled,
            "fade_seconds": self.fade_seconds,
            "normalise": self.normalise,
            "target_lufs": self.target_lufs,
            "ceiling_dbtp": self.ceiling_dbtp,
            "allow_boost": self.allow_boost,
            "loop_music": self.loop_music,
            "loop_ambient": self.loop_ambient,
            "output_mode": self.output_mode,
            "output_device": self.output_device,
            "trim_db": self.trim_db,
            "ffmpeg_path": self.ffmpeg_path,
            "opus_path": self.opus_path,
        }

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "PlaybackSettings":
        settings = cls()
        if not data:
            return settings
        for key, value in data.items():
            if hasattr(settings, key) and not key.startswith("_"):
                try:
                    current = getattr(settings, key)
                    setattr(settings, key, type(current)(value))
                except (TypeError, ValueError):
                    continue
        return settings

    def load(self) -> "PlaybackSettings":
        """Merge saved values in place.  A corrupt file is ignored, not fatal."""
        from ..config import paths

        file = paths.settings_file
        if not file.exists():
            return self
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception:
            return self
        merged = PlaybackSettings.from_dict(data)
        for key, value in merged.to_dict().items():
            setattr(self, key, value)
        return self

    def save(self) -> None:
        from ..config import paths

        try:
            paths.settings_file.write_text(
                json.dumps(self.to_dict(), indent=2), encoding="utf-8"
            )
        except Exception:
            pass


class MusicEngine:
    def __init__(
        self,
        playlist: PlaylistManager,
        debug: DebugLogger,
        settings: Optional[PlaybackSettings] = None,
        library: Optional[MediaLibrary] = None,
    ) -> None:
        self.playlist = playlist
        self.debug = debug
        self.settings = settings or PlaybackSettings()
        #: Optional — needed only to measure and cache loudness.
        self.library = library

        self.voice_client = None
        #: Duck-typed local sink with start(source)/stop(), injected by the GUI so
        #: this module stays free of Qt.
        self.local_sink = None
        self.source: Optional[MixingSource] = None
        self._music_voice: Optional[Voice] = None
        self._ambient_voice: Optional[Voice] = None
        self._ambient_track: Optional[MusicTrack] = None
        self._current_track: Optional[MusicTrack] = None
        self._loop_provider: Callable[[], Optional[asyncio.AbstractEventLoop]] = lambda: None
        #: Fallback loop, for running without a bot at all (local playback).
        self._own_loop: Optional[asyncio.AbstractEventLoop] = None
        #: Tracks currently being measured, so replaying one does not start a
        #: second analysis of the same file.
        self._measuring: set = set()
        #: Scheduled work, cancelled on shutdown so nothing complains about
        #: pending tasks when the loop stops.
        self._pending: set = set()
        #: Number of voices being prepared right now.  The idle suspend refuses
        #: to fire while any start is in flight, so a slow first measurement
        #: cannot have the mixer pulled out from under it.
        self._pending_starts = 0

        # Observers, replaced by the GUI bridge.
        self.on_track_change: Callable[[Optional[MusicTrack]], None] = _noop
        self.on_playing_change: Callable[[bool], None] = _noop
        self.on_error: Callable[[str], None] = _noop
        #: Fired when the set of playing voices changes, so the UI can resync.
        self.on_layers_changed: Callable[[], None] = _noop

    # ═════════════════════════════════════════════════════════════════════
    #  Session lifecycle
    # ═════════════════════════════════════════════════════════════════════

    def bind_loop(self, provider) -> None:
        self._loop_provider = provider

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        try:
            return self._loop_provider()
        except Exception:
            return None

    def attach_voice_client(self, voice_client) -> None:
        """Bind a voice session.  Transmission starts when there is audio."""
        self.voice_client = voice_client
        self.source = None
        self.debug.log("Voice session ready (idle, not transmitting)", "MIX")

    def _ensure_source(self) -> Optional[MixingSource]:
        """Create and start the mixer if it isn't running.

        Called before anything is queued, so an idle output produces nothing at
        all, and a suspended one resumes without the caller noticing.
        """
        if self.source is not None:
            return self.source
        if not self.can_output:
            return None

        source = MixingSource(self.debug)
        self.source = source
        self._apply_all_levels()
        source.normalise = self.settings.normalise

        mode = self.output_mode
        try:
            if mode is OutputMode.LOCAL:
                setter = getattr(self.local_sink, "set_device", None)
                if setter is not None:
                    setter(self.settings.output_device)
                self.local_sink.start(source)
                self.debug.log("Mixer streaming to this PC", "MIX")
            else:
                self.voice_client.play(source, after=self._on_source_ended)
                self.debug.log("Mixer streaming to Discord", "MIX")
        except Exception as exc:
            self.source = None
            self.debug.log(f"Could not start output ({mode.value}): {exc}", "ERR")
            self.on_error(f"Could not start audio output: {exc}")
            return None
        return source

    def handle_output_failure(self, message: str) -> None:
        """Called when a sink fails asynchronously (it starts on the UI thread)."""
        self.debug.log(f"Output failed: {message}", "ERR")
        self._teardown_source()
        self.on_playing_change(False)
        self.on_error(message)

    def _output_available(self, what: str) -> bool:
        """Guard for the start coroutines.

        This used to test ``is_connected``, which is Discord-specific: in local
        output mode there is no voice client, so every start returned *silently*
        and the only symptom was no audio and no log line.  Bails are logged now.
        """
        if self.can_output:
            return True
        if self.output_mode is OutputMode.LOCAL:
            reason = "no local audio sink available"
        else:
            reason = "the bot is not in a voice channel — use !join"
        self.debug.log(f"Cannot start {what}: {reason}", "ERR")
        self.on_error(f"Cannot play: {reason}.")
        return False

    def _teardown_source(self) -> None:
        """Stop whichever sink is running and drop the mixer."""
        source, self.source = self.source, None
        if self.output_mode is OutputMode.LOCAL:
            if self.local_sink is not None:
                try:
                    self.local_sink.stop()
                except Exception:
                    pass
        elif self.voice_client is not None:
            try:
                self.voice_client.stop()
            except Exception:
                pass
        if source is not None:
            source.cleanup()
        self._music_voice = None
        self._ambient_voice = None
        self._current_track = None

    def suspend_if_idle(self, threshold: float = IDLE_SUSPEND_SECONDS) -> bool:
        """Stop transmitting after a spell of true silence.  Poll this.

        Nothing is playing when this fires, so there is no state to lose — the
        mixer is rebuilt on demand.
        """
        source = self.source
        if source is None or not self.can_output:
            return False
        if self._pending_starts > 0:
            return False
        if source.voice_count() > 0 or source.idle_seconds < threshold:
            return False
        self.debug.log(f"Idle {source.idle_seconds:.0f}s — stopping transmission", "MIX")
        try:
            self.voice_client.stop()
        except Exception:
            pass
        source.cleanup()
        self.source = None
        return True

    def detach_voice_client(self) -> None:
        self._teardown_source()
        self.voice_client = None
        self.on_playing_change(False)
        self.on_track_change(None)

    def _on_source_ended(self, error) -> None:
        if error:
            self.debug.log(f"Mixer source error: {error}", "ERR")
        self.debug.log("Mixer source ended", "MIX")

    # ═════════════════════════════════════════════════════════════════════
    #  State
    # ═════════════════════════════════════════════════════════════════════

    @property
    def is_connected(self) -> bool:
        return bool(self.voice_client and self.voice_client.is_connected())

    @property
    def output_mode(self) -> OutputMode:
        return self.settings.output

    @property
    def can_output(self) -> bool:
        """True when there is somewhere for audio to go."""
        if self.output_mode is OutputMode.LOCAL:
            return self.local_sink is not None
        return self.is_connected

    def set_output_device(self, name: str) -> None:
        """Pick the local output device.  Applies live if audio is playing."""
        self.settings.output_device = name or ""
        self.settings.save()
        setter = getattr(self.local_sink, "set_device", None)
        if setter is not None:
            setter(self.settings.output_device)   # logs the change itself
        elif self.debug:
            self.debug.log(f"Output device: {name or 'system default'}", "MIX")

    def set_output_mode(self, mode: OutputMode) -> None:
        """Switch between the Discord bot and local playback.

        Playback stops on the switch: a frame can only be consumed once, so the
        two sinks cannot share a mixer, and restarting is clearer than trying to
        hand a live stream over.
        """
        if mode is self.output_mode:
            return
        self._teardown_source()
        self.settings.output_mode = mode.value
        self.settings.save()
        self.debug.log(f"Output: {mode.value}", "MIX")
        self.on_layers_changed()

    @property
    def is_ready(self) -> bool:
        """Able to play — the mixer starts on demand."""
        return self.can_output

    @property
    def is_playing(self) -> bool:
        return self._music_voice is not None

    @property
    def current_track(self) -> Optional[MusicTrack]:
        return self._current_track

    @property
    def ambient_track(self) -> Optional[MusicTrack]:
        return self._ambient_track

    def spectrum(self) -> Optional[np.ndarray]:
        return self.source.spectrum() if self.source else None

    def level(self) -> float:
        return self.source.level if self.source else 0.0

    def diagnostics(self) -> dict:
        if not self.source:
            return {"attached": False}
        return {
            "attached": True,
            "frames": self.source.frames_mixed,
            "music": self.source.voice_count(MUSIC_BUS),
            "ambient": self.source.voice_count(AMBIENT_BUS),
            "sfx": self.source.voice_count(SFX_BUS),
            "level": round(self.source.level, 3),
            "normalise": self.settings.normalise,
            "target_lufs": self.settings.target_lufs,
            "allow_boost": self.settings.allow_boost,
            "clipped": self.source.clipped_frames,
            "paused": self.is_paused,
            "idle": round(self.source.idle_seconds, 1),
            "pending": self._pending_starts,
        }

    def gain_chain_report(self, track: MusicTrack, norm_gain: float) -> str:
        """Spell out every multiplier, so "why is it quiet/loud" is answerable.

        Everything multiplies, so a fader at 50% moves the result 6 dB away from
        whatever the normalisation target claims to deliver.
        """
        from ..audio.loudness import linear_to_db

        norm_db = linear_to_db(norm_gain) if norm_gain > 0 else -120.0
        music_db = linear_to_db(self.settings.music_volume) if self.settings.music_volume else -120.0
        master_db = linear_to_db(self.master_gain) if self.master_gain else -120.0
        total = norm_db + music_db + master_db

        loudness = self.library.loudness_of(track) if self.library else None
        if loudness is not None:
            effective = f"  =>  about {loudness.lufs + total:.1f} LUFS out"
            source = f"file {loudness.lufs:.1f} LUFS"
        else:
            effective = ""
            source = "file unmeasured"

        return (
            f"{source}  norm {norm_db:+.1f}  music {music_db:+.1f}  "
            f"master {master_db:+.1f}  = {total:+.1f} dB{effective}"
        )

    def effective_lufs(self) -> Optional[float]:
        """Estimated output loudness of the current track, for the UI readout."""
        track = self._current_track
        if track is None or self.library is None:
            return None
        loudness = self.library.loudness_of(track)
        if loudness is None:
            return None
        voice = self._music_voice
        norm = voice.norm_gain.target if (voice and self.settings.normalise) else 1.0
        combined = norm * self.settings.music_volume * self.master_gain
        if combined <= 0:
            return None
        return loudness.lufs + 20 * math.log10(combined)

    def effective_music_db(self) -> float:
        """The music bus and master multiplied, in dB — what the sliders add up to."""
        from ..audio.loudness import linear_to_db

        combined = self.settings.music_volume * self.master_gain
        return linear_to_db(combined) if combined > 0 else -120.0

    # ═════════════════════════════════════════════════════════════════════
    #  Levels — applied live, never restart anything
    # ═════════════════════════════════════════════════════════════════════

    def _apply_all_levels(self) -> None:
        if not self.source:
            return
        self.source.set_bus_gain(MUSIC_BUS, self.settings.music_volume, INSTANT_MS)
        self.source.set_bus_gain(AMBIENT_BUS, self.settings.ambient_volume, INSTANT_MS)
        self.source.set_bus_gain(SFX_BUS, self.settings.sfx_volume, INSTANT_MS)
        self.source.set_master_gain(self.master_gain, INSTANT_MS)
        self.source.normalise = self.settings.normalise

    def set_music_volume(self, value: float) -> None:
        self.settings.music_volume = value
        if self.source:
            self.source.set_bus_gain(MUSIC_BUS, value)

    def set_ambient_volume(self, value: float) -> None:
        self.settings.ambient_volume = value
        if self.source:
            self.source.set_bus_gain(AMBIENT_BUS, value)

    def set_sfx_volume(self, value: float) -> None:
        self.settings.sfx_volume = value
        if self.source:
            self.source.set_bus_gain(SFX_BUS, value)

    def set_master_volume(self, value: float) -> None:
        self.settings.master_volume = value
        self._push_master()

    def set_trim_db(self, trim: float) -> None:
        """Manual offset in dB, on top of normalisation and the faders."""
        self.settings.trim_db = trim
        self._push_master()
        self.debug.log(f"Output trim: {trim:+.1f} dB", "MIX")

    @property
    def master_gain(self) -> float:
        """Master fader and the manual trim, combined."""
        from ..audio.loudness import db_to_linear

        return self.settings.master_volume * db_to_linear(self.settings.trim_db)

    def _push_master(self) -> None:
        if self.source:
            self.source.set_master_gain(self.master_gain)

    # ═════════════════════════════════════════════════════════════════════
    #  Loudness normalisation
    # ═════════════════════════════════════════════════════════════════════

    def save_settings(self) -> None:
        """Persist levels so the right values survive a restart."""
        self.settings.save()

    def set_normalisation(self, enabled: bool) -> None:
        """Toggle loudness matching.  Instant — no restart, no re-decode."""
        self.settings.normalise = enabled
        if self.source:
            self.source.normalise = enabled
        self.debug.log(f"Normalisation {'on' if enabled else 'off'}", "MIX")
        self.on_layers_changed()

    def set_target_lufs(self, target: float) -> None:
        """Change the target and re-derive every playing voice's gain."""
        self.settings.target_lufs = target
        if not self.source:
            return
        for voice in self.source.voices():
            loudness = self._loudness_for_label(voice.label)
            if loudness is not None:
                voice.norm_gain.set(
                    normalisation_gain(
                        loudness,
                        target,
                        self.settings.ceiling_dbtp,
                        self.settings.allow_boost,
                    )
                )
        self.debug.log(f"Normalisation target: {target:.1f} LUFS", "MIX")
        self.on_layers_changed()

    def set_allow_boost(self, enabled: bool) -> None:
        """Let normalisation raise quiet tracks, not just tame loud ones."""
        self.settings.allow_boost = enabled
        self.set_target_lufs(self.settings.target_lufs)   # re-derive live gains
        self.debug.log(f"Normalisation boost {'allowed' if enabled else 'disabled'}", "MIX")

    def set_ceiling_dbtp(self, ceiling: float) -> None:
        """Change the true-peak ceiling and re-derive every playing gain."""
        self.settings.ceiling_dbtp = ceiling
        self.set_target_lufs(self.settings.target_lufs)

    def _loudness_for_label(self, label: str) -> Optional[Loudness]:
        if self.library is None:
            return None
        for kind in list(MediaKind):
            track = self.library.find_by_display_name(kind, label)
            if track is not None and track.loudness:
                return Loudness.from_dict(track.loudness)
        return None

    async def _normalisation_for(self, track: MusicTrack) -> float:
        """The gain to start this track at.

        Measured tracks give the exact figure instantly.  An unmeasured one gets
        a deliberately conservative guess so playback can begin now, with the
        real measurement running in the background.
        """
        if not self.settings.normalise or self.library is None:
            return 1.0

        loudness = self.library.loudness_of(track)
        if loudness is not None:
            gain = normalisation_gain(
                loudness,
                self.settings.target_lufs,
                self.settings.ceiling_dbtp,
                self.settings.allow_boost,
            )
            applied = gain_db_for_target(
                loudness,
                self.settings.target_lufs,
                self.settings.ceiling_dbtp,
                self.settings.allow_boost,
            )
            wanted = self.settings.target_lufs - loudness.lufs
            note = " (capped)" if abs(wanted - applied) > 0.05 else ""
            self.debug.log(
                f"{track.display_name}: {loudness.lufs:.1f} LUFS, "
                f"peak {loudness.true_peak:.1f} dBTP -> {applied:+.1f} dB{note}",
                "NORM",
            )
            return gain

        provisional = normalisation_gain(
            Loudness(lufs=PROVISIONAL_LUFS, true_peak=-1.0),
            self.settings.target_lufs,
            self.settings.ceiling_dbtp,
            self.settings.allow_boost,
        )
        self.debug.log(
            f"{track.display_name}: not measured yet — starting at "
            f"{PROVISIONAL_LUFS:.0f} LUFS assumed, measuring in the background",
            "NORM",
        )
        return provisional

    async def _measure_in_background(self, track: MusicTrack, voice: Voice) -> None:
        """Measure a track while it plays, then glide to the right gain."""
        if self.library is None or track.path in self._measuring:
            return
        self._measuring.add(track.path)
        try:
            loudness = await asyncio.to_thread(self.library.measure_track, track)
        finally:
            self._measuring.discard(track.path)
        if loudness is None:
            return
        try:
            self.library.save()
        except Exception as exc:
            self.debug.log(f"Could not cache loudness: {exc}", "ERR")

        gain = normalisation_gain(
            loudness,
            self.settings.target_lufs,
            self.settings.ceiling_dbtp,
            self.settings.allow_boost,
        )
        applied = gain_db_for_target(
            loudness,
            self.settings.target_lufs,
            self.settings.ceiling_dbtp,
            self.settings.allow_boost,
        )
        self.debug.log(
            f"{track.display_name}: measured {loudness.lufs:.1f} LUFS "
            f"-> correcting to {applied:+.1f} dB",
            "NORM",
        )
        # Measuring takes seconds, during which the voice that triggered it may
        # have been replaced — by a crossfade, or by the DM hitting play again.
        # Correct every voice currently playing this track, not just that one.
        corrected = 0
        if self.source is not None:
            for playing in self.source.voices():
                if playing is voice or playing.label == track.display_name:
                    playing.norm_gain.set(gain, NORMALISATION_CORRECTION_MS)
                    corrected += 1
        if corrected:
            self.debug.log(f"Applied to {corrected} playing voice(s)", "NORM")
        self.on_layers_changed()

    # ═════════════════════════════════════════════════════════════════════
    #  Layers — several tracks at once, each with its own fader
    # ═════════════════════════════════════════════════════════════════════

    def layers(self) -> List[LayerInfo]:
        """Everything currently playing, for the UI's fader strips."""
        if not self.source:
            return []
        primary = self._music_voice
        infos = []
        for voice in self.source.voices():
            if voice.stop_when_silent:
                continue  # already fading out; the UI shouldn't offer a fader
            infos.append(
                LayerInfo(
                    voice_id=voice.id,
                    label=voice.label or "(unnamed)",
                    bus=voice.bus,
                    trim=voice.trim.target,
                    normalisation_db=round(20 * math.log10(voice.norm_gain.target), 1)
                    if voice.norm_gain.target > 0
                    else 0.0,
                    looping=voice.loop,
                    paused=voice.paused,
                    is_primary=voice is primary,
                )
            )
        return infos

    def add_layer(self, track: Optional[MusicTrack]) -> bool:
        """Start a track *alongside* whatever is already playing."""
        if track is None:
            return False
        if not self.is_ready:
            self.on_error("Not connected to a voice channel — use !join in Discord first.")
            return False
        if self.source is not None and self.source.voice_count(MUSIC_BUS) >= MAX_MUSIC_LAYERS:
            self.on_error(f"Layer limit reached ({MAX_MUSIC_LAYERS}). Stop one first.")
            return False
        return self._schedule(self._start_music(track, replace=False))

    def set_layer_trim(self, voice_id: int, value: float) -> bool:
        """Move one track's fader.  Independent of fades and of every other track."""
        if not self.source:
            return False
        return self.source.set_voice_trim(voice_id, value)

    def set_loop_music(self, enabled: bool) -> bool:
        """Repeat toggle for music: applies now and to the next track."""
        self.settings.loop_music = enabled
        self.settings.save()
        changed = 0
        if self.source:
            for voice in self.source.voices(MUSIC_BUS):
                if voice.stop_when_silent or not hasattr(voice.stream, "loop"):
                    continue
                voice.stream.loop = enabled
                voice.loop = enabled
                changed += 1
        self.debug.log(f"Loop music {'on' if enabled else 'off'} ({changed} playing)", "PLAY")
        self.on_layers_changed()
        return True

    def set_loop_ambient(self, enabled: bool) -> bool:
        self.settings.loop_ambient = enabled
        self.settings.save()
        if self.source:
            for voice in self.source.voices(AMBIENT_BUS):
                if hasattr(voice.stream, "loop"):
                    voice.stream.loop = enabled
                    voice.loop = enabled
        self.debug.log(f"Loop ambient {'on' if enabled else 'off'}", "MIX")
        self.on_layers_changed()
        return True

    def set_layer_loop(self, voice_id: int, enabled: bool) -> bool:
        """Turn looping on or off for one voice, mid-playback.

        Takes effect at the end of the current pass — the audio you are hearing
        is not interrupted.
        """
        if not self.source:
            return False
        voice = self.source.find_voice(voice_id)
        if voice is None:
            return False
        stream = voice.stream
        if not hasattr(stream, "loop"):
            return False
        stream.loop = enabled
        voice.loop = enabled
        self.debug.log(f"Loop {'on' if enabled else 'off'}: {voice.label}", "PLAY")
        self.on_layers_changed()
        return True

    def stop_layer(self, voice_id: int) -> bool:
        if not self.source:
            return False
        voice = self.source.find_voice(voice_id)
        if voice is None:
            return False
        if voice is self._music_voice:
            self._music_voice = None
            self._current_track = None
            self.on_track_change(None)
        voice.fade_out_and_stop(self.settings.fade_ms or 250)
        self.debug.log(f"Layer stopped: {voice.label}", "PLAY")
        self.on_layers_changed()
        return True

    # ═════════════════════════════════════════════════════════════════════
    #  Music
    # ═════════════════════════════════════════════════════════════════════

    def play(self, track: Optional[MusicTrack]) -> bool:
        if track is None:
            return False
        if self.playlist.mode is PlaybackMode.MULTITRACK:
            # In multi-track mode "play" means "add", so the DM can stack a
            # battle theme over an existing bed without stopping it.
            return self.add_layer(track)
        if not self.is_ready:
            self.debug.log("Play refused — mixer not attached", "PLAY")
            self.on_error("Not connected to a voice channel — use !join in Discord first.")
            return False
        return self._schedule(self._start_music(track))

    def play_current(self) -> bool:
        return self.play(self.playlist.current)

    def play_index(self, index: int) -> bool:
        if not (0 <= index < len(self.playlist)):
            return False
        self.playlist.index = index
        return self.play_current()

    def next(self) -> bool:
        if self.playlist.mode is PlaybackMode.SINGLE:
            return self.play(self.playlist.current)
        return self.play(self.playlist.advance())

    def previous(self) -> bool:
        return self.play(self.playlist.go_back())

    @property
    def is_paused(self) -> bool:
        return bool(self.source and self.source.bus_is_paused(MUSIC_BUS))

    def pause(self) -> bool:
        """Hold the music where it is.  Ambient and SFX keep running."""
        if not self.source:
            return False
        held = self.source.pause_bus(MUSIC_BUS, True)
        if not held:
            return False
        self.on_playing_change(False)
        self.on_layers_changed()
        self.debug.log(f"Paused {held} music voice(s)", "PLAY")
        return True

    def resume(self) -> bool:
        """Continue from the held position — this is not a restart."""
        if not self.source:
            return False
        resumed = self.source.pause_bus(MUSIC_BUS, False)
        if not resumed:
            return False
        self.on_playing_change(True)
        self.on_layers_changed()
        self.debug.log(f"Resumed {resumed} music voice(s)", "PLAY")
        return True

    def toggle_pause(self) -> bool:
        return self.resume() if self.is_paused else self.pause()

    def set_layer_paused(self, voice_id: int, paused: bool) -> bool:
        if not self.source:
            return False
        if not self.source.set_voice_paused(voice_id, paused):
            return False
        self.on_layers_changed()
        return True

    def stop(self, layers_too: bool = True) -> None:
        """Fade the music out.  The mixer keeps running; ambient keeps playing."""
        if self.source:
            if layers_too:
                self.source.stop_bus(MUSIC_BUS, self.settings.fade_ms)
            elif self._music_voice is not None:
                self._music_voice.fade_out_and_stop(self.settings.fade_ms)
        self._music_voice = None
        self._current_track = None
        self.on_playing_change(False)
        self.on_track_change(None)
        self.on_layers_changed()
        self.debug.log("Music stopped", "PLAY")

    async def _start_music(self, track: MusicTrack, replace: bool = True) -> None:
        """Start a music voice.

        ``replace=True`` crossfades over whatever was playing (normal playback);
        ``replace=False`` layers it alongside (the multi-track case).
        """
        if not self._output_available("music"):
            return
        stream = None
        self._track_start(+1)
        try:
            loop_track = self.settings.loop_music
            fade_ms = self.settings.fade_ms

            # Measure and prebuffer BEFORE touching the mixer.  Both of these
            # await for seconds on a first play, and claiming the mixer first
            # would leave it empty long enough for the idle suspend to tear it
            # down underneath us.
            norm_gain = await self._normalisation_for(track)
            # LoopingStream (rather than FFmpeg's -stream_loop) keeps the loop
            # flag mutable, so it can be toggled without restarting the track.
            stream = LoopingStream(lambda: FFmpegPcmStream(track.path), loop=loop_track)
            # Prebuffer off the audio thread so the crossfade starts clean.
            await asyncio.to_thread(stream.wait_until_ready, 1.5)

            source = self._ensure_source()
            if source is None:
                stream.stop()
                return

            previous = self._music_voice if replace else None
            voice = Voice(
                stream=stream,
                bus=MUSIC_BUS,
                gain=GainRamp(0.0 if fade_ms else 1.0),
                norm_gain=GainRamp(norm_gain),
                label=track.display_name,
                loop=loop_track,
                on_finish=self._music_voice_finished,
            )
            if fade_ms:
                voice.fade_to(1.0, fade_ms)

            # Rapid repeated presses could otherwise pile up copies of the same
            # track, each audible for the length of its fade — several times the
            # intended level.  Drop the oldest outgoing voice if that happens.
            outgoing = [v for v in source.voices(MUSIC_BUS) if v.stop_when_silent]
            while len(outgoing) >= 2:
                source.remove_voice(outgoing.pop(0))

            source.add_voice(voice)
            if replace:
                self._music_voice = voice
                self._current_track = track
                if previous is not None:
                    previous.fade_out_and_stop(fade_ms)
                self.on_track_change(track)

            self.on_playing_change(True)
            self.on_layers_changed()
            self.debug.log(
                f"{'Music' if replace else 'Layer'}: {track.display_name} "
                f"(loop={loop_track}, fade={fade_ms}ms)",
                "PLAY",
            )
            if self.settings.normalise and self.library is not None:
                if self.library.loudness_of(track) is None:
                    self._schedule(self._measure_in_background(track, voice))
            self.debug.log(self.gain_chain_report(track, norm_gain), "GAIN")
        except Exception as exc:
            if stream is not None:
                stream.stop()
            self.debug.log(f"Play error: {exc}", "ERR")
            self.debug.log(traceback.format_exc(), "ERR")
            self.on_error(str(exc))
        finally:
            self._track_start(-1)

    def _music_voice_finished(self, voice: Voice) -> None:
        """Called from the audio thread when a track reaches its end."""
        if voice is not self._music_voice:
            return  # an outgoing crossfade voice; ignore
        self._music_voice = None
        if self.playlist.mode not in (PlaybackMode.PLAYLIST, PlaybackMode.SHUFFLE):
            self.on_playing_change(False)
            self.on_track_change(None)
            return
        self._schedule(self._auto_next())

    async def _auto_next(self) -> None:
        track = self.playlist.advance()
        if track is None:
            self.on_playing_change(False)
            self.on_track_change(None)
            return
        await self._start_music(track)

    # ═════════════════════════════════════════════════════════════════════
    #  Ambient bed
    # ═════════════════════════════════════════════════════════════════════

    def set_ambient(self, track: Optional[MusicTrack]) -> bool:
        """Swap the looping ambient bed without touching the music."""
        self._ambient_track = track
        if not self.is_ready:
            return False
        return self._schedule(self._start_ambient(track))

    def clear_ambient(self) -> None:
        self._ambient_track = None
        if self.source:
            self.source.stop_bus(AMBIENT_BUS, self.settings.fade_ms or 250)
        self._ambient_voice = None
        self.on_layers_changed()
        self.debug.log("Ambient cleared", "MIX")

    async def _start_ambient(self, track: Optional[MusicTrack]) -> None:
        if track is None:
            if self.source is not None:
                self.source.stop_bus(AMBIENT_BUS, 250)
            self._ambient_voice = None
            return
        if not self._output_available("ambient"):
            return
        stream = None
        self._track_start(+1)
        try:
            fade_ms = self.settings.fade_ms or 500
            norm_gain = await self._normalisation_for(track)
            stream = LoopingStream(
                lambda: FFmpegPcmStream(track.path), loop=self.settings.loop_ambient
            )
            await asyncio.to_thread(stream.wait_until_ready, 1.5)

            source = self._ensure_source()
            if source is None:
                stream.stop()
                return

            previous = self._ambient_voice
            voice = Voice(
                stream=stream,
                bus=AMBIENT_BUS,
                gain=GainRamp(0.0),
                norm_gain=GainRamp(norm_gain),
                label=track.display_name,
                loop=self.settings.loop_ambient,
            )
            voice.fade_to(1.0, fade_ms)
            source.add_voice(voice)
            self._ambient_voice = voice
            if previous is not None:
                previous.fade_out_and_stop(fade_ms)
            self.debug.log(f"Ambient: {track.display_name}", "MIX")
        except Exception as exc:
            if stream is not None:
                stream.stop()
            self.debug.log(f"Ambient error: {exc}", "ERR")
            self.on_error(str(exc))
        finally:
            self._track_start(-1)

    # ═════════════════════════════════════════════════════════════════════
    #  SFX — layered on top, never interrupts anything
    # ═════════════════════════════════════════════════════════════════════

    def play_sfx(self, track: MusicTrack) -> bool:
        if not self.is_ready:
            self.on_error("Not connected to a voice channel.")
            return False
        return self._schedule(self._start_sfx(track))

    async def _start_sfx(self, track: MusicTrack) -> None:
        if not self._output_available("SFX"):
            return
        stream = None
        self._track_start(+1)
        try:
            norm_gain = await self._normalisation_for(track)
            stream = FFmpegPcmStream(track.path)
            await asyncio.to_thread(stream.wait_until_ready, 1.0, 5)

            source = self._ensure_source()
            if source is None:
                stream.stop()
                return

            active = source.voices(SFX_BUS)
            if len(active) >= MAX_SFX_VOICES:
                source.remove_voice(active[0])  # drop the oldest

            source.add_voice(
                Voice(
                    stream=stream,
                    bus=SFX_BUS,
                    gain=GainRamp(1.0),
                    norm_gain=GainRamp(norm_gain),
                    label=track.display_name,
                )
            )
            self.debug.log(f"SFX: {track.display_name}", "PLAY")
        except Exception as exc:
            if stream is not None:
                stream.stop()
            self.debug.log(f"SFX error: {exc}", "ERR")
            self.on_error(str(exc))
        finally:
            self._track_start(-1)

    # ═════════════════════════════════════════════════════════════════════
    #  Scheduling
    # ═════════════════════════════════════════════════════════════════════

    def _track_start(self, delta: int) -> None:
        self._pending_starts = max(0, self._pending_starts + delta)

    def _ensure_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """The bot's loop if there is one, otherwise our own.

        Playback is coroutine-driven, and local output has no bot to borrow a
        loop from — so the engine runs one itself when needed.  That is what lets
        the app work as a plain music player with no Discord connection.
        """
        loop = self.loop
        if loop is not None and not loop.is_closed():
            return loop

        if self._own_loop is not None and not self._own_loop.is_closed():
            return self._own_loop

        own = asyncio.new_event_loop()

        def run() -> None:
            asyncio.set_event_loop(own)
            own.run_forever()

        self._own_loop = own
        threading.Thread(target=run, name="engine-loop", daemon=True).start()
        self.debug.log("Started the engine's own event loop (no bot)", "MIX")
        return own

    def _schedule(self, coro) -> bool:
        loop = self._ensure_loop()
        if loop is None or loop.is_closed():
            coro.close()
            self.debug.log("No event loop available — command dropped", "ERR")
            self.on_error("Could not start playback: no event loop.")
            return False
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        self._pending.add(future)
        future.add_done_callback(self._pending.discard)
        return True

    def shutdown(self) -> None:
        """Tear everything down, including our own loop if we started one."""
        for future in list(self._pending):
            future.cancel()
        self._pending.clear()
        self._teardown_source()
        own, self._own_loop = self._own_loop, None
        if own is not None and not own.is_closed():
            own.call_soon_threadsafe(own.stop)
