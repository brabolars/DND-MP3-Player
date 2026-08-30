# src/dndmusic/gui/dialogs/token_setup.py
"""First-run dialog asking for the Discord bot token."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ...bot.auth import write_env_token
from ...config import APP_NAME

_EXPLANATION = (
    "To connect to Discord, this app needs a bot token.\n\n"
    "Your token is saved locally in a .env file next to the app\n"
    "and is never sent anywhere else.\n\n"
    "If you're the DM and received this app, ask the developer\n"
    "for the token. If you ARE the developer, get it from\n"
    "discord.com/developers."
)


class TokenSetupDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("First-Time Setup")
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        header = QLabel(f"Welcome to {APP_NAME}!")
        header.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        layout.addWidget(header)

        explanation = QLabel(_EXPLANATION)
        explanation.setWordWrap(True)
        explanation.setStyleSheet(
            "padding: 8px; background: rgba(255,255,255,0.05); border-radius: 6px;"
        )
        layout.addWidget(explanation)

        layout.addWidget(QLabel("Paste your Discord bot token:"))
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("MTQxMjM2...")
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.token_input)

        show_token = QCheckBox("Show token")
        show_token.toggled.connect(
            lambda visible: self.token_input.setEchoMode(
                QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
            )
        )
        layout.addWidget(show_token)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def token(self) -> str:
        return self.token_input.text().strip()


def show_token_setup_dialog(parent=None, persist: bool = True) -> Optional[str]:
    dialog = TokenSetupDialog(parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    token = dialog.token()
    if not token:
        return None
    if persist:
        write_env_token(token)
    return token
