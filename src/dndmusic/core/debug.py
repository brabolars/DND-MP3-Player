# src/dndmusic/core/debug.py
"""In-memory rolling log, mirrored to stdout and dumpable over Discord."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from ..config import APP_NAME, APP_VERSION


class DebugLogger:
    def __init__(self, max_entries: int = 500) -> None:
        self.messages: List[str] = []
        self.session_start = datetime.now()
        self._max = max_entries
        self.log("=== SESSION STARTED ===", "SYS")

    def log(self, message: str, category: str = "GEN") -> None:
        line = f"[{datetime.now():%H:%M:%S}][{category}] {message}"
        self.messages.append(line)
        if len(self.messages) > self._max:
            self.messages.pop(0)
        print(line)

    def log_environment(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.log(line, "SYS")

    def redact(self, text: str) -> str:
        """Replace local paths with placeholders.

        The log goes to Discord via !debug, and full paths give away a Windows
        username and directory layout for no diagnostic benefit.
        """
        from ..config import paths

        replacements = [
            (str(paths.root), "<data>"),
            (str(Path.home()), "<home>"),
        ]
        for needle, placeholder in replacements:
            if not needle:
                continue
            text = text.replace(needle, placeholder)
            text = text.replace(needle.replace("\\", "/"), placeholder)
        return text

    def dump(self) -> str:
        uptime = int((datetime.now() - self.session_start).total_seconds())
        header = (
            f"=== {APP_NAME} v{APP_VERSION} DEBUG LOG ===\n"
            f"Session: {self.session_start:%Y-%m-%d %H:%M:%S}\n"
            f"Uptime: {uptime // 60}m {uptime % 60}s | Entries: {len(self.messages)}\n"
            f"{'=' * 40}\n"
        )
        return self.redact(header + "\n".join(self.messages))

    def last(self, count: int = 50) -> str:
        return self.redact("\n".join(self.messages[-count:]))