# src/dndmusic/app.py
"""Application entry point: build services, then hand them to Qt."""

from __future__ import annotations

import sys
from typing import Optional, Sequence

from .cli import parse_args
from .config import APP_NAME, APP_VERSION
from .services import build_services, environment_report


def _print_banner(services) -> None:
    print("=" * 50)
    for line in environment_report(services.ffmpeg):
        print(f"  {line}")
    print(f"  Mode: {'Normal' if services.discord_enabled else 'UI-only'}")
    print("=" * 50)


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    services = build_services(args)
    _print_banner(services)

    # Imported late so that --help and --version work without a display.
    from PyQt6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")

    window = MainWindow(services)
    window.show()
    return app.exec()


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
