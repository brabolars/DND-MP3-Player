#!/usr/bin/env python3
# main.py
"""Launcher.

Kept deliberately tiny: it only fixes the working directory for frozen builds
and makes ``src/`` importable when running from a checkout.
"""

import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).parent)
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dndmusic.app import main  # noqa: E402

if __name__ == "__main__":
    main()
