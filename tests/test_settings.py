# tests/test_settings.py
"""PlaybackSettings persistence — levels must survive a restart."""

import json

from dndmusic.config import paths
from dndmusic.engine.player import PlaybackSettings


def test_round_trip_through_disk(data_root):
    settings = PlaybackSettings()
    settings.target_lufs = -40.0
    settings.music_volume = 1.0
    settings.normalise = True
    settings.allow_boost = False
    settings.save()

    assert paths.settings_file.exists()
    reloaded = PlaybackSettings().load()
    assert reloaded.target_lufs == -40.0
    assert reloaded.music_volume == 1.0


def test_missing_file_leaves_defaults(data_root):
    defaults = PlaybackSettings()
    loaded = PlaybackSettings().load()
    assert loaded.to_dict() == defaults.to_dict()


def test_corrupt_file_is_ignored(data_root):
    paths.settings_file.write_text("{not json at all", encoding="utf-8")
    loaded = PlaybackSettings().load()
    assert loaded.target_lufs == PlaybackSettings().target_lufs


def test_unknown_keys_are_skipped(data_root):
    paths.settings_file.write_text(
        json.dumps({"target_lufs": -33.0, "nonsense_key": 5}), encoding="utf-8"
    )
    loaded = PlaybackSettings().load()
    assert loaded.target_lufs == -33.0
    assert not hasattr(loaded, "nonsense_key")


def test_wrong_types_do_not_crash(data_root):
    paths.settings_file.write_text(
        json.dumps({"target_lufs": "not a number", "fade_seconds": 3}), encoding="utf-8"
    )
    loaded = PlaybackSettings().load()
    assert loaded.target_lufs == PlaybackSettings().target_lufs
    assert loaded.fade_seconds == 3


def test_new_fields_persist(data_root):
    from dndmusic.core.models import OutputMode

    settings = PlaybackSettings()
    settings.loop_music = False
    settings.loop_ambient = False
    settings.output_mode = OutputMode.LOCAL.value
    settings.target_lufs = -38.0
    settings.save()

    reloaded = PlaybackSettings().load()
    assert reloaded.loop_music is False
    assert reloaded.loop_ambient is False
    assert reloaded.output is OutputMode.LOCAL
    assert reloaded.target_lufs == -38.0


def test_unknown_output_mode_falls_back_to_discord(data_root):
    from dndmusic.core.models import OutputMode

    settings = PlaybackSettings()
    settings.output_mode = "Telepathy"
    assert settings.output is OutputMode.DISCORD


def test_engine_runs_without_a_bot_loop(data_root):
    """Local playback has no bot to borrow an event loop from."""
    from dndmusic.core.debug import DebugLogger
    from dndmusic.core.playlist import PlaylistManager
    from dndmusic.engine.player import MusicEngine

    engine = MusicEngine(PlaylistManager(), DebugLogger())
    assert engine.loop is None            # no provider bound
    loop = engine._ensure_loop()          # so it makes its own
    try:
        assert loop is not None and not loop.is_closed()
        assert engine._ensure_loop() is loop   # reused, not recreated
    finally:
        engine.shutdown()


def test_local_output_does_not_require_a_voice_client(data_root):
    """Regression: the start coroutines guarded on is_connected.

    That is Discord-specific, so in local mode every start returned silently —
    no audio, no log line, nothing to debug.
    """
    from dndmusic.core.debug import DebugLogger
    from dndmusic.core.models import OutputMode
    from dndmusic.core.playlist import PlaylistManager
    from dndmusic.engine.player import MusicEngine

    class DummySink:
        def __init__(self):
            self.started_with = None

        def start(self, source):
            self.started_with = source

        def stop(self):
            self.started_with = None

    engine = MusicEngine(PlaylistManager(), DebugLogger())
    engine.settings.output_mode = OutputMode.LOCAL.value
    engine.local_sink = DummySink()

    try:
        assert engine.is_connected is False       # no bot, ever
        assert engine.can_output is True          # but a sink is present
        assert engine._output_available("music") is True

        source = engine._ensure_source()
        assert source is not None
        assert engine.local_sink.started_with is source
    finally:
        engine.shutdown()


def test_discord_mode_without_a_channel_reports_why(data_root):
    from dndmusic.core.debug import DebugLogger
    from dndmusic.core.playlist import PlaylistManager
    from dndmusic.engine.player import MusicEngine

    engine = MusicEngine(PlaylistManager(), DebugLogger())
    errors = []
    engine.on_error = errors.append
    try:
        assert engine._output_available("music") is False
        assert errors and "!join" in errors[0]
    finally:
        engine.shutdown()


def test_output_device_persists(data_root):
    settings = PlaybackSettings()
    settings.output_device = "Headset (Steam)"
    settings.save()
    assert PlaybackSettings().load().output_device == "Headset (Steam)"
