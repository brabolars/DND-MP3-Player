# tests/test_layout.py
"""Window layout: docks fill the window and can't be lost."""

import os

import pytest

pytest.importorskip("PyQt6", reason="PyQt6 not installed")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDockWidget  # noqa: E402

from dndmusic.cli import parse_args  # noqa: E402
from dndmusic.gui.main_window import LAYOUT_VERSION, MainWindow  # noqa: E402
from dndmusic.gui.ui_state import UiState  # noqa: E402
from dndmusic.services import build_services  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp, tmp_path):
    services = build_services(parse_args(["--ui-only", "--data-dir", str(tmp_path)]))
    window = MainWindow(services)
    window.resize(1600, 900)
    window.show()
    qapp.processEvents()
    yield window
    window.close()
    services.engine.shutdown()


def test_every_panel_is_a_dock(window):
    assert set(window.docks) == {"visualizer", "library", "playlist", "layers", "controls"}


def test_panels_cannot_be_closed_away(window):
    """A closed dock has no affordance to bring it back, so closing is disabled."""
    for dock in window.docks.values():
        features = dock.features()
        assert not (features & QDockWidget.DockWidgetFeature.DockWidgetClosable)
        assert features & QDockWidget.DockWidgetFeature.DockWidgetFloatable
        assert features & QDockWidget.DockWidgetFeature.DockWidgetMovable


def test_centre_takes_no_horizontal_room(window):
    """The header used to live in the centre and squeezed the docks to the edges."""
    assert window.centralWidget().width() <= 1


def test_no_dead_band_under_the_visualiser(window, qapp):
    qapp.processEvents()
    gap = window.docks["library"].geometry().top() - window.docks["visualizer"].geometry().bottom()
    assert gap < 20, f"{gap}px of dead space"


def test_panels_span_the_window(window, qapp):
    qapp.processEvents()
    spanned = sum(
        window.docks[key].geometry().width() for key in ("library", "playlist", "controls")
    )
    assert spanned > window.width() * 0.9


def test_show_all_restores_hidden_panels(window):
    window.docks["library"].hide()
    window._show_all_docks()
    assert not window.docks["library"].isHidden()


def test_float_and_reset(window):
    window._float_all_docks()
    assert all(dock.isFloating() for dock in window.docks.values())
    window._reset_layout()
    assert not any(dock.isFloating() for dock in window.docks.values())
    assert all(not dock.isHidden() for dock in window.docks.values())


def test_reset_button_recovers_a_wrecked_layout(window, qapp):
    """The escape hatch has to be reachable when the window is already a mess."""
    from PyQt6.QtWidgets import QPushButton

    button = next(
        b for b in window.top_bar.findChildren(QPushButton) if b.text() == "Reset UI"
    )

    window._float_all_docks()
    window.docks["library"].hide()
    qapp.processEvents()

    button.click()
    qapp.processEvents()

    assert not any(dock.isFloating() for dock in window.docks.values())
    assert not any(dock.isHidden() for dock in window.docks.values())


def test_reset_persists_immediately(window):
    """So a crash can't resurrect the layout you just escaped."""
    window._float_all_docks()
    window._reset_layout()
    assert UiState.load().dock_state


def test_layout_state_is_versioned(window):
    window._save_ui_state()
    assert UiState.load().extras["layout_version"] == LAYOUT_VERSION


def test_an_older_saved_layout_is_ignored(qapp, tmp_path):
    services = build_services(parse_args(["--ui-only", "--data-dir", str(tmp_path)]))
    state = UiState()
    state.extras["layout_version"] = LAYOUT_VERSION - 1
    state.dock_state = UiState.encode(b"not a real layout")
    state.save()

    window = MainWindow(services)
    window.show()
    qapp.processEvents()
    try:
        assert all(dock.isVisible() for dock in window.docks.values())
    finally:
        window.close()
        services.engine.shutdown()
