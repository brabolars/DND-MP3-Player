# src/dndmusic/gui/widgets/library_panel.py
"""Tab container holding the three library views."""

from __future__ import annotations

from PyQt6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .ambient_view import AmbientView
from .music_library_view import MusicLibraryView
from .sfx_view import SfxView


class LibraryPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.music = MusicLibraryView()
        self.sfx = SfxView()
        self.ambient = AmbientView()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.music, "Music")
        self.tabs.addTab(self.sfx, "SFX")
        self.tabs.addTab(self.ambient, "Ambient")
        layout.addWidget(self.tabs)
