#!/usr/bin/env python3
# tools/verify_layout.py
"""Check a checkout against the manifest of expected files.

Copying files by hand goes wrong in three ways, and all three surface later as
confusing import errors: a file is missing, a file is an older version, or a file
that was deleted upstream is still present.  This finds all of them at once.

    python tools/verify_layout.py            # report
    python tools/verify_layout.py --fix      # also repair trailing newlines
    python tools/verify_layout.py --generate # rewrite the manifest from this tree

Use --generate after you have intentionally edited files, to make the current
state the new baseline.  Line endings are normalised before hashing, so CRLF and
LF compare equal.  Only src/ and tests/ are checked for unexpected files — your
music, playlists and .env are none of its business.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).resolve().parent / "manifest.txt"
MANIFEST_VERSION = "3.6.0"

TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".yml", ".yaml", ".spec", ".example", ""}
CHECKED_TREES = ("src", "tests")
IGNORED_PARTS = {
    "__pycache__", ".git", ".pytest_cache", ".ruff_cache", ".venv", "venv",
    "music_files", "sound_effects", "ambient_sounds", "playlists", "temp_mixes",
    "build", "dist", "vendor",
}
IGNORED_NAMES = {
    ".env", "music_data.json", "custom_themes.json", "custom_categories.json",
    "mixer_settings.json", "ui_state.json", "manifest.txt", "manifest.json",
    # PyInstaller regenerates this beside build.py on every run.
    "DnDMusicManager.spec",
}


# ── hashing ──────────────────────────────────────────────────────────────────

def normalise(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return data


def digest(path: Path) -> str:
    return hashlib.sha256(normalise(path)).hexdigest()


def tracked_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if set(relative.parts) & IGNORED_PARTS or path.name in IGNORED_NAMES:
            continue
        yield path, relative.as_posix()


# ── manifest format ──────────────────────────────────────────────────────────
#
# Plain text rather than JSON: a truncated copy is detectable (the header
# declares the file count), and no editor can mangle it into invalid syntax.

def write_manifest() -> int:
    lines = [f"# dnd-music-manager manifest v{MANIFEST_VERSION}"]
    entries = []
    for path, relative in tracked_files():
        data = normalise(path)
        newlines = data.count(b"\n")
        entries.append(
            f"{hashlib.sha256(data).hexdigest()} {len(data)} {newlines} {relative}"
        )
    lines.append(f"# files: {len(entries)}")
    lines += entries
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(entries)


def read_manifest() -> Optional[Dict[str, dict]]:
    """Parse the manifest, or explain clearly why it can't be used."""
    if not MANIFEST.exists():
        print(f"No manifest at {MANIFEST}")
        print("Copy tools/manifest.txt in, or run with --generate to create one.")
        return None

    raw = MANIFEST.read_text(encoding="utf-8", errors="replace").strip()
    if not raw:
        print(f"The manifest at {MANIFEST} is empty.")
        print("The copy did not come through — re-copy tools/manifest.txt.")
        return None

    declared = None
    expected: Dict[str, dict] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("# files:"):
                try:
                    declared = int(line.split(":", 1)[1])
                except ValueError:
                    pass
            continue
        parts = line.split(" ", 3)
        if len(parts) != 4:
            print(f"Malformed manifest line, ignoring: {line[:60]}")
            continue
        sha, size, lines_count, relative = parts
        expected[relative] = {
            "sha256": sha,
            "bytes": int(size) if size.isdigit() else 0,
            "lines": int(lines_count) if lines_count.isdigit() else 0,
        }

    if not expected:
        print(f"The manifest at {MANIFEST} has no usable entries.")
        print("Re-copy it, or run with --generate.")
        return None

    if declared is not None and declared != len(expected):
        print(f"The manifest looks truncated: it declares {declared} files but "
              f"only {len(expected)} lines parsed.")
        print("Re-copy tools/manifest.txt in full.\n")

    return expected


# ── comparison ───────────────────────────────────────────────────────────────

def newline_only_repair(path: Path, want: dict) -> Optional[bytes]:
    """If only the trailing newline differs, return the repaired bytes.

    Proven, not guessed: the candidate is hashed against the manifest.
    """
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return None
    data = normalise(path)
    candidates = [data + b"\n"]
    if data.endswith(b"\n"):
        candidates.append(data[:-1])
    for candidate in candidates:
        if hashlib.sha256(candidate).hexdigest() == want["sha256"]:
            return candidate
    return None


def explain(path: Path, want: dict) -> str:
    data = normalise(path)
    size, lines = len(data), data.count(b"\n")
    expected_size, expected_lines = want["bytes"], want["lines"]
    delta = size - expected_size
    detail = f"yours {size}B/{lines}L vs expected {expected_size}B/{expected_lines}L"

    if abs(delta) <= 2 and lines in (expected_lines, expected_lines - 1):
        return f"{detail}  -> copy artifact (trailing newline)"
    if size == 0:
        return f"{detail}  -> EMPTY; the copy did not come through"
    if abs(delta) < max(40, expected_size * 0.02):
        return f"{detail}  -> nearly identical; whitespace or a hand edit"
    if delta < 0:
        return f"{detail}  -> {abs(delta)}B shorter: older version, or truncated paste"
    return f"{detail}  -> {delta}B larger: older version, or extra content"


def main() -> int:
    if "--generate" in sys.argv:
        count = write_manifest()
        print(f"Wrote {MANIFEST} with {count} files.")
        return 0

    expected = read_manifest()
    if expected is None:
        return 2

    fix = "--fix" in sys.argv
    missing, stale, newline_only, ok = [], [], [], 0

    for relative, want in sorted(expected.items()):
        path = ROOT / relative
        if not path.exists():
            missing.append(relative)
            continue
        if digest(path) == want["sha256"]:
            ok += 1
            continue
        repair = newline_only_repair(path, want)
        if repair is None:
            stale.append((relative, explain(path, want)))
        elif fix:
            crlf = b"\r\n" in path.read_bytes()
            path.write_bytes(repair.replace(b"\n", b"\r\n") if crlf else repair)
            ok += 1
            newline_only.append((relative, "repaired"))
        else:
            newline_only.append((relative, "missing trailing newline"))

    unexpected = []
    for tree in CHECKED_TREES:
        directory = ROOT / tree
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or set(path.parts) & IGNORED_PARTS:
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative not in expected and path.name not in IGNORED_NAMES:
                unexpected.append(relative)

    print(f"{ok} of {len(expected)} file(s) match the manifest.\n")

    if missing:
        print(f"MISSING ({len(missing)}) — copy these in:")
        for item in missing:
            print(f"    {item}")
        print()
    if stale:
        print(f"OUT OF DATE ({len(stale)}) — overwrite with the current version:")
        for relative, reason in stale:
            print(f"    {relative}")
            print(f"        {reason}")
        print()
    if newline_only:
        print(f"NEWLINE ONLY ({len(newline_only)}) — content identical, harmless:")
        for relative, note in newline_only:
            print(f"    {relative}  ({note})")
        if not fix:
            print("    Run with --fix to normalise them.")
        print()
    if unexpected:
        print(f"UNEXPECTED ({len(unexpected)}) — deleted upstream, or your own additions:")
        for item in sorted(unexpected):
            print(f"    {item}")
        print()

    if missing or stale or unexpected:
        print("Fix the above, then run:  python -m pytest -q")
        return 1
    if newline_only and not fix:
        print("Only trailing-newline differences — safe, or rerun with --fix.")
    print("Layout is correct.  Run:  python -m pytest -q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())