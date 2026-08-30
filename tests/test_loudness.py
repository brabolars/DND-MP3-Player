# tests/test_loudness.py
"""Loudness measurement and normalisation gain."""

import shutil
import subprocess

import pytest

from dndmusic.audio.loudness import (
    DEFAULT_ALLOW_BOOST,
    DEFAULT_CEILING_DBTP,
    MAX_BOOST_DB,
    MAX_CUT_DB,
    Loudness,
    db_to_linear,
    gain_db_for_target,
    linear_to_db,
    measure,
    normalisation_gain,
)

# ── gain maths (no ffmpeg needed) ────────────────────────────────────────────

def test_default_is_attenuate_only():
    """Turning normalisation on must never make anything louder than the file."""
    assert DEFAULT_ALLOW_BOOST is False
    quiet = Loudness(lufs=-30.0, true_peak=-20.0)
    assert gain_db_for_target(quiet, -16.0) == 0.0


def test_quiet_track_is_boosted_only_when_asked():
    quiet = Loudness(lufs=-20.0, true_peak=-12.0)
    assert gain_db_for_target(quiet, -16.0, allow_boost=True) == pytest.approx(4.0)
    assert gain_db_for_target(quiet, -16.0, allow_boost=False) == 0.0


def test_loud_track_is_cut():
    assert gain_db_for_target(Loudness(lufs=-9.0, true_peak=-6.0), -16.0) == pytest.approx(-7.0)


def test_already_at_target_is_left_alone():
    assert gain_db_for_target(Loudness(lufs=-16.0, true_peak=-3.0), -16.0) == pytest.approx(0.0)


def test_peak_ceiling_holds_the_boost_back():
    # Wants +10 dB, but the peak is already at -2 dBTP.
    gain = gain_db_for_target(
        Loudness(lufs=-26.0, true_peak=-2.0), -16.0, ceiling_dbtp=-1.0, allow_boost=True
    )
    assert gain == pytest.approx(1.0)


def test_ceiling_applies_even_without_boosting():
    """A hot-peaking file is pulled under the ceiling, buying headroom to layer."""
    hot = Loudness(lufs=-18.0, true_peak=-0.2)
    assert gain_db_for_target(hot, -18.0, ceiling_dbtp=-1.0) == pytest.approx(-0.8)


def test_boost_is_capped():
    assert (
        gain_db_for_target(Loudness(lufs=-60.0, true_peak=-50.0), -16.0, allow_boost=True)
        == MAX_BOOST_DB
    )


def test_cut_is_capped_but_generously():
    """The cut limit must not be reachable by real material, or matching breaks."""
    assert MAX_CUT_DB >= 40.0
    assert gain_db_for_target(Loudness(lufs=60.0, true_peak=0.0), -16.0) == -MAX_CUT_DB


@pytest.mark.parametrize("target", [-14.0, -23.0, -30.0, -40.0, -50.0])
def test_every_target_is_actually_reachable(target):
    """Regression: a 24 dB cut cap left loud tracks stranded above low targets."""
    for lufs in (-6.0, -10.0, -14.0, -20.0, -30.0):
        loudness = Loudness(lufs=lufs, true_peak=-1.5)
        landed = lufs + gain_db_for_target(loudness, target)
        if lufs > target:
            assert landed == pytest.approx(target, abs=0.1), (
                f"{lufs} LUFS did not reach {target}"
            )


def test_tracks_are_matched_to_each_other_at_a_low_target():
    tracks = [Loudness(lufs=v, true_peak=-1.0) for v in (-8.0, -14.0, -22.0, -30.0)]
    landed = [t.lufs + gain_db_for_target(t, -40.0) for t in tracks]
    assert max(landed) - min(landed) < 0.2


def test_unmeasured_track_is_untouched():
    assert gain_db_for_target(None) == 0.0
    assert normalisation_gain(None) == 1.0


def test_two_tracks_end_up_matched_when_boosting_is_allowed():
    quiet = Loudness(lufs=-20.0, true_peak=-8.0)
    loud = Loudness(lufs=-12.0, true_peak=-3.0)
    after_quiet = quiet.lufs + gain_db_for_target(quiet, -16.0, allow_boost=True)
    after_loud = loud.lufs + gain_db_for_target(loud, -16.0, allow_boost=True)
    assert after_quiet == pytest.approx(after_loud, abs=0.1)


