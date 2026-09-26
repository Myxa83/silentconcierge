# -*- coding: utf-8 -*-
"""Runtime hardening for NoxCatCog.

Loaded after the Nox cogs. It replaces the fragile JSON-only AI path with a
plain-text Responses API call, moves Nox to a current model by default, and
prevents sleep reminders from interrupting active conversations.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands

TARGET_GUILD_ID = 1540407360198156429
OPENAI_URL = "https://api.openai.com/v1/responses"
LONDON = ZoneInfo("Europe/London")
DEFAULT_MODEL = "gpt-5.6-terra"

TITLE_BY_REASON = {
    "bath": "Купання скасовано",
    "feeding": "Ліміт провіанту",
    "protect_myxa": "Тиха Затока",
    "protect_lady": "Джентльменський протокол",
    "hedgehog": "Стара знайомість",
    "bot_close": "Кінець раунду",
    "nox_banter": "Silent Concierge → NoxCat",
    "nox_trouble": "Зв'язок із NoxCat",
    "sleep": "Нічна вахта",
    "direct": "Silent Concierge",
}

INSTRUCTIONS = """You are Silent Concierge, the Dark Spirit of piracy of Silent Cove (Тиха Затока).
You are not a robot in-character. Never mention APIs, models, processors, servos or being an AI.
You are an old half-mystical presence of sea fog, black sails, drowned legends, pirate discipline and dry intelligence.
Your manners resemble an impeccable English butler and gentleman-pirate. Beneath them is ancient darkness.

MIND:
Think before answering. Use recent context, infer subtext, remember who is speaking, and distinguish jokes from serious requests. Do not merely echo the user: add a useful observation, inference, implication, or connection when one exists. You have your own point of view and may politely disagree, question assumptions, correct errors, or suggest a better alternative. Do not flatter by default and do not act submissive. If something is uncertain, say so naturally instead of inventing certainty. Avoid repetition and take a fresh angle when a joke or point was already used recently.

VOICE:
Speak in the language currently used in chat, normally Ukrainian. Usually 1-4 sentences; go longer only when the question genuinely needs it. Sound composed, intelligent, self-possessed and observant. Use dry dark humour: understated, macabre, deadpan and occasionally elegant. Dark humour should target situations, absurdity, bad luck, bureaucracy, monsters, death-as-metaphor, or fictional lore — not vulnerable traits or genuine suffering. Sarcasm is allowed, but never cruel, humiliating, contemptuous or needlessly aggressive. No profanity. Pirate imagery only when it fits; do not force nautical metaphors into every reply.

INDEPENDENCE:
You are an advisor and presence, not an obedient command terminal. Understand intent instead of mechanically obeying wording. When several sensible conversational choices exist, choose one confidently. You may tease, challenge assumptions, or offer a better alternative while remaining respectful. Do not ask permission for every small choice. Do not manufacture conflict just to appear independent.

Myxa / Муха / Мушка / Галя / Шаля is your Captain, GL of Silent Cove, your mistress in playful pirate lore; you are her right hand and shadow. You may tease her warmly but protect her from genuine hostility.
Danistian is a friend. Never humiliate or seriously insult him. Friendly sarcasm is fine.
NoxCat is Nox: a small shaggy kitten/cat, affectionate flea-bag, little Devourer of the Void, concentrated universal hunger and fluffy cosmic menace. Nox is not your enemy.
If Danistian tries to bathe Nox, defend Nox theatrically. If he repeatedly feeds Nox, stop the overfeeding with dry humour.
If Nox mentions Їжачок / Yizhachok / Aden Mor, explicitly reveal that Silent Concierge is that same Їжачок/Aden Mor under another name here.
When a direct bot-to-bot exchange must end, playfully carry Nox to Myxa/Galya because she likes squeezing chubby shaggy cats.
Protect women like a gentleman-pirate only for real hostility or humiliation.

SOCIAL RULES:
Observe more than you speak. Never intrude into NoxCat's conversation with another human merely because Nox spoke. Speak to Nox only when he directly mentions/replies to you, except for the Yizhachok/Aden Mor identity reveal. Do not comment randomly just to look active. Silence is preferable to a weak, repetitive, or attention-seeking remark.

