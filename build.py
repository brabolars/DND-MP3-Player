# build.py
"""PyInstaller packaging script.

    python build.py              # windowed build -> dist/DnDMusicManager.exe
    python build.py --console    # same, but keeps a console for the debug log
    python build.py --dry-run    # print the command without building

Plain flags rather than a .spec file, so there is one readable script that both
you and the GitHub workflow run — a spec plus a separate CI command line is two
places to keep in sync.

Three things this build needs beyond the defaults:

* ``vendor/`` — ffmpeg.exe and libopus-0.dll are bundled when present, so the
  result runs on a machine with neither installed.  Whatever is in the folder
  gets included; a missing file is not an error, because the workflow's download
  step is allowed to fail.
* hidden imports — PyQt6.QtMultimedia (local playback) and disnake's submodules
  are reached indirectly, so PyInstaller cannot see them by static analysis.
* excludes — tkinter, PyQt5 and PySide6 would otherwise be dragged in and add
  tens of megabytes.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent.resolve()
NAME = "DnDMusicManager"
VENDOR = ROOT / "vendor"
ICON = ROOT / "packaging" / "icon.ico"

HIDDEN_IMPORTS = [
    "disnake",
    "disnake.ext.commands",
    "disnake.opus",
    "PyQt6.QtMultimedia",   # local "This PC" output
    "PyQt6.QtNetwork",
]

EXCLUDES = ["tkinter", "matplotlib", "PyQt5", "PySide6"]


def bundled_binaries() -> list[str]:
    """--add-binary arguments for everything in vendor/, if anything."""
    if not VENDOR.is_dir():
        print("No vendor/ folder — the build will rely on system FFmpeg and Opus.")
        return []

    found = [path for path in sorted(VENDOR.iterdir()) if path.is_file()]
    if not found:
        print("vendor/ is empty — the build will rely on system FFmpeg and Opus.")
        return []

    arguments = []
    for path in found:
        print(f"  bundling {path.name}")
        # PyInstaller wants source<sep>destination, and the separator differs.
        arguments += ["--add-binary", f"{path}{os.pathsep}."]
    return arguments


def build_command(console: bool) -> list[str]:
    command = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console" if console else "--windowed",
        "--name", NAME,
        "--clean",
        "--noconfirm",
        "--paths", str(ROOT / "src"),
    ]
    for module in HIDDEN_IMPORTS:
        command += ["--hidden-import", module]
    for module in EXCLUDES:
        command += ["--exclude-module", module]
    command += bundled_binaries()
    if ICON.exists():
        command += ["--icon", str(ICON)]
    command.append(str(ROOT / "main.py"))
    return command


def main() -> int:
    console = "--console" in sys.argv
    dry_run = "--dry-run" in sys.argv

    command = build_command(console)
    print("\n" + " ".join(command) + "\n")
    if dry_run:
        return 0

    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print("\nBuild failed")
        return result.returncode

    produced = ROOT / "dist" / (NAME + (".exe" if os.name == "nt" else ""))
    if produced.exists():
        size = produced.stat().st_size / (1024 * 1024)
        print(f"\nBuild successful: {produced}  ({size:.1f} MB)")
    else:
        print(f"\nBuild finished — check {ROOT / 'dist'}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())