def test_attenuate_only_narrows_the_spread_without_raising_anything():
    """The loud one comes down to target; the quiet one is left alone."""
    quiet = Loudness(lufs=-26.0, true_peak=-14.0)
    loud = Loudness(lufs=-10.0, true_peak=-6.0)
    after_quiet = quiet.lufs + gain_db_for_target(quiet, -18.0)
    after_loud = loud.lufs + gain_db_for_target(loud, -18.0)

    assert after_quiet == -26.0                      # untouched
    assert after_loud == pytest.approx(-18.0)        # tamed
    assert abs(after_loud - after_quiet) < abs(loud.lufs - quiet.lufs)


def test_db_conversions_round_trip():
    assert db_to_linear(0.0) == pytest.approx(1.0)
    assert db_to_linear(6.0) == pytest.approx(1.995, abs=0.01)
    assert linear_to_db(db_to_linear(-7.5)) == pytest.approx(-7.5)


def test_serialisation_round_trip():
    original = Loudness(lufs=-18.4, true_peak=-1.2, lra=6.5)
    assert Loudness.from_dict(original.to_dict()) == original
    assert Loudness.from_dict(None) is None
    assert Loudness.from_dict({"nonsense": 1}) is None


# ── real measurement ────────────────────────────────────────────────────────

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
class TestRealMeasurement:
    @staticmethod
    def tone(path, volume):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=2", "-ac", "2", "-ar", "48000",
             "-filter:a", f"volume={volume}", str(path), "-y"],
            check=True,
        )
        return str(path)

    def test_measures_a_real_file(self, tmp_path):
        result = measure(self.tone(tmp_path / "t.wav", 0.5))
        assert result is not None
        assert -60 < result.lufs < 0
        assert result.true_peak <= 0

    def test_louder_file_measures_louder(self, tmp_path):
        quiet = measure(self.tone(tmp_path / "q.wav", 0.1))
        loud = measure(self.tone(tmp_path / "l.wav", 0.8))
        assert loud.lufs > quiet.lufs

    def test_normalisation_matches_two_files(self, tmp_path):
        """Levels chosen to sit inside the gain caps, as real music does."""
        quiet = measure(self.tone(tmp_path / "q.wav", 0.6))
        loud = measure(self.tone(tmp_path / "l.wav", 0.9))

        target = -20.0
        after_quiet = quiet.lufs + gain_db_for_target(
            quiet, target, DEFAULT_CEILING_DBTP, allow_boost=True
        )
        after_loud = loud.lufs + gain_db_for_target(
            loud, target, DEFAULT_CEILING_DBTP, allow_boost=True
        )

        assert abs(loud.lufs - quiet.lufs) > 2.0          # they did differ
        assert after_quiet == pytest.approx(target, abs=0.5)
        assert after_loud == pytest.approx(target, abs=0.5)

    def test_extreme_boost_is_capped_not_wrong(self, tmp_path):
        """A near-silent file is not amplified without limit."""
        very_quiet = measure(self.tone(tmp_path / "vq.wav", 0.02))
        assert gain_db_for_target(very_quiet, -16.0, allow_boost=True) == MAX_BOOST_DB
        assert gain_db_for_target(very_quiet, -16.0) == 0.0

    def test_real_files_are_never_made_louder_by_default(self, tmp_path):
        for volume in (0.05, 0.2, 0.5, 0.95):
            loudness = measure(self.tone(tmp_path / f"v{volume}.wav", volume))
            assert gain_db_for_target(loudness, -18.0) <= 0.0

    def test_missing_file_returns_none(self, tmp_path):
        assert measure(str(tmp_path / "nope.mp3")) is None

    def test_silence_returns_none(self, tmp_path):
        path = tmp_path / "silent.wav"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "anullsrc=r=48000:cl=stereo", "-t", "1", str(path), "-y"],
            check=True,
        )
        assert measure(str(path)) is None
