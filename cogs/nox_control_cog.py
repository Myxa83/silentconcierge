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

    @commands.command(name="noxreload")
    @commands.is_owner()
    async def nox_reload(self, ctx: commands.Context) -> None:
        """Reload the live NoxCat social cog from the currently deployed code."""
        if not self._right_guild(ctx):
            return

        try:
            if NOX_EXTENSION in self.bot.extensions:
                await self.bot.reload_extension(NOX_EXTENSION)
            else:
                await self.bot.load_extension(NOX_EXTENSION)
        except Exception as exc:
            await ctx.send(f"Nox reload failed: `{type(exc).__name__}: {exc}`")
            return

        await ctx.send("Nox mode reloaded.")

    @commands.command(name="noxstatus")
    @commands.is_owner()
    async def nox_status(self, ctx: commands.Context) -> None:
        """Show whether the NoxCat social cog is loaded."""
        if not self._right_guild(ctx):
            return

        enabled = NOX_EXTENSION in self.bot.extensions
        await ctx.send(f"Nox mode: **{'ON' if enabled else 'OFF'}**")

    @commands.command(name="noxai")
    @commands.is_owner()
    async def nox_ai(self, ctx: commands.Context) -> None:
        """Show AI wiring status without exposing the secret key."""
        if not self._right_guild(ctx):
            return

        cog = self.bot.get_cog("NoxCatCog")
        if cog is None:
            await ctx.send("Nox AI: **OFF** — NoxCatCog is not loaded.")
            return

        key_present = bool(getattr(cog, "api_key", ""))
        model = getattr(cog, "model", "unknown")
        rescue = self.bot.get_cog("NoxDirectRescueCog") is not None
        await ctx.send(
            "Nox AI diagnostics:\n"
            f"• cog: **ON**\n"
            f"• OPENAI_API_KEY: **{'SET' if key_present else 'MISSING'}**\n"
            f"• model: `{model}`\n"
            f"• direct-reply rescue: **{'ON' if rescue else 'OFF'}**"
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NoxControlCog(bot))
