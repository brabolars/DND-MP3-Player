# tests/test_gui_widgets.py
"""Widget behaviour that is worth pinning: the library search filter.

Skipped when PyQt6 isn't installed, so CI stays lightweight.
"""

import os

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from dndmusic.core.categories import CategoryRegistry  # noqa: E402
from dndmusic.core.models import MusicTrack  # noqa: E402
from dndmusic.gui.widgets.music_library_view import MusicLibraryView  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def view(qapp, data_root):
    widget = MusicLibraryView()
    tracks = [
        MusicTrack("a.mp3", "/tmp/a.mp3", "Goblin Ambush", "Battle", 1024),
        MusicTrack("b.mp3", "/tmp/b.mp3", "Tavern Brawl", "Battle", 1024),
        MusicTrack("c.mp3", "/tmp/c.mp3", "Lute Song", "Tavern", 1024),
    ]
    widget.set_tracks(tracks, list(CategoryRegistry()))
    return widget


def visible_categories(view) -> list:
    tree = view.tree
    return [
        tree.topLevelItem(i).text(0)
        for i in range(tree.topLevelItemCount())
        if not tree.topLevelItem(i).isHidden()
    ]


def test_unfiltered_shows_every_category(view):
    assert len(visible_categories(view)) == len(CategoryRegistry())
    assert view.match_label.text() == ""


def test_search_matches_track_names(view):
    view.search_box.setText("lute")
    assert view.match_label.text() == "1/3"
    assert visible_categories(view) == ["🍺 Tavern"]


def test_search_matches_category_names(view):
    view.search_box.setText("battle")
    assert view.match_label.text() == "2/3"


def test_search_is_case_insensitive(view):
    view.search_box.setText("GOBLIN")
    assert view.match_label.text() == "1/3"


def test_no_match_hides_everything(view):
    view.search_box.setText("zzzz")
    assert view.match_label.text() == "0/3"
    assert visible_categories(view) == []


def test_clearing_restores_the_full_tree(view):
    view.search_box.setText("lute")
    view.search_box.clear()
    assert len(visible_categories(view)) == len(CategoryRegistry())
    assert view.match_label.text() == ""


def test_selected_track_survives_filtering(view):
    view.search_box.setText("goblin")
    battle = next(
        view.tree.topLevelItem(i)
        for i in range(view.tree.topLevelItemCount())
        if not view.tree.topLevelItem(i).isHidden()
    )
    view.tree.setCurrentItem(battle.child(0))
    track = view.selected_track()
    assert track is not None and track.display_name == "Goblin Ambush"


# ── local output sink ───────────────────────────────────────────────────────

def test_sink_start_is_marshalled_to_the_gui_thread(qapp):
    """Regression: QAudioSink built on the engine's thread produced silence.

    Qt audio objects must live on a thread with an event loop.  The engine calls
    start() from its asyncio thread, so the sink has to hop threads itself.
    """
    import threading

    from PyQt6.QtCore import QTimer

    from dndmusic.gui.local_output import LocalAudioSink

    sink = LocalAudioSink()
    seen = {}
    original = sink._open

    def spy(source):
        seen["thread"] = threading.current_thread().name
        return original(source)

    sink._open = spy
    threading.Thread(target=lambda: sink.start(object()), name="engine-loop").start()

    QTimer.singleShot(400, qapp.quit)
    qapp.exec()

    assert seen.get("thread") == threading.main_thread().name


def test_mixer_device_serves_exact_byte_counts(qapp):
    """Qt asks for arbitrary sizes; short reads would glitch the audio."""
    import numpy as np
    from PyQt6.QtCore import QIODeviceBase

    from dndmusic.audio.mixer import GainRamp, MixingSource, Voice
    from dndmusic.audio.pcm import FRAME_SAMPLES, array_to_frame
    from dndmusic.gui.local_output import MixerDevice

    class Constant:
        def __init__(self):
            self.frame = array_to_frame(np.full(FRAME_SAMPLES, 1234, dtype=np.int32))

        def read_frame(self):
            return self.frame

        def stop(self):
            pass

    source = MixingSource()
    source.add_voice(Voice(stream=Constant(), bus="music", gain=GainRamp(1.0)))

    device = MixerDevice(source)
    device.open(QIODeviceBase.OpenModeFlag.ReadOnly)
    for want in (1, 100, 3840, 5000, 512, 20001):
        assert len(device.readData(want)) == want

    # and it pads rather than signalling EOF once the mixer is gone
    source.cleanup()
    assert len(device.readData(3840)) == 3840


# ── output device picker ────────────────────────────────────────────────────

@pytest.fixture()
def panel(qapp):
    from dndmusic.gui.widgets.control_panel import ControlPanel

    return ControlPanel()


def test_device_list_always_offers_the_system_default(panel):
    panel.set_output_devices([])
    assert panel.device_combo.count() == 1
    assert panel.device_combo.itemData(0) == ""


def test_device_list_keeps_the_saved_choice(panel):
    panel.set_output_devices(["Speakers", "Headset"], "Headset")
    assert panel.device_combo.currentData() == "Headset"


def test_unplugged_device_falls_back_to_default(panel):
    panel.set_output_devices(["Speakers"], "Headset")
    assert panel.device_combo.currentData() == ""


def test_picking_a_device_emits_its_name(panel):
    from dndmusic.core.models import OutputMode

    panel.set_output_devices(["Speakers", "Headset"])
    seen = []
    panel.output_device_selected.connect(seen.append)
    panel.set_output_mode(OutputMode.LOCAL)
    panel.device_combo.setCurrentIndex(2)
    assert seen == ["Headset"]


def test_device_picker_is_only_enabled_for_local_output(panel):
    from dndmusic.core.models import OutputMode

    panel.set_output_devices(["Speakers"])
    panel.set_output_mode(OutputMode.DISCORD)
    assert panel.device_combo.isEnabled() is False
    panel.set_output_mode(OutputMode.LOCAL)
    assert panel.device_combo.isEnabled() is True


def test_changing_mode_by_hand_updates_the_picker(panel):
    """Regression: only the programmatic setter used to update the enabled state."""
    from dndmusic.core.models import OutputMode

    panel.set_output_devices(["Speakers"])
    panel.set_output_mode(OutputMode.DISCORD)
    index = panel.output_combo.findData(OutputMode.LOCAL)
    panel.output_combo.setCurrentIndex(index)
    assert panel.device_combo.isEnabled() is True


# ── window layout ───────────────────────────────────────────────────────────

def test_control_panel_groups_do_not_stretch(qapp):
    """Regression: tall dock + expanding groups left big dead gaps."""
    from PyQt6.QtWidgets import QScrollArea, QSizePolicy

    from dndmusic.gui.widgets.control_panel import ControlPanel

    panel = ControlPanel()
    scroll = panel.findChild(QScrollArea)
    assert scroll is not None, "controls should scroll rather than stretch"

    for group in scroll.widget().findChildren(type(panel._build_output())):
        if group.parent() is scroll.widget():
            assert group.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