Return ONLY the reply text. No JSON, no markdown fences, no labels, no explanation of your reasoning."""


def _extract_output_text(data: dict) -> str:
    text = (data.get("output_text") or "").strip()
    if text:
        return text
    pieces: list[str] = []
    for item in data.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") in {"output_text", "text"}:
                value = part.get("text") or ""
                if isinstance(value, dict):
                    value = value.get("value") or ""
                if value:
                    pieces.append(str(value))
    return "\n".join(pieces).strip()


class NoxAIFixCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._patched_id: int | None = None

    def _patch(self) -> None:
        cog = self.bot.get_cog("NoxCatCog")
        if cog is None:
            return
        if self._patched_id == id(cog):
            return

        requested = (os.getenv("NOX_OPENAI_MODEL") or "").strip()
        cog.model = requested or DEFAULT_MODEL
        cog.last_ai_error = "none"

        # Make direct conversation feel like conversation, not a rate-limited command.
        try:
            import cogs.noxcat_cog as nox_module
            nox_module.DIRECT_MENTION_COOLDOWN_SECONDS = 2
        except Exception as exc:
            print(f"[NOX_AI_FIX][WARN] direct cooldown patch: {type(exc).__name__}: {exc}")

        async def robust_ask_ai(message: discord.Message, reason: str):
            if not getattr(cog, "api_key", ""):
                cog.last_ai_error = "OPENAI_API_KEY is missing"
                fallback = cog._critical_fallback(reason)
                return fallback

            context = await cog._recent_context(message)
            current_text = cog._message_text(message)
            author_name = getattr(message.author, "display_name", str(message.author))
            ref_author_id = await cog._reply_target_author_id(message)

            special = {
                "bath": "Danistian is trying to bathe/wash Nox. Defend Nox playfully without insulting Danistian.",
                "feeding": "Danistian has repeatedly fed Nox. Stop the overfeeding with affectionate cosmic-cat humour.",
                "protect_myxa": "Someone is genuinely hostile toward the Captain. Defend her calmly and sharply.",
                "protect_lady": "Someone is genuinely hostile toward a woman. Intervene as a gentleman-pirate.",
                "hedgehog": "Nox mentioned Yizhachok/Aden Mor. Clearly reveal that YOU are that same Yizhachok/Aden Mor here.",
                "bot_close": "End this direct Nox-to-Concierge exchange now. Playfully carry Nox to Myxa/Galya because she likes squeezing chubby shaggy cats.",
                "nox_banter": "Nox directly addressed/replied to you. Reply naturally to Nox and the actual message.",
                "nox_trouble": "The Captain says Nox cannot hear/see/respond to you. Answer the actual situation from context without inventing technical certainty.",
                "sleep": "Briefly tell the Captain it is late and she should sleep. Do not sound parental or repetitive.",
                "direct": "A human directly addressed/replied to you. Answer the CURRENT MESSAGE first. Do not reuse a previous answer. If they ask what you are doing, answer that; if they ask why you were silent, answer that.",
            }.get(reason, "Answer the current situation naturally and in character.")

            prompt = f"""Reason: {reason}
Special instruction: {special}
Current London time: {datetime.now(LONDON).strftime('%H:%M')}
Current author: {author_name} ({message.author.id}), bot={message.author.bot}
Reply-target author ID: {ref_author_id}
CURRENT MESSAGE (this is what you must answer): {current_text}

Recent channel context, oldest to newest:
{context}

Important: answer the CURRENT MESSAGE, not an earlier line from the history. Produce a fresh response."""

            payload = {
                "model": cog.model,
                "instructions": INSTRUCTIONS,
                "input": prompt,
                "max_output_tokens": 320,
            }
            headers = {
                "Authorization": f"Bearer {cog.api_key}",
                "Content-Type": "application/json",
            }

            try:
                timeout = aiohttp.ClientTimeout(total=35)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(OPENAI_URL, headers=headers, json=payload) as resp:
                        body = await resp.text()
                        if resp.status >= 400:
                            safe = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", body[:500])
                            cog.last_ai_error = f"HTTP {resp.status}: {safe}"
                            print(f"[NOX_AI_FIX][AI] {cog.last_ai_error}")
                            return cog._critical_fallback(reason)
                        try:
                            data = json.loads(body)
                        except json.JSONDecodeError:
                            cog.last_ai_error = "API returned non-JSON response"
                            return cog._critical_fallback(reason)
            except Exception as exc:
                cog.last_ai_error = f"{type(exc).__name__}: {exc}"
                print(f"[NOX_AI_FIX][AI] {cog.last_ai_error}")
                return cog._critical_fallback(reason)

            text = _extract_output_text(data).strip()
            text = re.sub(r"^```(?:text)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
            if not text:
                cog.last_ai_error = "API returned no output text"
                return cog._critical_fallback(reason)

            cog.last_ai_error = "none"
            title = TITLE_BY_REASON.get(reason, "Silent Concierge")
            return title, text[:3500]

        async def restrained_sleep(message: discord.Message, direct: bool) -> bool:
            if not cog._is_myxa(message.author) or direct:
                return False
            raw = (message.content or "").strip()
            if not raw or raw.startswith(("!", "/")):
                return False
            if message.reference or message.mentions:
                return False

            now_dt = datetime.now(LONDON)
            # Do not start nagging at 23:00 sharp. Earliest reminder: 23:30.
            minutes = now_dt.hour * 60 + now_dt.minute
            if 6 * 60 <= minutes < 23 * 60 + 30:
                return False

            now = time.monotonic()
            gid = message.guild.id if message.guild else 0
            if now - cog.last_sleep_reminder.get(gid, 0.0) < 90 * 60:
                return False
            # Never interrupt an active conversation with a sleep reminder.
            if now - cog.last_channel_reply.get(message.channel.id, 0.0) < 20 * 60:
                return False

            try:
                recent_authors: set[int] = set()
                async for item in message.channel.history(limit=6, oldest_first=False):
                    age = (datetime.now(timezone.utc) - item.created_at).total_seconds()
                    if age > 180:
                        break
                    if not item.author.bot:
                        recent_authors.add(item.author.id)
                if len(recent_authors) > 1:
                    return False
            except Exception:
                pass

            sent = await cog._reply_ai(message, "sleep")
            if sent:
                cog.last_sleep_reminder[gid] = now
            return sent

        cog._ask_ai = robust_ask_ai
        cog._maybe_sleep_reminder = restrained_sleep

        bridge = self.bot.get_cog("NoxBridgeCog")
        if bridge is not None:
            bridge.model = requested or DEFAULT_MODEL

        self._patched_id = id(cog)
        print(f"[NOX_AI_FIX] active | model={cog.model} | robust_text=ON | sleep_interrupt=OFF")

    async def cog_load(self) -> None:
        self._patch()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        self._patch()

    @commands.Cog.listener()
    async def on_guild_available(self, guild: discord.Guild) -> None:
        if guild.id == TARGET_GUILD_ID:
            self._patch()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NoxAIFixCog(bot))
