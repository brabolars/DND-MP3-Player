# src/dndmusic/gui/widgets/ambient_view.py
"""Ambient bed tab.

Since mixing now happens in-process, the ambient bed is just another voice on
its own bus: selecting one crossfades it in under whatever is already playing,
and its volume is a live gain change.  The old "real-time vs pre-compile" choice
and the Compile button are gone — both existed only to work around FFmpeg
having to be respawned.
"""

from __future__ import annotations

from typing import List, Optional

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

_STATUS_STYLE = "padding:6px; border-radius:4px; font-weight:bold; background:{background};"
_IDLE = "rgba(100,100,100,0.12)"
_ACTIVE = "rgba(0,200,0,0.15)"


class AmbientView(QWidget):
    add_files_requested = pyqtSignal()
    ambient_selected = pyqtSignal(object)
    ambient_cleared = pyqtSignal()
    delete_requested = pyqtSignal(object)
    volume_changed = pyqtSignal(int)
    loop_toggled = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        info = QLabel(
            "Ambient loops on its own mixer bus — it fades in under the music "
            "and keeps playing while tracks change."
        )
        info.setWordWrap(True)
        info.setStyleSheet("padding: 6px; background: rgba(255,255,255,0.06); border-radius: 4px;")
        layout.addWidget(info)

        self.status = QLabel()
        layout.addWidget(self.status)
        self.set_active(None)

        top_row = QHBoxLayout()
        add_button = QPushButton("Add Ambient")
        add_button.clicked.connect(self.add_files_requested.emit)
        top_row.addWidget(add_button)

        self.loop_button = QPushButton("↻ Loop")
        self.loop_button.setCheckable(True)
        self.loop_button.setChecked(True)
        self.loop_button.setToolTip("Repeat the ambient bed (takes effect at the end of a pass)")
        self.loop_button.toggled.connect(self.loop_toggled.emit)
        top_row.addWidget(self.loop_button)
        layout.addLayout(top_row)

        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_click)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list)

        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("Ambient Vol:"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(30)
        self.volume_label = QLabel("30%")
        self.volume_label.setMinimumWidth(40)
        self.volume_slider.valueChanged.connect(self._on_volume)
        volume_row.addWidget(self.volume_slider)
        volume_row.addWidget(self.volume_label)
        layout.addLayout(volume_row)

        clear_button = QPushButton("Clear Ambient")
        clear_button.clicked.connect(self.ambient_cleared.emit)
        layout.addWidget(clear_button)

    # ── rendering ────────────────────────────────────────────────────────

    def set_tracks(self, tracks: List[MusicTrack], active_path: Optional[str]) -> None:
        self.list.clear()
        for track in tracks:
            marker = "▶ " if active_path == track.path else ""
            item = QListWidgetItem(f"{marker}{track.display_name}")
            item.setData(TRACK_ROLE, track)
            self.list.addItem(item)

    def set_active(self, track: Optional[MusicTrack]) -> None:
        if track is None:
            self.status.setText("No ambient playing")
            self.status.setStyleSheet(_STATUS_STYLE.format(background=_IDLE))
        else:
            self.status.setText(f"Looping: {track.display_name}")
            self.status.setStyleSheet(_STATUS_STYLE.format(background=_ACTIVE))

    def set_loop(self, enabled: bool) -> None:
        self.loop_button.blockSignals(True)
        self.loop_button.setChecked(enabled)
        self.loop_button.blockSignals(False)

    def set_volume(self, percent: int) -> None:
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(percent)
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(f"{percent}%")

    # ── interaction ──────────────────────────────────────────────────────

    def _on_volume(self, value: int) -> None:
        self.volume_label.setText(f"{value}%")
        self.volume_changed.emit(value)

    def _on_click(self, item) -> None:
        self.ambient_selected.emit(item.data(TRACK_ROLE))

    def _on_context_menu(self, position) -> None:
        item = self.list.itemAt(position)
        if not item:
            return
        track = item.data(TRACK_ROLE)
        menu = QMenu(self)
        menu.addAction("Play as ambient", lambda: self.ambient_selected.emit(track))
        menu.addSeparator()
        menu.addAction("Delete", lambda: self.delete_requested.emit(track))
        menu.exec(self.list.mapToGlobal(position))
