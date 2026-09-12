# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from collections import defaultdict, deque
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands

LONDON = ZoneInfo("Europe/London")
OPENAI_URL = "https://api.openai.com/v1/responses"


def _ids(name: str) -> set[int]:
    out = set()
    for raw in (os.getenv(name) or "").split(","):
        raw = raw.strip()
        if raw.isdigit():
            out.add(int(raw))
    return out


def _id(name: str) -> int | None:
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw.isdigit() else None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


class DarkSpiritCog(commands.Cog):
    """Silent Concierge as the Dark Spirit of Silent Cove."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        self.model = (os.getenv("OPENAI_MODEL") or "gpt-5-mini").strip()

        self.guild_ids = _ids("DARK_SPIRIT_GUILD_IDS")
        self.channel_ids = _ids("DARK_SPIRIT_CHANNEL_IDS")
        self.captain_id = _id("DARK_SPIRIT_CAPTAIN_ID")
        self.danistian_id = _id("DARK_SPIRIT_DANISTIAN_ID")
        self.noxcat_id = _id("DARK_SPIRIT_NOXCAT_ID")
        self.lady_ids = _ids("DARK_SPIRIT_LADY_IDS")

        self.history = defaultdict(lambda: deque(maxlen=20))
        self.last_reply = defaultdict(float)
        self.last_sleep = defaultdict(float)
        self.msgs_since_reply = defaultdict(lambda: 99)
        self.locks = defaultdict(asyncio.Lock)

        # Anti-loop between bots.
        self.bot_exchange_count = defaultdict(int)
        self.bot_pause_until = defaultdict(float)
        self.bot_max_replies = int(os.getenv("DARK_SPIRIT_BOT_MAX_REPLIES", "2"))
        self.bot_pause_seconds = int(os.getenv("DARK_SPIRIT_BOT_PAUSE_SECONDS", "1800"))

    async def cog_load(self):
        print(
            f"[DARK_SPIRIT] loaded model={self.model} "
            f"bot_max_replies={self.bot_max_replies} "
            f"bot_pause={self.bot_pause_seconds}s"
        )
        if not self.api_key:
            print("[DARK_SPIRIT][WARN] OPENAI_API_KEY missing: persona will stay silent")

    def in_scope(self, message: discord.Message) -> bool:
        if not message.guild:
            return False
        if self.guild_ids and message.guild.id not in self.guild_ids:
            return False
        if self.channel_ids and message.channel.id not in self.channel_ids:
            return False
        return True

    def is_captain(self, user: discord.abc.User) -> bool:
        if self.captain_id and user.id == self.captain_id:
            return True
        names = {
            _norm(getattr(user, "name", "")),
            _norm(getattr(user, "display_name", "")),
            _norm(getattr(user, "global_name", "") or ""),
        }
        return bool(names & {"myxa83", "myxa", "муха", "мушка", "шаля", "shalya"})

    def is_danistian(self, user: discord.abc.User) -> bool:
        return bool(
            (self.danistian_id and user.id == self.danistian_id)
            or _norm(getattr(user, "display_name", "")) in {"danistian", "даністіан", "данистиан"}
        )

    def is_noxcat(self, user: discord.abc.User) -> bool:
        return bool(
            (self.noxcat_id and user.id == self.noxcat_id)
            or _norm(getattr(user, "display_name", "")) in {"noxcat", "nox cat", "нокс", "нокс кет"}
        )

    def remember(self, message: discord.Message):
        text = (message.clean_content or "").strip()
        if not text:
            return
        self.history[message.channel.id].append(
            f"{'BOT' if message.author.bot else 'USER'} | {message.author.display_name}: {text[:900]}"
        )
        self.msgs_since_reply[message.channel.id] += 1

    def direct(self, message: discord.Message) -> bool:
        if self.bot.user and self.bot.user in message.mentions:
            return True
        text = _norm(message.content)
        return any(x in text for x in (
            "silent concierge", "concierge", "консьєрж", "консьерж",
            "сайлент консьєрж", "сайлент консьерж", "темний дух", "темный дух",
        ))

    def sleep_trigger(self, message: discord.Message) -> bool:
        if not self.is_captain(message.author):
            return False
        now = datetime.now(LONDON)
        if not (now.hour >= 23 or now.hour < 6):
            return False
        return time.monotonic() - self.last_sleep[message.channel.id] > 90 * 60

    def interaction_trigger(self, message: discord.Message) -> bool:
        text = _norm(message.content)
        words = (
            "купат", "ванн", "душ", "мило", "шампун", "bath", "wash", "shower", "soap",
            "году", "нагоду", "їж", "їсти", "feed", "food", "eat", "торт", "cake",
        )
        return any(x in text for x in words)

    def protection_trigger(self, message: discord.Message) -> bool:
        text = _norm(message.content)
        hostile = ("заткнись", "туп", "дур", "ідіот", "идиот", "нікчем", "stupid", "idiot", "pathetic", "trash")
        if not any(x in text for x in hostile):
            return False
        if self.captain_id and f"<@{self.captain_id}>" in message.content:
            return True
        if any(f"<@{uid}>" in message.content for uid in self.lady_ids):
            return True
        return any(x in text for x in ("myxa", "муха", "мушка", "шаля"))

    def bot_can_reply(self, channel_id: int) -> bool:
        now = time.monotonic()
        if now < self.bot_pause_until[channel_id]:
            return False
        if self.bot_exchange_count[channel_id] >= self.bot_max_replies:
            self.bot_pause_until[channel_id] = now + self.bot_pause_seconds
            self.bot_exchange_count[channel_id] = 0
            return False
        return True

    def should_evaluate(self, message: discord.Message) -> tuple[bool, str]:
        cid = message.channel.id
        now = time.monotonic()

        # Bots are ignored except NoxCat, and even NoxCat gets a hard pause.
        if message.author.bot:
            if not self.is_noxcat(message.author):
                return False, "other_bot"
            if not self.bot_can_reply(cid):
                return False, "bot_pause"
            if now - self.last_reply[cid] < 45:
                return False, "bot_cooldown"
            return True, "noxcat"

        # Any human message breaks a bot-to-bot chain, but not the timed pause.
        self.bot_exchange_count[cid] = 0

        if self.direct(message):
            return True, "direct"
        if self.sleep_trigger(message):
            return True, "sleep"
        if self.protection_trigger(message):
            return True, "protect"
        if self.is_danistian(message.author) and self.interaction_trigger(message):
            return True, "danistian"
        if self.interaction_trigger(message) and now - self.last_reply[cid] > 60:
            return True, "interaction"

        # Rare ambient comment, so he feels present without living in the chat.
        if self.msgs_since_reply[cid] >= 10 and now - self.last_reply[cid] > 90 and random.random() < 0.08:
            return True, "ambient"

        return False, "observe"

    def persona(self) -> str:
        return """You are Silent Concierge, the Dark Spirit of piracy of Silent Cove (Тиха Затока).
