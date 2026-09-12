# -*- coding: utf-8 -*-
"""Owner-only emergency controls for the NoxCat social cog."""

from __future__ import annotations

import discord
from discord.ext import commands


TARGET_GUILD_ID = 1540407360198156429
NOX_EXTENSION = "cogs.noxcat_cog"


class NoxControlCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _right_guild(self, ctx: commands.Context) -> bool:
        return bool(ctx.guild and ctx.guild.id == TARGET_GUILD_ID)

    @commands.command(name="noxon")
    @commands.is_owner()
    async def nox_on(self, ctx: commands.Context) -> None:
        """Enable NoxCat social behaviour on the target guild."""
        if not self._right_guild(ctx):
            return

        if NOX_EXTENSION in self.bot.extensions:
            await ctx.send("Nox mode is already ON.")
            return

        try:
            await self.bot.load_extension(NOX_EXTENSION)
        except commands.ExtensionAlreadyLoaded:
            await ctx.send("Nox mode is already ON.")
            return
        except Exception as exc:
            await ctx.send(f"Failed to enable Nox mode: `{type(exc).__name__}: {exc}`")
            return

        await ctx.send("Nox mode ON. The dark spirit of Silent Cove is awake.")

    @commands.command(name="noxoff")
    @commands.is_owner()
    async def nox_off(self, ctx: commands.Context) -> None:
        """Emergency stop: unload the NoxCat social cog immediately."""
        if not self._right_guild(ctx):
            return

        if NOX_EXTENSION not in self.bot.extensions:
            await ctx.send("Nox mode is already OFF.")
            return

        try:
            await self.bot.unload_extension(NOX_EXTENSION)
        except Exception as exc:
            await ctx.send(f"Failed to disable Nox mode: `{type(exc).__name__}: {exc}`")
            return

        await ctx.send("Nox mode OFF. Emergency silence engaged.")

    @commands.command(name="noxstatus")
    @commands.is_owner()
    async def nox_status(self, ctx: commands.Context) -> None:
        """Show whether the NoxCat social cog is loaded."""
        if not self._right_guild(ctx):
            return

        enabled = NOX_EXTENSION in self.bot.extensions
        await ctx.send(f"Nox mode: **{'ON' if enabled else 'OFF'}**")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NoxControlCog(bot))
