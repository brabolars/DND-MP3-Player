# src/dndmusic/gui/theme/background.py
"""Composites a theme's background image for use in a stylesheet.

Qt stylesheets can show a background image but cannot fade one, so the image and
its black veil are blended here into a single cached PNG that the stylesheet then
points at.  Doing it once per theme change beats repainting every frame, and it
works for docked panels too, which paint over a custom paintEvent.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap

from ...config import paths

CACHE_DIR_NAME = ".background-cache"
#: Big enough for a maximised window; scaled by the stylesheet from there.
MAX_EDGE = 2560


def cache_dir() -> Path:
    directory = paths.root / CACHE_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def composite(cfg) -> Optional[str]:
    """Blend image + veil into a cached PNG.  Returns its path, or None.

    The cache key covers the source file, its mtime and both opacities, so
    editing the sliders re-renders but reopening the same theme does not.
    """
    if not cfg.background_image:
        return None

    source = Path(cfg.background_image)
    if not source.is_file():
        return None

    try:
        stamp = source.stat().st_mtime_ns
    except OSError:
        stamp = 0

    key = hashlib.sha256(
        f"{source}|{stamp}|{cfg.background_opacity:.3f}|{cfg.overlay_opacity:.3f}".encode()
    ).hexdigest()[:16]
    target = cache_dir() / f"bg_{key}.png"
    if target.exists():
        return str(target)

    image = QImage(str(source))
    if image.isNull():
        return None
    if max(image.width(), image.height()) > MAX_EDGE:
        image = image.scaled(
            MAX_EDGE,
            MAX_EDGE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    canvas = QPixmap(image.size())
    canvas.fill(QColor(0, 0, 0))          # black underneath, so fading darkens

    painter = QPainter(canvas)
    painter.setOpacity(max(0.0, min(1.0, cfg.background_opacity)))
    painter.drawImage(0, 0, image)
    painter.setOpacity(1.0)
    veil = QColor(0, 0, 0)
    veil.setAlphaF(max(0.0, min(1.0, cfg.overlay_opacity)))
    painter.fillRect(canvas.rect(), veil)
    painter.end()

    return str(target) if canvas.save(str(target), "PNG") else None


def clear_cache() -> int:
    """Drop cached composites.  Returns how many were removed."""
    removed = 0
    directory = paths.root / CACHE_DIR_NAME
    if not directory.is_dir():
        return 0
    for file in directory.glob("bg_*.png"):
        try:
            file.unlink()
            removed += 1
        except OSError:
            continue
    return removed
