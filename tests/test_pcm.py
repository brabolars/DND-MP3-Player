# tests/test_pcm.py
import numpy as np

from dndmusic.audio import pcm


def test_frame_geometry_matches_discord_expectations():
    assert pcm.SAMPLES_PER_FRAME == 960
    assert pcm.FRAME_BYTES == 3840
    assert len(pcm.SILENCE) == pcm.FRAME_BYTES


def test_round_trip_preserves_samples():
    samples = np.array([0, 1000, -1000, 32767, -32768], dtype=np.int32)
    restored = pcm.frame_to_array(pcm.array_to_frame(samples))
    assert list(restored) == list(samples)


def test_array_to_frame_clips_instead_of_wrapping():
    restored = pcm.frame_to_array(pcm.array_to_frame(np.array([50_000, -50_000], dtype=np.int32)))
    assert list(restored) == [pcm.INT16_MAX, pcm.INT16_MIN]


def test_pad_frame_fills_short_chunks():
    assert len(pcm.pad_frame(b"\x01\x02")) == pcm.FRAME_BYTES
    assert len(pcm.pad_frame(b"\x00" * (pcm.FRAME_BYTES + 10))) == pcm.FRAME_BYTES


def test_peak_is_normalised():
    assert pcm.peak(np.array([pcm.INT16_MAX], dtype=np.int32)) == 1.0
    assert pcm.peak(np.zeros(4, dtype=np.int32)) == 0.0


def test_spectrum_locates_a_tone():
    t = np.arange(pcm.SAMPLES_PER_FRAME) / pcm.SAMPLE_RATE
    tone = (np.sin(2 * np.pi * 4000 * t) * 20000).astype(np.int16)
    interleaved = np.repeat(tone, pcm.CHANNELS)

    bands = pcm.spectrum(interleaved, bands=32)
    assert bands.shape == (32,)
    assert bands.max() > 0
    # A 4 kHz tone belongs in the upper half of a log-spaced spectrum.
    assert bands.argmax() > 16
