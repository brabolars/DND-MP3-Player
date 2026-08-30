# src/dndmusic/bot/__init__.py
"""Discord side: token resolution, bot lifecycle and command cogs."""

from .client import BotContext, BotRunner

__all__ = ["BotContext", "BotRunner"]
