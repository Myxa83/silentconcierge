# -*- coding: utf-8 -*-
"""Bridge human requests like 'запитай NoxCat щось' into a real @NoxCat mention."""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from pymongo.errors import DuplicateKeyError

from data.mongo_store import get_database


TARGET_GUILD_ID = 1540407360198156429
CLAIM_COLLECTION = "nox_bridge_claims"
TURQUOISE = 0x40E0D0

NOX_NAME_MARKERS = (
    "noxcat",
    "nox cat",
    "нокс",
    "нокс кет",
    "нокс кэт",
)

ASK_PREFIXES = (
    "запитай",
    "спитай",
    "питай",
    "звернись до",
    "ask",
)

RANDOM_QUESTIONS = (
    "Ноксе, як ви оцінюєте рівень сьогоднішнього хаосу на станції за шкалою від одного до неминучих наслідків?",
    "Ноксе, як маленький пожирач Пустки, дайте професійну оцінку: що сьогодні небезпечніше, людська цікавість чи порожня миска?",
    "Ноксе, питання від Тихої Затоки: скільки здорового глузду ще залишилося на цій станції?",
    "Ноксе, що ви оберете: ще одну таємницю Всесвіту чи ще одну тарілку? Відповідайте обережно, Даністіан може почути.",
    "Ноксе, як там Пустка? Не з'їли ще все без нас?",
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").casefold()).strip()


def _is_nox_name(name: str) -> bool:
    low = _norm(name)
    return any(marker == low or marker in low for marker in NOX_NAME_MARKERS)


class NoxBridgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        try:
            get_database()[CLAIM_COLLECTION].create_index(
                "expires_at", expireAfterSeconds=0
            )
        except Exception as exc:
            print(f"[NOX_BRIDGE][WARN] TTL index: {type(exc).__name__}: {exc}")
        print(f"[NOX_BRIDGE] loaded | guild={TARGET_GUILD_ID}")

    def _claim_once(self, message_id: int) -> bool:
        """Cross-process dedupe, so multiple Render workers cannot ask 2-3 times."""
        try:
            get_database()[CLAIM_COLLECTION].insert_one({
                "_id": str(message_id),
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=2),
            })
            return True
        except DuplicateKeyError:
            return False
        except Exception as exc:
            print(f"[NOX_BRIDGE][WARN] claim failed: {type(exc).__name__}: {exc}")
            return True

    @staticmethod
    def _looks_like_ask_request(text: str) -> bool:
        low = _norm(text)
        has_ask = any(prefix in low for prefix in ASK_PREFIXES)
        has_nox = any(marker in low for marker in NOX_NAME_MARKERS)
        return has_ask and has_nox

    @staticmethod
    def _extract_question(text: str) -> str:
        cleaned = text.strip()
        low = _norm(cleaned)

        for prefix in ASK_PREFIXES:
            if low.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip(" ,:.-")
                break

        cleaned = re.sub(
            r"(?i)\b(?:NoxCat|Nox\s+Cat|Нокс(?:\s+Кет|\s+Кэт)?|Нокса)\b",
            "",
            cleaned,
            count=1,
        ).strip(" ,:.-")

        if _norm(cleaned) in {"", "щось", "що-небудь", "що небудь", "something"}:
            return random.choice(RANDOM_QUESTIONS)

        return f"Ноксе, {cleaned}"

    @staticmethod
    def _find_nox(guild: discord.Guild) -> discord.Member | None:
        for member in guild.members:
            if not member.bot:
                continue
            names = (
                getattr(member, "name", ""),
                getattr(member, "display_name", ""),
                getattr(member, "global_name", "") or "",
            )
            if any(_is_nox_name(name) for name in names):
                return member
        return None

    @staticmethod
    def _embed(question: str) -> discord.Embed:
        embed = discord.Embed(
            title="Silent Concierge → NoxCat",
            description=question,
            color=TURQUOISE,
        )
        embed.set_footer(text="Тиха Затока")
        return embed

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.guild.id != TARGET_GUILD_ID:
            return
        if message.author.bot or not message.content:
            return
        if not self._looks_like_ask_request(message.clean_content):
            return
        if not self._claim_once(message.id):
            return

        nox = self._find_nox(message.guild)
        if nox is None:
            embed = discord.Embed(
                title="Silent Concierge",
                description="Нокса бачу лише в легендах, але не в списку учасників. Не можу його покликати.",
                color=TURQUOISE,
            )
            await message.channel.send(embed=embed)
            return

        question = self._extract_question(message.clean_content)

        # The mention stays in normal message content because mentions inside an
        # embed do not reliably notify another bot. The actual text is in the
        # turquoise embed.
        await message.channel.send(
            content=nox.mention,
            embed=self._embed(question),
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=[nox],
                replied_user=False,
            ),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NoxBridgeCog(bot))
