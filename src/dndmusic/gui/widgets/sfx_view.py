# src/dndmusic/gui/widgets/sfx_view.py
"""Sound-effects tab.  SFX layer on top of the music without interrupting it."""

from __future__ import annotations

from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ...core.models import MusicTrack

TRACK_ROLE = Qt.ItemDataRole.UserRole


class SfxView(QWidget):
    play_requested = pyqtSignal(object)
    delete_requested = pyqtSignal(object)
    add_files_requested = pyqtSignal()
    volume_changed = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        info = QLabel("Double-click to fire — plays over the music, several at once.")
        info.setWordWrap(True)
        info.setStyleSheet("padding: 6px; background: rgba(255,255,255,0.06); border-radius: 4px;")
        layout.addWidget(info)

        add_button = QPushButton("Add SFX")
        add_button.clicked.connect(self.add_files_requested.emit)
        layout.addWidget(add_button)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._on_double_click)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list)

        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("SFX Vol:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_label = QLabel("80%")
        self.volume_label.setMinimumWidth(40)
        self.volume_slider.valueChanged.connect(self._on_volume)
        volume_row.addWidget(self.volume_slider)
        volume_row.addWidget(self.volume_label)
        layout.addLayout(volume_row)

    def set_tracks(self, tracks: List[MusicTrack]) -> None:
        self.list.clear()
        for track in tracks:
            item = QListWidgetItem(track.display_name)
            item.setData(TRACK_ROLE, track)
            self.list.addItem(item)

    def set_volume(self, percent: int) -> None:
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(percent)
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(f"{percent}%")

    def _on_volume(self, value: int) -> None:
        self.volume_label.setText(f"{value}%")
        self.volume_changed.emit(value)

    def _on_double_click(self, item) -> None:
        self.play_requested.emit(item.data(TRACK_ROLE))

    def _on_context_menu(self, position) -> None:
        item = self.list.itemAt(position)
        if not item:
            return
        track = item.data(TRACK_ROLE)
        menu = QMenu(self)
        menu.addAction("Play", lambda: self.play_requested.emit(track))
        menu.addAction("Delete", lambda: self.delete_requested.emit(track))
        menu.exec(self.list.mapToGlobal(position))
