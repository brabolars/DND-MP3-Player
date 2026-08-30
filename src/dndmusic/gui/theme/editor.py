# src/dndmusic/gui/theme/editor.py
"""Theme editor dialog."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from pathlib import Path

from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from ...config import AUDIO_EXTENSIONS, paths  # noqa: F401  (paths used below)
from .background import composite
from .models import ThemeConfig, VisualStyle

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
PREVIEW_HEIGHT = 120

#: (label, attribute, minimum, maximum, scale, suffix)
_SLIDERS = (
    ("Glow:", "glow_intensity", 0, 100, 100.0, "%"),
    ("Corners:", "border_radius", 0, 20, 1.0, "px"),
    ("Border:", "border_width", 1, 4, 1.0, "px"),
)

_COLORS = (("Primary:", "primary"), ("Accent:", "accent"))


class ThemeEditorDialog(QDialog):
    def __init__(self, parent, cfg: ThemeConfig) -> None:
        super().__init__(parent)
        self.setWindowTitle("Theme Editor")
        self.setMinimumSize(560, 640)
        self.cfg = cfg.copy()
        self._color_buttons = {}
        self._sliders = {}
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(self.cfg.name)
        row.addWidget(self.name_edit)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Style:"))
        self.style_combo = QComboBox()
        self.style_combo.addItems([style.value for style in VisualStyle])
        self.style_combo.setCurrentText(self.cfg.visual_style.value)
        row.addWidget(self.style_combo)
        layout.addLayout(row)

        for label, attribute in _COLORS:
            layout.addLayout(self._color_row(label, attribute))

        for label, attribute, minimum, maximum, scale, suffix in _SLIDERS:
            layout.addLayout(self._slider_row(label, attribute, minimum, maximum, scale, suffix))

        layout.addWidget(self._build_background())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_background(self) -> QGroupBox:
        """Background image, its strength, and the veil that keeps text legible."""
        group = QGroupBox("Background image")
        layout = QVBoxLayout(group)

        row = QHBoxLayout()
        self.image_label = QLabel(self._image_caption())
        self.image_label.setWordWrap(True)
        row.addWidget(self.image_label, 1)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._pick_image)
        row.addWidget(choose)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear_image)
        row.addWidget(clear)
        layout.addLayout(row)

        layout.addLayout(
            self._slider_row("Image:", "background_opacity", 0, 100, 100.0, "%")
        )
        layout.addLayout(
            self._slider_row("Darken:", "overlay_opacity", 0, 100, 100.0, "%")
        )

        self.preview = QLabel()
        self.preview.setMinimumHeight(PREVIEW_HEIGHT)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("border-radius: 4px; background: rgba(0,0,0,0.4);")
        layout.addWidget(self.preview)

        # Live preview: the sliders show their effect without closing the dialog.
        for attribute in ("background_opacity", "overlay_opacity"):
            slider, _scale = self._sliders[attribute]
            slider.valueChanged.connect(lambda _v: self._refresh_preview())
        self._refresh_preview()
        return group

    def _image_caption(self) -> str:
        if not self.cfg.background_image:
            return "None — the theme's gradient is used."
        return Path(self.cfg.background_image).name

    def _pick_image(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Background image", str(paths.backgrounds), IMAGE_FILTER
        )
        if not chosen:
            return
        self.cfg.background_image = chosen
        self.image_label.setText(self._image_caption())
        self._refresh_preview()

    def _clear_image(self) -> None:
        self.cfg.background_image = ""
        self.image_label.setText(self._image_caption())
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self._sync_from_sliders()
        path = composite(self.cfg)
        if not path:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("No background image")
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview.setText("Could not read that image")
            return
        self.preview.setText("")
        self.preview.setPixmap(
            pixmap.scaledToHeight(PREVIEW_HEIGHT, Qt.TransformationMode.SmoothTransformation)
        )

    def _sync_from_sliders(self) -> None:
        for attribute, (slider, scale) in self._sliders.items():
            value = slider.value() / scale
            setattr(self.cfg, attribute, value if scale != 1.0 else int(value))

    def _color_row(self, label: str, attribute: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        value = getattr(self.cfg, attribute)
        button = QPushButton(value)
        button.setStyleSheet(f"background:{value};")
        button.clicked.connect(lambda _=False, a=attribute: self._pick_color(a))
        self._color_buttons[attribute] = button
        row.addWidget(button)
        return row

    def _slider_row(self, label, attribute, minimum, maximum, scale, suffix) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(int(getattr(self.cfg, attribute) * scale))
        value_label = QLabel(f"{slider.value()}{suffix}")
        value_label.setMinimumWidth(40)
        slider.valueChanged.connect(
            lambda v, lbl=value_label, s=suffix: lbl.setText(f"{v}{s}")
        )
        self._sliders[attribute] = (slider, scale)
        row.addWidget(slider)
        row.addWidget(value_label)
        return row

    def _pick_color(self, attribute: str) -> None:
        chosen = QColorDialog.getColor(QColor(getattr(self.cfg, attribute)), self)
        if not chosen.isValid():
            return
        setattr(self.cfg, attribute, chosen.name())
        button = self._color_buttons[attribute]
        button.setText(chosen.name())
        button.setStyleSheet(f"background:{chosen.name()};")

    def config(self) -> ThemeConfig:
        self.cfg.name = self.name_edit.text().strip() or self.cfg.name
        self.cfg.visual_style = VisualStyle(self.style_combo.currentText())
        self._sync_from_sliders()
        return self.cfg
