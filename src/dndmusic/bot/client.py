# src/dndmusic/bot/client.py
"""Bot construction and lifecycle (runs on its own thread)."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..config import COMMAND_PREFIX
from ..core.debug import DebugLogger
from ..core.library import MediaLibrary
from ..discord_api import DISCORD_AVAILABLE, commands, disnake, require_disnake
from ..engine.player import MusicEngine


def _noop(*_args, **_kwargs) -> None:
    return None


@dataclass
class BotContext:
    """Everything the cogs are allowed to touch, handed in explicitly."""

    engine: MusicEngine
    library: MediaLibrary
    debug: DebugLogger
    on_status: Callable[[str], None] = field(default=_noop)


class BotRunner:
    """Starts the bot in a daemon thread and exposes its event loop."""

    def __init__(self, token: str, context: BotContext, prefix: str = COMMAND_PREFIX) -> None:
        self.token = token
        self.context = context
        self.prefix = prefix
        self.bot = None
        self.ready = False
        self._thread: Optional[threading.Thread] = None

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        require_disnake()
        self.bot = self._build_bot()
        self._thread = threading.Thread(target=self._run, name="discord-bot", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.bot.run(self.token)
        except Exception as exc:
            self.context.debug.log(f"Bot run error: {exc}", "ERR")
            self.context.on_status(f"Error: {str(exc)[:40]}")

    def stop(self, timeout: float = 3.0) -> None:
        if not self.bot:
            return
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        try:
            voice_client = self.context.engine.voice_client
            if voice_client:
                asyncio.run_coroutine_threadsafe(
                    voice_client.disconnect(), loop
                ).result(timeout=timeout)
            asyncio.run_coroutine_threadsafe(self.bot.close(), loop).result(timeout=timeout)
        except Exception:
            pass

    # ── access ───────────────────────────────────────────────────────────

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return getattr(self.bot, "loop", None) if self.bot else None

    def run_coroutine(self, coro):
        loop = self.loop
        if loop is None or loop.is_closed():
            coro.close()
            return None
        return asyncio.run_coroutine_threadsafe(coro, loop)

    # ── construction ─────────────────────────────────────────────────────

    def _build_bot(self):
        intents = disnake.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        bot = commands.Bot(command_prefix=self.prefix, intents=intents)
        self._register_cogs(bot)

        context = self.context
        runner = self

        @bot.event
        async def on_ready():  # noqa: D401 - disnake callback
            runner.ready = True
            context.debug.log(f"Bot online as {bot.user}", "BOT")
            context.on_status(f"Online — {bot.user.name} — Use {runner.prefix}join")

        return bot

    def _register_cogs(self, bot) -> None:
        # Imported here so the module tree stays importable without disnake.
        from .cogs.diagnostics import DiagnosticsCog
        from .cogs.voice import VoiceCog

        bot.add_cog(VoiceCog(bot, self.context))
        bot.add_cog(DiagnosticsCog(bot, self.context))


def bot_available() -> bool:
    return DISCORD_AVAILABLE
