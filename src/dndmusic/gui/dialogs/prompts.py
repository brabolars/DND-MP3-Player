# src/dndmusic/gui/dialogs/prompts.py
"""Thin wrappers around Qt's stock dialogs, so widgets stay free of them."""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from ...config import AUDIO_FILE_FILTER
from ...core.categories import CategoryRegistry


def pick_audio_files(parent, title: str) -> List[str]:
    files, _ = QFileDialog.getOpenFileNames(parent, title, "", AUDIO_FILE_FILTER)
    return files


def choose_category(
    parent, categories: CategoryRegistry, exclude: Optional[str] = None, title: str = "Category"
) -> Optional[str]:
    displays = [c.display for c in categories if c.name != exclude]
    if not displays:
        return None
    choice, accepted = QInputDialog.getItem(parent, title, "Choose:", displays, 0, False)
    if not accepted:
        return None
    return categories.name_for(choice)


def ask_text(parent, title: str, label: str, default: str = "") -> Optional[str]:
    text, accepted = QInputDialog.getText(parent, title, label, text=default)
    if not accepted:
        return None
    text = text.strip()
    return text or None


def confirm(parent, title: str, question: str) -> bool:
    return (
        QMessageBox.question(parent, title, question) == QMessageBox.StandardButton.Yes
    )


def warn(parent, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)


def inform(parent, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)
