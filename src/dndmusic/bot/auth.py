# src/dndmusic/bot/auth.py
"""Bot token resolution.

Order of preference:
    1. ``DISCORD_TOKEN`` in the environment (which includes a loaded .env)
    2. the remote auth server, when ``AUTH_SERVER_URL`` is configured
    3. nothing — the caller shows the first-run setup dialog
"""

from __future__ import annotations

import hashlib
import os
import platform
from typing import Optional

from ..config import AUTH_SERVER_URL, paths

try:  # pragma: no cover
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]
    REQUESTS_AVAILABLE = False


def load_dotenv_if_available() -> bool:
    """Populate os.environ from .env when python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False
    load_dotenv(dotenv_path=paths.env_file if paths.env_file.exists() else None)
    return True


def machine_fingerprint() -> str:
    raw = f"{platform.node()}-{platform.machine()}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def token_from_environment() -> Optional[str]:
    return os.getenv("DISCORD_TOKEN", "").strip() or None


def token_from_auth_server(url: str = AUTH_SERVER_URL, timeout: int = 10) -> Optional[str]:
    if not url or not REQUESTS_AVAILABLE:
        return None
    try:
        response = requests.post(
            f"{url}/api/token",
            json={"fingerprint": machine_fingerprint(), "secret": os.getenv("APP_SECRET", "")},
            timeout=timeout,
        )
        if response.status_code == 200:
            return response.json().get("token")
    except Exception as exc:
        print(f"  Auth server unavailable: {exc}")
    return None


def resolve_token(allow_remote: bool = True) -> Optional[str]:
    token = token_from_environment()
    if token:
        return token
    if allow_remote:
        return token_from_auth_server()
    return None


def write_env_token(token: str) -> None:
    """Persist the token to .env next to the app data and export it."""
    paths.env_file.write_text(f"DISCORD_TOKEN={token}\n", encoding="utf-8")
    os.environ["DISCORD_TOKEN"] = token
