# src/dndmusic/gui/widgets/__init__.py
"""Reusable UI panels.

Every widget is *dumb*: it renders what it is given and emits Qt signals
describing user intent.  It never touches the library, the engine or the bot —
:class:`~dndmusic.gui.main_window.MainWindow` wires intents to services.
"""

from .ambient_view import AmbientView
from .control_panel import ControlPanel
from .layer_mixer import LayerMixerPanel, LayerStrip
from .library_panel import LibraryPanel
from .music_library_view import MusicLibraryView
from .playlist_panel import PlaylistPanel
from .sfx_view import SfxView
from .top_bar import TopBar
from .visualizer import VisualizerStyle, VisualizerWidget

__all__ = [
    "AmbientView",
    "ControlPanel",
    "LayerMixerPanel",
    "LayerStrip",
    "LibraryPanel",
    "MusicLibraryView",
    "PlaylistPanel",
    "SfxView",
    "TopBar",
    "VisualizerStyle",
    "VisualizerWidget",
]
