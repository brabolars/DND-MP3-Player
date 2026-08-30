# src/dndmusic/gui/widgets/layer_mixer.py
"""Live fader strips — one per playing voice.

Rebuilt only when the *set* of voices changes, never on every poll, so dragging
a slider isn't fought by the refresh loop.
"""

from __future__ import annotations

from typing import Dict, List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox,
    QStyle,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

BUS_COLOURS = {
    "music": "rgba(0,150,255,0.18)",
    "ambient": "rgba(0,200,0,0.15)",
    "sfx": "rgba(255,165,0,0.18)",
}


class LayerStrip(QWidget):
    """One track: name, fader, stop button."""

    trim_changed = pyqtSignal(int, int)     # voice id, percent
    stop_requested = pyqtSignal(int)
    loop_toggled = pyqtSignal(int, bool)
    pause_toggled = pyqtSignal(int, bool)

    def __init__(self, layer, parent=None) -> None:
        super().__init__(parent)
        self.voice_id = layer.voice_id
        self.setStyleSheet(
            f"background: {BUS_COLOURS.get(layer.bus, 'rgba(255,255,255,0.06)')};"
            "border-radius: 4px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        header = QHBoxLayout()
        marker = "▶ " if layer.is_primary else ""
        self.name_label = QLabel(f"{marker}{layer.label}")
        self.name_label.setStyleSheet("font-weight: bold;")
        self.name_label.setWordWrap(False)
        header.addWidget(self.name_label, 1)

        self.meta_label = QLabel(self._meta(layer))
        self.meta_label.setStyleSheet("font-size: 10px; color: #9a9a9a;")
        header.addWidget(self.meta_label)

        # Qt's standard pixmaps: no bundled assets, and they render on every
        # platform even when a font lacks the media glyphs.
        style = self.style()
        self.pause_button = QPushButton(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaPause), ""
        )
        self.pause_button.setText("Hold")
        self.pause_button.setCheckable(True)
        self.pause_button.setChecked(layer.paused)
        self.pause_button.setMaximumWidth(64)
        self.pause_button.setToolTip("Hold this track where it is")
        self.pause_button.toggled.connect(
            lambda checked: self.pause_toggled.emit(self.voice_id, checked)
        )
        header.addWidget(self.pause_button)

        self.loop_button = QPushButton(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload), ""
        )
        self.loop_button.setText("Loop")
        self.loop_button.setCheckable(True)
        self.loop_button.setChecked(layer.looping)
        self.loop_button.setMaximumWidth(64)
        self.loop_button.setToolTip("Loop this track (takes effect at the end of the pass)")
        self.loop_button.toggled.connect(
            lambda checked: self.loop_toggled.emit(self.voice_id, checked)
        )
        header.addWidget(self.loop_button)

        stop = QPushButton(
            style.standardIcon(QStyle.StandardPixmap.SP_MediaStop), ""
        )
        stop.setText("Stop")
        stop.setMaximumWidth(64)
        stop.setToolTip("Stop this track")
        stop.clicked.connect(lambda: self.stop_requested.emit(self.voice_id))
        header.addWidget(stop)
        layout.addLayout(header)

        row = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(layer.trim * 100)))
        self.value_label = QLabel(f"{self.slider.value()}%")
        self.value_label.setMinimumWidth(36)
        self.slider.valueChanged.connect(self._on_slider)
        row.addWidget(self.slider)
        row.addWidget(self.value_label)
        layout.addLayout(row)

    @staticmethod
    def _meta(layer) -> str:
        parts = [layer.bus]
        if layer.normalisation_db:
            parts.append(f"{layer.normalisation_db:+.1f} dB")
        if layer.paused:
            parts.append("held")
        return "  ".join(parts)

    def _on_slider(self, value: int) -> None:
        self.value_label.setText(f"{value}%")
        self.trim_changed.emit(self.voice_id, value)

    def update_meta(self, layer) -> None:
        """Refresh labels without touching controls the user may be holding."""
        self.meta_label.setText(self._meta(layer))
        marker = "▶ " if layer.is_primary else ""
        self.name_label.setText(f"{marker}{layer.label}")
        for button, state in ((self.loop_button, layer.looping),
                              (self.pause_button, layer.paused)):
            if button.isChecked() != state:
                button.blockSignals(True)
                button.setChecked(state)
                button.blockSignals(False)


class LayerMixerPanel(QWidget):
    """The stack of strips."""

    trim_changed = pyqtSignal(int, int)
    stop_requested = pyqtSignal(int)
    loop_toggled = pyqtSignal(int, bool)
    pause_toggled = pyqtSignal(int, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Playing now")
        group_layout = QVBoxLayout(group)

        self.empty_label = QLabel("Nothing playing.\nRight-click a track → Add as layer.")
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet("padding: 8px; color: #9a9a9a;")
        group_layout.addWidget(self.empty_label)

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(4)
        self.container_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.container)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        group_layout.addWidget(scroll)

        outer.addWidget(group)
        self._strips: Dict[int, LayerStrip] = {}

    def sync(self, layers: List) -> None:
        """Add/remove strips to match the engine, leaving existing ones alone."""
        incoming = {layer.voice_id: layer for layer in layers}

        for voice_id in list(self._strips):
            if voice_id not in incoming:
                strip = self._strips.pop(voice_id)
                self.container_layout.removeWidget(strip)
                strip.deleteLater()

        for voice_id, layer in incoming.items():
            existing = self._strips.get(voice_id)
            if existing is None:
                strip = LayerStrip(layer)
                strip.trim_changed.connect(self.trim_changed.emit)
                strip.stop_requested.connect(self.stop_requested.emit)
                strip.loop_toggled.connect(self.loop_toggled.emit)
                strip.pause_toggled.connect(self.pause_toggled.emit)
                self._strips[voice_id] = strip
                self.container_layout.insertWidget(self.container_layout.count() - 1, strip)
            else:
                existing.update_meta(layer)

        self.empty_label.setVisible(not self._strips)
