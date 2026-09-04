# src/dndmusic/discord_api.py
"""Single import point for disnake.

Importing disnake from one place means the rest of the codebase never needs a
try/except, and the app still starts (UI-only) when the library is missing.
"""

from __future__ import annotations

from . import _ssl_compat

# aiohttp builds a default SSL context at import time, so this has to run before
# disnake is imported — see _ssl_compat for why.
_ssl_compat.install()

try:  # pragma: no cover - depends on the environment
    import disnake
    from disnake.ext import commands, tasks

    DISCORD_AVAILABLE = True
except ImportError:  # pragma: no cover
    disnake = None  # type: ignore[assignment]
    commands = None  # type: ignore[assignment]
    tasks = None  # type: ignore[assignment]
    DISCORD_AVAILABLE = False

#: Base classes that degrade to ``object`` when disnake is absent, so modules
#: that subclass them can still be imported for tests and tooling.
AudioSourceBase = disnake.AudioSource if DISCORD_AVAILABLE else object
CogBase = commands.Cog if DISCORD_AVAILABLE else object

INSTALL_HINT = 'pip install "disnake[voice]" dave.py'


def require_disnake() -> None:
    if not DISCORD_AVAILABLE:
        raise RuntimeError(f"disnake is not installed — run: {INSTALL_HINT}")


def opus_loaded() -> bool:
    return bool(DISCORD_AVAILABLE and disnake.opus.is_loaded())


def voice_encryption_available() -> bool:
    """PyNaCl, which disnake needs to encrypt the voice stream.

    disnake imports it lazily, so a missing PyNaCl only shows up when someone
    runs !join.  Reporting it at startup turns a confusing runtime error into a
    line in the banner.
    """
    try:
        import nacl.secret  # noqa: F401
    except Exception:
        return False
    return True