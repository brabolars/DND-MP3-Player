# src/dndmusic/audio/loudness.py
"""Loudness measurement and normalisation gain.

Two things worth separating, because they are often conflated:

* **Loudness** is perceptual, measured in LUFS (EBU R128 / ITU BS.1770). It is
  what makes one track feel louder than another.
* **True peak** is the highest instantaneous sample level in dBFS/dBTP. It is
  what makes audio clip.

Normalising to a *peak* target (e.g. "-6 dB") does not balance anything: a dense
track peaking at -6 dBFS is far louder than a sparse one peaking at -6 dBFS.
So we measure integrated loudness per file, cache it, and apply a static gain to
bring each track to the same target — the same idea as ReplayGain. True peak is
measured too, and used to hold the gain back if raising a track would clip it.

Reference targets:

    -23 LUFS   EBU R128 broadcast
    -16 LUFS   podcast / mono-ish speech, and a good default for voice chat
    -14 LUFS   Spotify, YouTube, Amazon
     -9 LUFS   loudness-war mastering

Measurement runs FFmpeg once per file and is cached on the track, so it never
happens twice for the same file.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

#: Music playing under a conversation is not the "anchor element" — the speech
#: is.  Discord applies AGC to microphone input, so voices arrive auto-levelled
#: at roughly -18 LUFS, while a bot bypasses AGC entirely and arrives at exactly
#: what we send.  So we have to be our own AGC, and -24 puts music a few dB under
#: speech.  That also happens to be where the standards sit: ATSC A/85 is -24
#: LKFS, EBU R128 -23, and console games -24 via the GANG recommendations.
DEFAULT_TARGET_LUFS = -24.0

#: Attenuate-only by default.  Boosting is what makes normalisation surprising:
#: a quiet file suddenly arrives 4x louder than the one before it.  With this
#: off, normalisation can only ever pull a loud track *down*, so enabling it can
#: never make anything louder than the raw file.
DEFAULT_ALLOW_BOOST = False

#: Never let normalisation push a true peak above this.
DEFAULT_CEILING_DBTP = -1.0

#: Cap on how far a single track may be moved, so a near-silent file doesn't
#: get amplified into a hiss storm.
MAX_BOOST_DB = 6.0      # only reachable when boosting is explicitly enabled

#: Attenuation is harmless, so this is deliberately generous.  A tight cut cap
#: silently breaks matching at low targets: if a loud master needs -32 dB and the
#: cap is -24, it lands 8 dB above everything else and normalisation stops doing
#: its job.  Only *boosting* needs a tight limit, because that raises the noise
#: floor with the signal.
MAX_CUT_DB = 60.0

_JSON_BLOCK = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.DOTALL)


@dataclass(frozen=True)
class Loudness:
    """Measured programme loudness for one file."""

    lufs: float           # integrated loudness
    true_peak: float      # dBTP
    lra: float = 0.0      # loudness range

    def to_dict(self) -> dict:
        return {"lufs": self.lufs, "true_peak": self.true_peak, "lra": self.lra}

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["Loudness"]:
        if not data:
            return None
        try:
            return cls(
                lufs=float(data["lufs"]),
                true_peak=float(data["true_peak"]),
                lra=float(data.get("lra", 0.0)),
            )
        except (KeyError, TypeError, ValueError):
            return None


def measure(path: str, executable: Optional[str] = None, timeout: int = 120) -> Optional[Loudness]:
    """Analyse a file with FFmpeg's loudnorm filter.  None if it fails.

    Decoding runs far faster than realtime, but this still blocks — call it off
    the UI and audio threads.
    """
    from .ffmpeg import executable as default_executable

    command = [
        executable or default_executable(), "-hide_banner", "-nostats",
        "-i", path,
        "-af", "loudnorm=print_format=json",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None

    match = _JSON_BLOCK.search(result.stderr or "")
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
        lufs = float(payload["input_i"])
        peak = float(payload["input_tp"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None

    if not math.isfinite(lufs) or lufs < -70:
        return None  # silence, or too quiet to measure meaningfully

    lra_raw = payload.get("input_lra", "0")
    try:
        lra = float(lra_raw)
    except (TypeError, ValueError):
        lra = 0.0

    return Loudness(lufs=lufs, true_peak=peak, lra=lra)


def gain_db_for_target(
    loudness: Optional[Loudness],
    target_lufs: float = DEFAULT_TARGET_LUFS,
    ceiling_dbtp: float = DEFAULT_CEILING_DBTP,
    allow_boost: bool = DEFAULT_ALLOW_BOOST,
) -> float:
    """Gain in dB to bring a track towards the target without clipping.

    With ``allow_boost=False`` (the default) the result is never positive, so
    turning normalisation on cannot make anything louder — it only tames the
    tracks that are hotter than the target.  The true-peak ceiling is applied
    either way, which also buys headroom for layering several tracks at once.
    """
    if loudness is None:
        return 0.0

    gain = target_lufs - loudness.lufs
    if not allow_boost:
        gain = min(0.0, gain)
    gain = max(-MAX_CUT_DB, min(MAX_BOOST_DB, gain))

    # Hold back if this would push the true peak over the ceiling.
    headroom = ceiling_dbtp - loudness.true_peak
    if gain > headroom:
        gain = headroom

    return gain


def db_to_linear(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def linear_to_db(linear: float) -> float:
    if linear <= 0:
        return -math.inf
    return 20.0 * math.log10(linear)


def normalisation_gain(
    loudness: Optional[Loudness],
    target_lufs: float = DEFAULT_TARGET_LUFS,
    ceiling_dbtp: float = DEFAULT_CEILING_DBTP,
    allow_boost: bool = DEFAULT_ALLOW_BOOST,
) -> float:
    """Linear multiplier for the mixer.  1.0 when unmeasured."""
    return db_to_linear(gain_db_for_target(loudness, target_lufs, ceiling_dbtp, allow_boost))
