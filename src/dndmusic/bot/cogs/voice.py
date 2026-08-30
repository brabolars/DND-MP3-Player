# src/dndmusic/bot/cogs/voice.py
"""Voice channel commands: join / leave."""

from __future__ import annotations

import asyncio

from ...discord_api import CogBase, commands
from ..client import BotContext

CONNECT_TIMEOUT = 30.0
STABILISE_ATTEMPTS = 10


class VoiceCog(CogBase):
    def __init__(self, bot, context: BotContext) -> None:
        self.bot = bot
        self.context = context

    @property
    def engine(self):
        return self.context.engine

    @property
    def debug(self):
        return self.context.debug

    @commands.command(name="join")
    async def join(self, ctx) -> None:
        if not ctx.author.voice:
            await ctx.send("You need to be in a voice channel!")
            return

        try:
            if ctx.voice_client:
                self.debug.log("Disconnecting existing voice client first", "BOT")
                await ctx.voice_client.disconnect(force=True)
                self.engine.detach_voice_client()
                await asyncio.sleep(1.0)

            channel = ctx.author.voice.channel
            self.debug.log(f"Connecting to #{channel.name}...", "BOT")
            voice_client = await channel.connect(timeout=CONNECT_TIMEOUT, reconnect=True)
            self.engine.attach_voice_client(voice_client)

            # The DAVE handshake can take a few seconds — poll instead of assuming.
            connected = False
            for attempt in range(STABILISE_ATTEMPTS):
                await asyncio.sleep(1.0)
                if voice_client.is_connected():
                    connected = True
                    break
                self.debug.log(
                    f"Waiting for connection... attempt {attempt + 1}/{STABILISE_ATTEMPTS}", "BOT"
                )

            if connected:
                await ctx.send(f"Joined **#{channel.name}**!")
                self.context.on_status(f"Ready in #{channel.name}")
                self.debug.log(f"Fully connected to #{channel.name}", "BOT")
            else:
                self.debug.log("Connection didn't stabilize", "ERR")
                await ctx.send(
                    "Joined but the connection is unstable — try `!leave` then `!join` again."
                )
                self.context.on_status(f"Unstable in #{channel.name}")

        except asyncio.TimeoutError:
            await ctx.send("Connection timed out — try again.")
            self.debug.log("Voice connection timed out", "ERR")
            self.engine.detach_voice_client()
        except Exception as exc:
            await ctx.send(f"Error: {exc}")
            self.debug.log(f"Join error: {exc}", "ERR")
            self.engine.detach_voice_client()

    @commands.command(name="leave")
    async def leave(self, ctx) -> None:
        if not ctx.voice_client:
            await ctx.send("I'm not in a voice channel!")
            return
        await ctx.voice_client.disconnect()
        self.engine.detach_voice_client()
        await ctx.send("Left voice channel.")
        self.context.on_status(f"Online — {self.bot.user.name} — Use !join")
