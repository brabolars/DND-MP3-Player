#!/usr/bin/env python3
# tools/add_path_headers.py
"""Add the `# <relative path>` header comment to files that are missing it.

Every file in this project starts with a comment naming its own path, so a file
taken out of context can be put back.  If you have an older copy of the tree, the
headers are the only difference in most files — this adds them in place rather
than making you re-copy 50 files for a one-line change.

    python tools/add_path_headers.py --dry-run   # show what would change
    python tools/add_path_headers.py             # apply

Idempotent, and it preserves shebangs and existing line endings.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HASH_STYLE = {".py", ".yml", ".yaml", ".toml", ".spec", ".txt"}
MARKDOWN_STYLE = {".md"}
BY_NAME = {".gitignore": "hash", ".env.example": "hash"}

SKIP_PARTS = {
    "__pycache__", ".git", ".pytest_cache", ".ruff_cache", ".venv", "venv",
    "music_files", "sound_effects", "ambient_sounds", "playlists", "temp_mixes",
    "build", "dist", "vendor",
}
SKIP_NAMES = {
    "manifest.txt", "manifest.json", ".env", "music_data.json",
    "custom_themes.json", "custom_categories.json", "mixer_settings.json",
}


def comment_style(path: Path) -> str | None:
    if path.name in BY_NAME:
        return BY_NAME[path.name]
    suffix = path.suffix.lower()
    if suffix in HASH_STYLE:
        return "hash"
    if suffix in MARKDOWN_STYLE:
        return "markdown"
    return None


def header_for(relative: str, style: str) -> str:
    return f"<!-- {relative} -->" if style == "markdown" else f"# {relative}"


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    added, already, skipped = [], 0, 0

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(ROOT)
        if set(relative_path.parts) & SKIP_PARTS or path.name in SKIP_NAMES:
            continue

        style = comment_style(path)
        if style is None:
            skipped += 1
            continue

        relative = relative_path.as_posix()
        header = header_for(relative, style)

        raw = path.read_bytes()
        crlf = b"\r\n" in raw
        text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
        lines = text.split("\n")

        insert_at = 1 if lines and lines[0].startswith("#!") else 0
        if insert_at < len(lines) and lines[insert_at].strip() == header:
            already += 1
            continue

        # Replace a stale header (wrong path) rather than stacking a second one.
        if insert_at < len(lines):
            candidate = lines[insert_at].strip()
            looks_like_header = (
                candidate.startswith("<!-- ") and candidate.endswith(" -->")
            ) or (
                candidate.startswith("# ")
                and candidate.endswith((".py", ".md", ".txt", ".toml", ".yml", ".spec"))
            )
            if looks_like_header:
                lines.pop(insert_at)

        lines.insert(insert_at, header)
        added.append(relative)

        if not dry_run:
            out = "\n".join(lines)
            path.write_bytes(out.replace("\n", "\r\n").encode("utf-8") if crlf
                             else out.encode("utf-8"))

    verb = "would add" if dry_run else "added"
    print(f"{verb} headers to {len(added)} file(s); {already} already correct, "
          f"{skipped} not comment-capable")
    for relative in added[:60]:
        print(f"    {relative}")
    if len(added) > 60:
        print(f"    ... and {len(added) - 60} more")
    if dry_run and added:
        print("\nRerun without --dry-run to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
