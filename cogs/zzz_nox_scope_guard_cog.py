# -*- coding: utf-8 -*-
"""Keep the legacy DarkSpiritCog away from the dedicated NoxCat server.

The Nox server is owned by cogs.noxcat_cog. This guard prevents the older
DarkSpiritCog from independently replying there and creating duplicate or
unsolicited dialogue.
"""

from __future__ import annotations

import discord
from discord.ext import commands


TARGET_GUILD_ID = 1540407360198156429


class NoxScopeGuardCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._patched_object_id: int | None = None

    def _patch_legacy_dark_spirit(self) -> None:
        cog = self.bot.get_cog("DarkSpiritCog")
        if cog is None:
            return

        object_id = id(cog)
        if self._patched_object_id == object_id:
            return

        original = cog.in_scope

        def guarded_in_scope(message: discord.Message) -> bool:
            if message.guild and message.guild.id == TARGET_GUILD_ID:
                return False
            return original(message)

        cog.in_scope = guarded_in_scope
        self._patched_object_id = object_id
        print(f"[NOX_GUARD] DarkSpiritCog excluded from guild {TARGET_GUILD_ID}")

    async def cog_load(self) -> None:
        self._patch_legacy_dark_spirit()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self._patch_legacy_dark_spirit()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NoxScopeGuardCog(bot))
