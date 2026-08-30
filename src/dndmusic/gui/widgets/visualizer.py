# src/dndmusic/gui/widgets/visualizer.py
"""Animated audio visualiser.

Currently driven by a synthetic waveform; swapping in real FFT data means
replacing :meth:`VisualizerWidget._advance` only.
"""

from __future__ import annotations

import math
import random
from enum import Enum
from typing import Callable, Optional

import numpy as np
from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget


class VisualizerStyle(Enum):
    BARS = "Waveform Bars"
    RADIAL = "Radial"
    SPECTRUM = "Spectrum Analyzer"


class VisualizerWidget(QWidget):
    def __init__(self, parent=None, bars: int = 32, fps: int = 30) -> None:
        super().__init__(parent)
        self.setMinimumHeight(100)
        self.setMaximumHeight(140)

        self.style_mode = VisualizerStyle.BARS
        self.primary_color = QColor("#00d4ff")
        self.accent_color = QColor("#0099cc")

        self._num_bars = bars
        self._bar_values = np.zeros(bars)
        self._target_values = np.zeros(bars)
        self._phase = 0.0
        self._is_playing = False
        #: Set to a callable returning a normalised band array (see MusicEngine).
        self.level_provider: Optional[Callable[[], Optional[np.ndarray]]] = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(1000 / fps))

    # ── public API ───────────────────────────────────────────────────────

    def set_playing(self, playing: bool) -> None:
        self._is_playing = playing

    def set_colors(self, primary: str, accent: str) -> None:
        self.primary_color = QColor(primary)
        self.accent_color = QColor(accent)

    def set_style(self, style: VisualizerStyle) -> None:
        self.style_mode = style

    # ── animation ────────────────────────────────────────────────────────

    def _tick(self) -> None:
        self._advance()
        self._bar_values += (self._target_values - self._bar_values) * 0.25
        self.update()

    def _advance(self) -> None:
        self._phase += 0.08

        bands = self._real_bands()
        if bands is not None:
            self._target_values[:] = bands
            return

        for i in range(self._num_bars):
            if self._is_playing:
                base = 0.3 + 0.4 * math.sin(self._phase * 1.5 + i * 0.4)
                self._target_values[i] = max(0.05, min(1.0, base + random.uniform(-0.15, 0.15)))
            else:
                self._target_values[i] = 0.05 + 0.08 * math.sin(self._phase + i * 0.3)

    def _real_bands(self) -> Optional[np.ndarray]:
        """Live spectrum from the mixer, resampled to the bar count."""
        if self.level_provider is None:
            return None
        try:
            bands = self.level_provider()
        except Exception:
            return None
        if bands is None or len(bands) == 0 or not bands.any():
            return None
        if len(bands) != self._num_bars:
            indices = np.linspace(0, len(bands) - 1, self._num_bars)
            bands = np.interp(indices, np.arange(len(bands)), bands)
        return np.clip(bands, 0.03, 1.0)

    # ── painting ─────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        painter.fillRect(0, 0, width, height, QColor(0, 0, 0, 40))

        if self.style_mode is VisualizerStyle.BARS:
            self._draw_bars(painter, width, height)
        elif self.style_mode is VisualizerStyle.RADIAL:
            self._draw_radial(painter, width, height)
        else:
            self._draw_spectrum(painter, width, height)

        painter.end()

    def _draw_bars(self, painter: QPainter, width: int, height: int) -> None:
        gap = 2
        bar_width = max(2, (width - gap * self._num_bars) / self._num_bars)
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(self._num_bars):
            bar_height = int(self._bar_values[i] * (height - 10))
            x = int(i * (bar_width + gap) + gap)
            y = height - bar_height - 2

            gradient = QLinearGradient(x, y, x, height)
            gradient.setColorAt(0.0, self.primary_color)
            gradient.setColorAt(1.0, self.accent_color)
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(x, y, int(bar_width), bar_height, 2, 2)

    def _draw_radial(self, painter: QPainter, width: int, height: int) -> None:
        cx, cy = width // 2, height // 2
        base_radius = min(cx, cy) * 0.35

        for i in range(self._num_bars):
            angle = (2 * math.pi * i / self._num_bars) - math.pi / 2
            value = self._bar_values[i]
            length = base_radius * 0.3 + value * base_radius * 0.9

            inner = base_radius * 0.4
            x1 = cx + math.cos(angle) * inner
            y1 = cy + math.sin(angle) * inner
            x2 = cx + math.cos(angle) * (inner + length)
            y2 = cy + math.sin(angle) * (inner + length)

            color = QColor(self.primary_color)
            color.setAlphaF(0.5 + value * 0.5)
            pen = QPen(color, 2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        glow = QRadialGradient(cx, cy, base_radius * 0.35)
        glow.setColorAt(
            0,
            QColor(
                self.primary_color.red(),
                self.primary_color.green(),
                self.primary_color.blue(),
                60,
            ),
        )
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(QPointF(cx, cy), base_radius * 0.35, base_radius * 0.35)

    def _draw_spectrum(self, painter: QPainter, width: int, height: int) -> None:
        if self._num_bars < 2:
            return

        middle = height // 2
        top, bottom = [], []
        for i in range(self._num_bars):
            x = int(i * width / (self._num_bars - 1))
            offset = int(self._bar_values[i] * middle * 0.85)
            top.append(QPointF(x, middle - offset))
            bottom.append(QPointF(x, middle + offset))

        gradient = QLinearGradient(0, 0, 0, height)
        edge = QColor(self.primary_color)
        edge.setAlphaF(0.5)
        centre = QColor(self.accent_color)
        centre.setAlphaF(0.15)
        gradient.setColorAt(0, edge)
        gradient.setColorAt(0.5, centre)
        gradient.setColorAt(1, edge)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawPolygon(top + list(reversed(bottom)))

        for points, color in ((top, self.primary_color), (bottom, self.accent_color)):
            pen = QPen(color, 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            for start, end in zip(points, points[1:]):
                painter.drawLine(start, end)
