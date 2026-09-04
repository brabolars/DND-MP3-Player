# src/dndmusic/core/debug.py
"""In-memory rolling log, mirrored to stdout and dumpable over Discord."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, List

from ..config import APP_NAME, APP_VERSION


#: Session logs to keep before the oldest are deleted.
MAX_LOG_FILES = 10


class DebugLogger:
    def __init__(self, max_entries: int = 500, to_file: bool = True) -> None:
        self.messages: List[str] = []
        self.session_start = datetime.now()
        self._max = max_entries
        self._file = None
        if to_file:
            self._open_log_file()
        self.log("=== SESSION STARTED ===", "SYS")

    # ── file output ──────────────────────────────────────────────────────

    def _open_log_file(self) -> None:
        """Mirror everything to logs/.  Never fatal if it can't be opened."""
        from ..config import paths

        try:
            paths.logs.mkdir(parents=True, exist_ok=True)
            self._prune_old_logs(paths.logs)
            target = paths.logs / f"session-{self.session_start:%Y%m%d-%H%M%S}.log"
            self._file = target.open("a", encoding="utf-8", buffering=1)
        except Exception:
            self._file = None

    @staticmethod
    def _prune_old_logs(directory) -> None:
        try:
            existing = sorted(directory.glob("session-*.log"))
            for stale in existing[: max(0, len(existing) - MAX_LOG_FILES + 1)]:
                stale.unlink(missing_ok=True)
        except Exception:
            pass

    @property
    def log_file(self):
        return getattr(self._file, "name", None)

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

    def log(self, message: str, category: str = "GEN") -> None:
        line = f"[{datetime.now():%H:%M:%S}][{category}] {message}"
        self.messages.append(line)
        if len(self.messages) > self._max:
            self.messages.pop(0)
        print(line)
        if self._file is not None:
            try:
                self._file.write(self.redact(line) + "\n")
            except Exception:
                self._file = None

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
