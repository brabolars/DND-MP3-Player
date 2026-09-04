# src/dndmusic/gui/widgets/top_bar.py
"""Top bar: theme picker, theme editor button, visualiser style picker."""

from __future__ import annotations

from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from ...config import APP_NAME, APP_VERSION
from ..widgets.visualizer import VisualizerStyle


class TopBar(QWidget):
    theme_selected = pyqtSignal(str)
    customise_requested = pyqtSignal()
    visualizer_style_selected = pyqtSignal(object)
    reset_layout_requested = pyqtSignal()

    def __init__(self, theme_labels: List[str], current_label: str, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        layout.addWidget(QLabel("Theme:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(theme_labels)
        self.theme_combo.setCurrentText(current_label)
        self.theme_combo.setMinimumWidth(160)
        self.theme_combo.currentTextChanged.connect(self.theme_selected.emit)
        layout.addWidget(self.theme_combo)

        customise = QPushButton("Customize")
        customise.clicked.connect(self.customise_requested.emit)
        layout.addWidget(customise)

        # Within reach rather than buried in a menu: the moment you need it, the
        # window is usually already in a state you don't want to navigate.
        reset = QPushButton("Reset UI")
        reset.setToolTip(
            "Put every panel back where it started and make them all visible.\n"
            "Affects the layout only — themes, levels and your library are untouched."
        )
        reset.clicked.connect(self.reset_layout_requested.emit)
        layout.addWidget(reset)

        layout.addSpacing(12)
        layout.addWidget(QLabel("Visualizer:"))
        self.visualizer_combo = QComboBox()
        self.visualizer_combo.addItems([style.value for style in VisualizerStyle])
        self.visualizer_combo.currentTextChanged.connect(self._emit_style)
        layout.addWidget(self.visualizer_combo)

        layout.addStretch()
        title = QLabel(f"{APP_NAME.upper()} v{APP_VERSION.split('.')[0]}")
        title.setStyleSheet("font-size: 15px; font-weight: bold; letter-spacing: 2px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addStretch()

    def _emit_style(self, text: str) -> None:
        for style in VisualizerStyle:
            if style.value == text:
                self.visualizer_style_selected.emit(style)
                return

    def add_theme_label(self, label: str) -> None:
        existing = [self.theme_combo.itemText(i) for i in range(self.theme_combo.count())]
        if label not in existing:
            self.theme_combo.addItem(label)
        self.theme_combo.setCurrentText(label)
