# src/dndmusic/gui/widgets/playlist_panel.py
"""Playlist panel: queue display, ordering and save/load."""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.models import MusicTrack, PlaybackMode, enum_from_value


class PlaylistPanel(QWidget):
    mode_selected = pyqtSignal(object)
    play_index_requested = pyqtSignal(int)
    move_requested = pyqtSignal(int, int)   # position, offset
    remove_requested = pyqtSignal(int)
    clear_requested = pyqtSignal()
    save_requested = pyqtSignal()
    load_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Playlist")
        layout = QVBoxLayout(group)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([mode.value for mode in PlaybackMode])
        self.mode_combo.currentTextChanged.connect(
            lambda text: self.mode_selected.emit(
                enum_from_value(PlaybackMode, text, PlaybackMode.SINGLE)
            )
        )
        mode_row.addWidget(self.mode_combo)
        layout.addLayout(mode_row)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(
            lambda _item: self.play_index_requested.emit(self.list.currentRow())
        )
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list)

        controls = QHBoxLayout()
        for label, handler in (
            ("▲", lambda: self.move_requested.emit(self.list.currentRow(), -1)),
            ("▼", lambda: self.move_requested.emit(self.list.currentRow(), 1)),
            ("Remove", lambda: self.remove_requested.emit(self.list.currentRow())),
            ("Clear", self.clear_requested.emit),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            controls.addWidget(button)
        layout.addLayout(controls)

        io_row = QHBoxLayout()
        save_button = QPushButton("Save")
        save_button.clicked.connect(self.save_requested.emit)
        load_button = QPushButton("Load")
        load_button.clicked.connect(self.load_requested.emit)
        io_row.addWidget(save_button)
        io_row.addWidget(load_button)
        layout.addLayout(io_row)

        outer.addWidget(group)

    # ── rendering ────────────────────────────────────────────────────────

    def set_tracks(self, tracks: List[MusicTrack], current_index: Optional[int] = None) -> None:
        self.list.clear()
        for track in tracks:
            self.list.addItem(QListWidgetItem(f"{track.display_name} [{track.category}]"))
        if current_index is not None and 0 <= current_index < self.list.count():
            self.list.setCurrentRow(current_index)

    def set_mode(self, mode: PlaybackMode) -> None:
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentText(mode.value)
        self.mode_combo.blockSignals(False)

    def set_current_index(self, index: int) -> None:
        if 0 <= index < self.list.count():
            self.list.setCurrentRow(index)

    @property
    def current_index(self) -> int:
        return self.list.currentRow()

    def _on_context_menu(self, position) -> None:
        item = self.list.itemAt(position)
        if not item:
            return
        row = self.list.row(item)
        menu = QMenu(self)
        menu.addAction("Play", lambda: self.play_index_requested.emit(row))
        menu.addAction("Remove", lambda: self.remove_requested.emit(row))
        menu.exec(self.list.mapToGlobal(position))
