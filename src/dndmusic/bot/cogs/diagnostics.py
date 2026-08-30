# src/dndmusic/bot/cogs/diagnostics.py
"""Diagnostic commands: debug log dump and status check."""

from __future__ import annotations

import io
from datetime import datetime

from ...discord_api import CogBase, commands, disnake
from ..client import BotContext

DM_CHAR_LIMIT = 1900


class DiagnosticsCog(CogBase):
    def __init__(self, bot, context: BotContext) -> None:
        self.bot = bot
        self.context = context

    @commands.command(name="debug")
    async def debug_dump(self, ctx) -> None:
        debug = self.context.debug
        try:
            dump = debug.dump()
            if len(dump) < DM_CHAR_LIMIT:
                await ctx.author.send(f"```\n{dump}\n```")
            else:
                buffer = io.BytesIO(dump.encode())
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                summary = (
                    f"**Debug — {len(debug.messages)} entries**\n```\n{debug.last(10)}\n```"
                )
                await ctx.author.send(summary, file=disnake.File(buffer, f"debug_{stamp}.txt"))
            await ctx.send("Debug log sent to DMs!")
        except Exception as exc:
            await ctx.send(f"Debug failed: {exc}")

    @commands.command(name="check")
    async def check(self, ctx) -> None:
        embed = disnake.Embed(title="D&D Music Manager v3", color=disnake.Color.blue())

        sessions = []
        for guild in self.bot.guilds:
            voice_client = guild.voice_client
            if voice_client and voice_client.is_connected():
                state = "Playing" if voice_client.is_playing() else "Idle"
                sessions.append(f"**{guild.name}** — #{voice_client.channel.name} ({state})")

        embed.add_field(
            name="Bot",
            value=f"{self.bot.user.name}\nServers: {len(self.bot.guilds)}",
            inline=False,
        )
        embed.add_field(name="Active Sessions", value="\n".join(sessions) or "None", inline=False)

        mixer = self.context.engine.diagnostics()
        if mixer.get("attached"):
            embed.add_field(
                name="Mixer",
                value=(
                    f"music: {mixer['music']} | ambient: {mixer['ambient']} | "
                    f"sfx: {mixer['sfx']}\nlevel: {mixer['level']:.2f} | "
                    f"frames mixed: {mixer['frames']}"
                ),
                inline=False,
            )
        else:
            embed.add_field(name="Mixer", value="Not attached", inline=False)

        await ctx.send(embed=embed)
