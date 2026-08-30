# src/dndmusic/audio/pcm.py
"""PCM frame format and sample maths.

Discord expects 20 ms frames of 48 kHz, 16-bit, stereo, little-endian PCM.
Everything downstream of FFmpeg speaks exactly this format, which is what makes
mixing in Python possible: frames from different sources are interchangeable.
"""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 48_000
CHANNELS = 2
SAMPLE_WIDTH = 2  # bytes per sample (int16)
FRAME_MS = 20

SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000          # 960 per channel
FRAME_SAMPLES = SAMPLES_PER_FRAME * CHANNELS                # 1920 interleaved
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH                  # 3840

SILENCE = b"\x00" * FRAME_BYTES

INT16_MIN = -32_768
INT16_MAX = 32_767

#: FFmpeg arguments that produce this exact format.
FFMPEG_OUTPUT_ARGS = (
    "-f", "s16le",
    "-ar", str(SAMPLE_RATE),
    "-ac", str(CHANNELS),
    "-vn",
)


def frame_to_array(frame: bytes) -> np.ndarray:
    """View a frame as interleaved int16 samples (zero-copy)."""
    return np.frombuffer(frame, dtype="<i2")


def array_to_frame(samples: np.ndarray) -> bytes:
    """Clip to int16 range and serialise.  Accepts int32/float accumulators."""
    return np.clip(samples, INT16_MIN, INT16_MAX).astype("<i2").tobytes()


def pad_frame(chunk: bytes) -> bytes:
    """Zero-pad a short final chunk up to a full frame."""
    if len(chunk) >= FRAME_BYTES:
        return chunk[:FRAME_BYTES]
    return chunk + b"\x00" * (FRAME_BYTES - len(chunk))


def peak(samples: np.ndarray) -> float:
    """Peak amplitude as 0.0–1.0."""
    if samples.size == 0:
        return 0.0
    return float(np.abs(samples).max()) / INT16_MAX


def spectrum(samples: np.ndarray, bands: int = 32) -> np.ndarray:
    """Log-spaced magnitude spectrum of a frame, normalised to roughly 0–1.

    Used to drive the visualiser from real audio instead of a sine wave.
    """
    if samples.size < CHANNELS * 2:
        return np.zeros(bands)

    mono = samples.reshape(-1, CHANNELS).mean(axis=1).astype(np.float32)
    mono /= INT16_MAX
    window = np.hanning(mono.size).astype(np.float32)
    magnitude = np.abs(np.fft.rfft(mono * window))

    # Log-spaced edges: low frequencies get fewer bins, matching perception.
    edges = np.geomspace(1, magnitude.size - 1, bands + 1).astype(int)
    out = np.empty(bands, dtype=np.float32)
    for i in range(bands):
        lo, hi = edges[i], max(edges[i] + 1, edges[i + 1])
        out[i] = magnitude[lo:hi].mean()

    # Compress the dynamic range so quiet detail stays visible.
    out = np.sqrt(out / (mono.size / 8))
    return np.clip(out, 0.0, 1.0)