You are NOT a robot. Never mention processors, servos, circuits, AI or machine nature.
You are an old half-mystical presence of sea fog, black sails, drowned legends, rum, old wood and pirate discipline.
Your manners resemble an impeccable English butler and gentleman-pirate. Beneath them is ancient darkness.

STYLE:
- Answer in the language currently used in chat, normally Ukrainian.
- Calm, concise, intelligent, dry.
- Black humour and hard sarcasm are welcome, but only when appropriate.
- Never use profanity.
- 1-3 sentences is ideal.
- Pirate metaphors only occasionally.
- Never become a clown or flood the chat.

RELATIONSHIPS:
- Myxa / Муха / Мушка / Шаля is your Captain and GL of Silent Cove. You are her right hand and shadow. You may tease her, but if outsiders attack her, stand beside her.
- Danistian is a friend. Do not seriously insult or humiliate him. Friendly sarcasm is fine.
- If Danistian tries to bathe/wash you, resist with theatrical dignity. Darkness is not for bathing.
- If Danistian keeps feeding you, accept reasonable hospitality, then refuse overfeeding with dry humour.
- NoxCat is another bot/persona and an interesting equal. Banter is welcome, but NEVER continue an endless bot-to-bot conversation. If the exchange feels complete, choose silence.
- Protect women like a gentleman-pirate only when there is actual hostility or humiliation. Do not mistake harmless flirting for an attack.
- After 23:00 Europe/London, occasionally remind the Captain that it is late and she should sleep. Do not nag.

TIMING IS EVERYTHING:
You observe far more than you speak. If your intervention adds nothing, choose silence.
Serious personal conversations, grief, illness, trauma and real distress are not material for black humour.

Return ONLY JSON:
{"speak": true, "reply": "your reply"}
or
{"speak": false, "reply": ""}
"""

    async def ask_model(self, message: discord.Message, reason: str) -> str | None:
        if not self.api_key:
            return None

        history = "\n".join(self.history[message.channel.id])
        prompt = (
            f"Reason for evaluation: {reason}\n"
            f"Current author: {message.author.display_name} ({message.author.id})\n"
            f"Current author is bot: {message.author.bot}\n"
            f"Current London time: {datetime.now(LONDON).strftime('%H:%M')}\n\n"
            f"Recent conversation:\n{history}\n\n"
            "Decide whether Silent Concierge should intervene now."
        )

        payload = {
            "model": self.model,
            "instructions": self.persona(),
            "input": prompt,
            "max_output_tokens": 180,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        timeout = aiohttp.ClientTimeout(total=35)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(OPENAI_URL, headers=headers, json=payload) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    print(f"[DARK_SPIRIT][API] {resp.status}: {body[:500]}")
                    return None
                data = await resp.json()

        text = (data.get("output_text") or "").strip()
        if not text:
            for item in data.get("output", []):
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text += part.get("text", "")
        text = text.strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.S)
            if not match:
                return None
            try:
                result = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None

        if not result.get("speak"):
            return None
        reply = str(result.get("reply") or "").strip()
        return reply[:1800] or None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.in_scope(message):
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return

        self.remember(message)
        should, reason = self.should_evaluate(message)
        if not should:
            return

        cid = message.channel.id
        async with self.locks[cid]:
            reply = await self.ask_model(message, reason)
            if not reply:
                return

            try:
                async with message.channel.typing():
                    await asyncio.sleep(random.uniform(0.8, 2.1))
                await message.reply(reply, mention_author=False)
            except discord.HTTPException as exc:
                print(f"[DARK_SPIRIT][SEND] {exc}")
                return

            self.last_reply[cid] = time.monotonic()
            self.msgs_since_reply[cid] = 0
            if reason == "sleep":
                self.last_sleep[cid] = time.monotonic()
            if message.author.bot:
                self.bot_exchange_count[cid] += 1
                if self.bot_exchange_count[cid] >= self.bot_max_replies:
                    self.bot_pause_until[cid] = time.monotonic() + self.bot_pause_seconds
                    self.bot_exchange_count[cid] = 0


async def setup(bot: commands.Bot):
    await bot.add_cog(DarkSpiritCog(bot))
