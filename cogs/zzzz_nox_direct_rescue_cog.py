# -*- coding: utf-8 -*-
"""Safety net for direct human replies/mentions on the NoxCat server.

This cog must never generate/send a second independent AI reply.
It only retries through NoxCatCog._reply_ai(), which has global reply claims.
"""

from __future__ import annotations

import asyncio

import discord
from discord.ext import commands


TARGET_GUILD_ID = 1540407360198156429
WAIT_SECONDS = 6.0


class NoxDirectRescueCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _reply_target_author_id(
        self,
        message: discord.Message,
    ) -> int | None:
        if not message.reference:
            return None

        resolved = message.reference.resolved
        if isinstance(resolved, discord.Message):
            return resolved.author.id

        cached = getattr(message.reference, "cached_message", None)
        if isinstance(cached, discord.Message):
            return cached.author.id

        message_id = getattr(message.reference, "message_id", None)
        if not message_id:
            return None

        try:
            referenced = await message.channel.fetch_message(message_id)
            return referenced.author.id
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            return None

    async def _direct_to_me(
        self,
        message: discord.Message,
    ) -> bool:
        if not self.bot.user:
            return False

        uid = self.bot.user.id
        raw = message.content or ""
        if f"<@{uid}>" in raw or f"<@!{uid}>" in raw:
            return True

        return (
            await self._reply_target_author_id(message)
            == uid
        )

    async def _already_answered(
        self,
        message: discord.Message,
    ) -> bool:
        if not self.bot.user:
            return False

        try:
            async for item in message.channel.history(
                limit=12,
                after=message.created_at,
                oldest_first=True,
            ):
                if item.author.id != self.bot.user.id:
                    continue

                ref_id = (
                    getattr(item.reference, "message_id", None)
                    if item.reference
                    else None
                )
                if ref_id == message.id:
                    return True
        except (discord.Forbidden, discord.HTTPException):
            return False

        return False

    @commands.Cog.listener()
    async def on_message(
        self,
        message: discord.Message,
    ) -> None:
        if (
            not message.guild
            or message.guild.id != TARGET_GUILD_ID
        ):
            return
        if message.author.bot:
            return

        if (message.content or "").casefold().startswith(
            (
                "!noxon",
                "!noxoff",
                "!noxstatus",
                "!noxreload",
                "!noxai",
            )
        ):
            return

        if not await self._direct_to_me(message):
            return

        nox_cog = self.bot.get_cog("NoxCatCog")
        if nox_cog is None:
            return

        await asyncio.sleep(WAIT_SECONDS)

        if await self._already_answered(message):
            return

        # Important: use the canonical pipeline.
        # _reply_ai() owns typing, style and global one-reply claim.
        try:
            await nox_cog._reply_ai(
                message,
                "direct",
            )
        except Exception as exc:
            print(
                f"[NOX_RESCUE] "
                f"{type(exc).__name__}: {exc}"
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NoxDirectRescueCog(bot))
