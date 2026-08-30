# src/dndmusic/gui/widgets/music_library_view.py
"""Music library tree (categories -> tracks)."""

from __future__ import annotations

from typing import Iterable, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.models import MusicTrack

TRACK_ROLE = Qt.ItemDataRole.UserRole


class MusicLibraryView(QWidget):
    play_requested = pyqtSignal(object)
    enqueue_requested = pyqtSignal(object)
    rename_requested = pyqtSignal(object)
    recategorise_requested = pyqtSignal(object)
    delete_requested = pyqtSignal(object)
    add_files_requested = pyqtSignal()
    new_category_requested = pyqtSignal()
    rescan_requested = pyqtSignal()
    layer_requested = pyqtSignal(object)
    analyse_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._tracks: List[MusicTrack] = []
        self._categories: list = []
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        buttons = QHBoxLayout()
        for text, signal in (
            ("Add Music", self.add_files_requested),
            ("Rename", None),
            ("New Folder", self.new_category_requested),
            ("Rescan", self.rescan_requested),
            ("Analyse", self.analyse_requested),
        ):
            button = QPushButton(text)
            if signal is None:
                button.clicked.connect(self._rename_current)
            else:
                button.clicked.connect(signal.emit)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)

        search_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search the library…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search)
        search_row.addWidget(self.search_box)
        self.match_label = QLabel()
        self.match_label.setStyleSheet("color: #9a9a9a; font-size: 11px;")
        self.match_label.setMinimumWidth(70)
        search_row.addWidget(self.match_label)
        layout.addLayout(search_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Library", "Size"])
        self.tree.setColumnWidth(0, 260)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.tree)

    # ── rendering ────────────────────────────────────────────────────────

    def set_tracks(self, tracks: List[MusicTrack], categories: Iterable) -> None:
        self._tracks = list(tracks)
        self._categories = list(categories)
        self._render()

    def _on_search(self, _text: str) -> None:
        self._render()

    def _render(self) -> None:
        """Rebuild the tree, honouring the search box.

        Matching is case-insensitive across the track name and its category, so
        "tav" finds both a Tavern-category track and one called "Tavern Brawl".
        """
        query = self.search_box.text().strip().lower()
        self.tree.clear()

        nodes = {}
        for category in self._categories:
            node = QTreeWidgetItem(self.tree)
            node.setText(0, category.display)
            nodes[category.name] = node

        shown = 0
        for track in self._tracks:
            if query and query not in f"{track.display_name} {track.category}".lower():
                continue
            parent = nodes.get(track.category)
            if parent is None:
                continue
            item = QTreeWidgetItem(parent)
            item.setText(0, track.display_name)
            item.setText(1, track.size_label)
            # The track object rides along on the item, so lookups can't drift
            # out of sync with display names (the old code matched on strings).
            item.setData(0, TRACK_ROLE, track)
            parent.setExpanded(True)
            shown += 1

        if query:
            # Hide categories with no hits, so results aren't buried in empties.
            for node in nodes.values():
                node.setHidden(node.childCount() == 0)
            self.match_label.setText(f"{shown}/{len(self._tracks)}")
        else:
            self.match_label.setText("")

    # ── interaction ──────────────────────────────────────────────────────

    def selected_track(self) -> Optional[MusicTrack]:
        return self._track_for(self.tree.currentItem())

    @staticmethod
    def _track_for(item) -> Optional[MusicTrack]:
        if item is None:
            return None
        return item.data(0, TRACK_ROLE)

    def _rename_current(self) -> None:
        track = self.selected_track()
        if track:
            self.rename_requested.emit(track)

    def _on_double_click(self, item, _column: int) -> None:
        track = self._track_for(item)
        if track:
            self.play_requested.emit(track)

    def _on_context_menu(self, position) -> None:
        track = self._track_for(self.tree.itemAt(position))
        if not track:
            return
        menu = QMenu(self)
        menu.addAction("Play Now", lambda: self.play_requested.emit(track))
        menu.addAction("Add as layer (play alongside)", lambda: self.layer_requested.emit(track))
        menu.addAction("Add to Playlist", lambda: self.enqueue_requested.emit(track))
        menu.addSeparator()
        menu.addAction("Change Category", lambda: self.recategorise_requested.emit(track))
        menu.addAction("Rename", lambda: self.rename_requested.emit(track))
        menu.addAction("Delete", lambda: self.delete_requested.emit(track))
        menu.exec(self.tree.mapToGlobal(position))
