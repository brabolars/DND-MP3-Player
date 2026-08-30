# src/dndmusic/cli.py
"""Command line parsing."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Optional, Sequence

from .config import APP_NAME, APP_VERSION


@dataclass
class AppArgs:
    ui_only: bool = False
    dev: bool = False
    data_dir: Optional[str] = None

    @property
    def discord_enabled(self) -> bool:
        return not self.ui_only


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dnd-music-manager", description=APP_NAME)
    parser.add_argument("--ui-only", action="store_true",
                        help="Launch the UI without connecting to Discord")
    parser.add_argument("--dev", action="store_true",
                        help="Development mode: read the token from .env, skip the auth server")
    parser.add_argument("--data-dir", default=None,
                        help="Override where music/library/config files are stored")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return parser


def parse_args(argv: Optional[Sequence[str]] = None) -> AppArgs:
    # parse_known_args keeps Qt's own switches (-style, -platform, ...) working.
    ns, _ = build_parser().parse_known_args(argv)
    return AppArgs(ui_only=ns.ui_only, dev=ns.dev, data_dir=ns.data_dir)
