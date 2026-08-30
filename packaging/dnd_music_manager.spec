# packaging/dnd_music_manager.spec
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — one-file Windows build.

Anything dropped into ``vendor/`` (libopus-0.dll, ffmpeg.exe) is bundled next
to the executable, so the app works on a machine with nothing installed.
"""

from pathlib import Path

ROOT = Path(SPECPATH).parent
VENDOR = ROOT / "vendor"

binaries = []
if VENDOR.is_dir():
    binaries = [(str(path), ".") for path in VENDOR.iterdir() if path.is_file()]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=[],
    hiddenimports=[
        "disnake",
        "disnake.ext.commands",
        "disnake.opus",
        "dndmusic",
        "dndmusic.gui.main_window",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DnDMusicManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # set True temporarily if you need the stdout log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "icon.ico") if (ROOT / "packaging" / "icon.ico").exists() else None,
)
