# -*- coding: utf-8 -*-
"""Safety net for direct human replies/mentions on the NoxCat server."""

from __future__ import annotations

import asyncio

import discord
from discord.ext import commands


TARGET_GUILD_ID = 1540407360198156429
TURQUOISE = 0x40E0D0
WAIT_SECONDS = 4.0


class NoxDirectRescueCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _reply_target_author_id(self, message: discord.Message) -> int | None:
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
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    async def _direct_to_me(self, message: discord.Message) -> bool:
        if not self.bot.user:
            return False

        uid = self.bot.user.id
        raw = message.content or ""
        if f"<@{uid}>" in raw or f"<@!{uid}>" in raw:
            return True

        return await self._reply_target_author_id(message) == uid

    async def _already_answered(self, message: discord.Message) -> bool:
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

                ref_id = getattr(item.reference, "message_id", None) if item.reference else None
                if ref_id == message.id:
                    return True

                delta = (item.created_at - message.created_at).total_seconds()
                if 0 <= delta <= WAIT_SECONDS + 3:
                    return True
        except (discord.Forbidden, discord.HTTPException):
            return False

        return False

    @staticmethod
    def _embed(title: str, text: str) -> discord.Embed:
        embed = discord.Embed(title=title, description=text, color=TURQUOISE)
        embed.set_footer(text="Тиха Затока")
        return embed

    @staticmethod
    def _failure_text(message: discord.Message, error: str) -> str:
        raw = (message.clean_content or "").strip().casefold()
        if "мовч" in raw:
            lead = "Не ігнорую вас, капітане."
        elif "що роб" in raw or "шо роб" in raw or "зо роб" in raw:
            lead = "Зараз намагаюся повернути собі нормальну мову, а не повторювати одну й ту саму дурницю."
        else:
            lead = "Я вас чую, капітане."
        return f"{lead} AI-відповідь зараз не пройшла, тому не буду прикидатися розумним заготовкою. Діагностика: `!noxai`."

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.guild.id != TARGET_GUILD_ID:
            return
        if message.author.bot:
            return

        nox_cog = self.bot.get_cog("NoxCatCog")
        if nox_cog is None:
            return

        if (message.content or "").casefold().startswith(
            ("!noxon", "!noxoff", "!noxstatus", "!noxreload", "!noxai")
        ):
            return

        if not await self._direct_to_me(message):
            return

        await asyncio.sleep(WAIT_SECONDS)
        if await self._already_answered(message):
            return

        generated = None
        try:
            generated = await nox_cog._ask_ai(message, "direct")
        except Exception as exc:
            print(f"[NOX_RESCUE][AI] {type(exc).__name__}: {exc}")

        if generated:
            title, text = generated
        else:
            title = "Silent Concierge"
            error = str(getattr(nox_cog, "last_ai_error", "unknown"))
            text = self._failure_text(message, error)

        try:
            await message.reply(
                embed=self._embed(title or "Silent Concierge", text),
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as exc:
            print(f"[NOX_RESCUE][SEND] {exc}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NoxDirectRescueCog(bot))
