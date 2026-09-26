# -*- coding: utf-8 -*-
"""AI bridge: human asks Silent Concierge to ask NoxCat something."""

from __future__ import annotations

import json
import os
import random
import re
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord.ext import commands
from pymongo.errors import DuplicateKeyError

from data.mongo_store import get_database


TARGET_GUILD_ID = 1540407360198156429
CLAIM_COLLECTION = "nox_bridge_claims"
TURQUOISE = 0x40E0D0
OPENAI_URL = "https://api.openai.com/v1/responses"

NOX_NAME_MARKERS = (
    "noxcat", "nox cat", "нокс", "нокс кет", "нокс кэт",
)
ASK_PREFIXES = (
    "запитай", "спитай", "питай", "звернись до", "ask",
)

FALLBACK_QUESTIONS = (
    "Ноксе, як ви оцінюєте рівень сьогоднішнього хаосу на станції?",
    "Ноксе, що сьогодні небезпечніше: людська цікавість чи порожня миска?",
    "Ноксе, скільки здорового глузду ще залишилося на цій станції?",
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
        self.api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        self.model = (os.getenv("OPENAI_MODEL") or "gpt-5-mini").strip()
        try:
            get_database()[CLAIM_COLLECTION].create_index("expires_at", expireAfterSeconds=0)
        except Exception as exc:
            print(f"[NOX_BRIDGE][WARN] TTL index: {type(exc).__name__}: {exc}")
        print(
            f"[NOX_BRIDGE] loaded | guild={TARGET_GUILD_ID} | model={self.model} | "
            f"ai={'ON' if self.api_key else 'OFF'}"
        )

    def _claim_once(self, message_id: int) -> bool:
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
        return (
            any(prefix in low for prefix in ASK_PREFIXES)
            and any(marker in low for marker in NOX_NAME_MARKERS)
        )

    @staticmethod
    def _extract_request(text: str) -> str:
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
        return cleaned

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
    def _message_text(message: discord.Message) -> str:
        text = (message.clean_content or "").strip()
        if text:
            return text[:1000]
        for embed in message.embeds:
            bits = [embed.title or "", embed.description or ""]
            value = " | ".join(x for x in bits if x).strip()
            if value:
                return value[:1000]
        return ""

    async def _recent_context(self, message: discord.Message) -> str:
        lines: list[str] = []
        try:
            async for item in message.channel.history(limit=12, oldest_first=False):
                text = self._message_text(item)
                if not text:
                    continue
                who = getattr(item.author, "display_name", str(item.author))
                lines.append(f"{'BOT' if item.author.bot else 'USER'} | {who}: {text}")
            lines.reverse()
        except Exception as exc:
            print(f"[NOX_BRIDGE][HISTORY] {type(exc).__name__}: {exc}")
        return "\n".join(lines[-12:])

    async def _make_question(self, message: discord.Message) -> str:
        request = self._extract_request(message.clean_content)

        if not self.api_key:
            if _norm(request) in {"", "щось", "що-небудь", "що небудь", "something"}:
                return random.choice(FALLBACK_QUESTIONS)
            return f"Ноксе, {request}"

        context = await self._recent_context(message)
        prompt = f"""A human asked Silent Concierge to ask NoxCat something.
Human request after removing the words 'ask NoxCat': {request or '(nothing specific; invent something relevant)'}

Recent public channel context:
{context}

Write ONE natural question addressed to NoxCat.
Rules:
- Language should match the chat, normally Ukrainian.
- Start with “Ноксе,”.
- If the human supplied a real question/topic, preserve its meaning instead of inventing a different one.
- If they only said “щось” or gave no topic, invent a witty context-aware question.
- Silent Concierge is a dark gentleman-pirate spirit of Тиха Затока: intelligent, self-possessed, observant and not submissive.
- He has his own point of view and may choose a sharper or more interesting angle instead of mechanically repeating the human request.
- Nox is a shaggy kitten, little Devourer of the Void, affectionate flea-bag and concentrated universal hunger.
- Use dry dark humour when it fits, but never cruelty, humiliation or needless aggression.
- No profanity.
- One or two short sentences maximum.
- Return only the question text, no JSON, no quotes."""

        payload = {
            "model": self.model,
            "instructions": (
                "You write concise, intelligent, independent in-character Discord dialogue "
                "for Silent Concierge. Use context and subtext, avoid generic lines, and prefer "
                "dry dark humour over crude insults. Do not mention being an AI or explain reasoning."
            ),
            "input": prompt,
            "max_output_tokens": 120,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(OPENAI_URL, headers=headers, json=payload) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        print(f"[NOX_BRIDGE][AI] {resp.status}: {body[:400]}")
                        raise RuntimeError("AI request failed")
                    data = await resp.json()

            text = (data.get("output_text") or "").strip()
            if not text:
                for item in data.get("output", []):
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            text += part.get("text", "")
            text = text.strip().strip('"')
            if text:
                return text[:1800]
        except Exception as exc:
            print(f"[NOX_BRIDGE][AI] {type(exc).__name__}: {exc}")

        if _norm(request) in {"", "щось", "що-небудь", "що небудь", "something"}:
            return random.choice(FALLBACK_QUESTIONS)
        return f"Ноксе, {request}"

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
                description="Нокса зараз не бачу серед учасників, тож покликати його не можу.",
                color=TURQUOISE,
            )
            embed.set_footer(text="Тиха Затока")
            await message.channel.send(embed=embed)
            return

        question = await self._make_question(message)
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
