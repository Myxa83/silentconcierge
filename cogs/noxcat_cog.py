# -*- coding: utf-8 -*-
"""AI-driven Silent Concierge behaviour for the NoxCat server.

Silent Concierge observes the room, but does not join conversations merely
because NoxCat spoke. NoxCat dialogue is opt-in: Nox must directly mention or
reply to Concierge. The only lore exception is Yizhachok/Aden Mor.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
import discord
from discord.ext import commands
from pymongo.errors import DuplicateKeyError

from data.mongo_store import get_database


TARGET_GUILD_ID = 1540407360198156429
LONDON = ZoneInfo("Europe/London")
TURQUOISE = 0x40E0D0
OPENAI_URL = "https://api.openai.com/v1/responses"
CLAIM_COLLECTION = "noxcat_social_claims"
REPLY_CLAIM_COLLECTION = "noxcat_reply_claims"

CHANNEL_COOLDOWN_SECONDS = 45
DIRECT_MENTION_COOLDOWN_SECONDS = 12
BOT_MIN_GAP_SECONDS = 5
BOT_WINDOW_SECONDS = 12 * 60
BOT_MAX_REPLIES_BEFORE_CLOSING = 4
BOT_LOCK_SECONDS = 25 * 60
HEDGEHOG_IDENTITY_COOLDOWN_SECONDS = 60
SLEEP_REMINDER_GAP_SECONDS = 60 * 60
FEED_WINDOW_SECONDS = 20 * 60
FEED_WARNING_THRESHOLD = 3

DEFAULT_NOX_ALIASES = {
    "noxcat", "nox cat", "нокс", "нокс кет", "нокс кэт", "nox",
    "кошеня", "котик", "кіт", "блохастик", "пожирач пустки",
    "маленький пожирач пустки", "згусток всесвітнього голоду",
}
DEFAULT_MYXA_ALIASES = {
    "myxa83", "myxa", "муха", "мушка", "шаля", "shalya", "галя", "halyna",
}
DEFAULT_DANISTIAN_ALIASES = {"danistian", "даністіан", "данистиан"}

BATH_WORDS = {
    "купати", "купаю", "купання", "купатися", "ванна", "ванну", "душ",
    "мити", "помити", "шампунь", "мило", "губка",
    "bath", "bathe", "shower", "wash", "soap", "shampoo", "sponge",
}
FOOD_WORDS = {
    "годувати", "годує", "годуй", "нагодувати", "їсти", "їжа", "смаколик",
    "печиво", "торт", "пиріг", "цукерки", "feed", "food", "eat", "snack",
    "cake", "pie", "cookie", "treat",
}
HOSTILE_WORDS = {
    "заткнись", "замовкни", "тупа", "дурна", "ідіотка", "ненавиджу",
    "мерзота", "нікчемна", "жалюгідна", "безмозка", "сміття",
    "shut up", "stupid", "idiot", "hate you", "worthless", "pathetic",
    "trash", "moron", "dumb bitch",
}
LADY_WORDS = {
    "дівчина", "дівчину", "дівчат", "дівчата", "жінка", "жінку",
    "girl", "girls", "woman", "women", "lady", "ladies",
}
HEDGEHOG_WORDS = {
    "їжачок", "їжачка", "їжачку", "їжачком", "їжачки", "їжачків",
    "їжак", "їжака", "їжаку", "їжаком", "їжаче",
    "іжачок", "іжачка", "іжачку", "іжачком",
    "hedgehog", "yizhachok", "izhachok",
    "аден", "адене", "адена", "адену", "аденом", "аден мор",
    "aden", "adene", "aden mor",
}
CONCIERGE_WORDS = {
    "silent concierge", "concierge",
    "сайлент консьєрж", "сайлент консьерж",
    "консьєрж", "консьєрже", "консьєржа", "консьєржу", "консьєржем",
    "консьерж", "консьержа", "консьержу", "консьержем",
    "конс'єрж", "конс’єрж",
    "konsierzh", "konsyerzh", "konsierj", "konsyerj",
}
NOX_ASK_WORDS = {"запитай", "спитай", "питай", "звернись до", "ask"}
NOX_TROUBLE_WORDS = {
    "не чує", "не цює", "не бачить", "не реагує", "не відповідає",
    "не працює", "не робить", "doesn't hear", "does not hear",
    "doesn't see", "does not see", "doesn't respond", "does not respond",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").casefold()).strip()


def _contains_any(text: str, words: set[str]) -> bool:
    low = _norm(text)
    return any(word in low for word in words)


def _mentions_hedgehog(text: str) -> bool:
    low = _norm(text)
    if _contains_any(low, HEDGEHOG_WORDS):
        return True
    # Українські відмінки/словоформи: їжачок, їжачком, їжачка, їжачки...
    if re.search(r"\b[ії]жач[а-яіїєґ']*\b", low):
        return True
    # Aden / Аден, у тому числі звичайні відмінки та звертання.
    if re.search(r"\bаден(?:е|а|у|ом)?\b", low):
        return True
    return bool(re.search(r"\baden(?:e)?\b", low))


def _mentions_concierge(text: str) -> bool:
    """Розпізнає ім'я/роль Concierge у відмінках, мовах і частих написаннях."""
    low = _norm(text)
    if _contains_any(low, CONCIERGE_WORDS):
        return True

    # concierge / Silent Concierge / concierge's
    if re.search(r"\b(?:silent\s+)?concierge(?:['’]s|s)?\b", low):
        return True

    # консьєрж, консьерж, консьєрже, консьєржа, консьєржу, консьєржем...
    if re.search(r"\bконс[ь'’]?[єе]рж[а-яіїєґ'’]*\b", low):
        return True

    # поширена транслітерація
    return bool(
        re.search(
            r"\b(?:silent\s+)?kons(?:i|y)e?r(?:zh|j)[a-z]*\b",
            low,
        )
    )


def _calls_concierge(text: str) -> bool:
    return _mentions_hedgehog(text) or _mentions_concierge(text)


def _polish_concierge_text(text: str) -> str:
    """Фінальний стиль: без довгих тире, без зайвої театральності."""
    value = str(text or "").strip()
    value = value.replace("—", ", ")
    value = value.replace("–", "-")
    value = re.sub(r"\s+,\s+", ", ", value)
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip()


def _parse_id_set(env_name: str) -> set[int]:
    result: set[int] = set()
    for part in os.getenv(env_name, "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            print(f"[NOXCAT][WARN] invalid ID in {env_name}: {part!r}")
    return result


def _parse_aliases(env_name: str, defaults: set[str]) -> set[str]:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return set(defaults)
    return {_norm(x) for x in raw.split(",") if x.strip()}


class NoxCatCog(commands.Cog):
    """Dark Spirit of Silent Cove with contextual AI speech."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        self.model = (os.getenv("OPENAI_MODEL") or "gpt-5-mini").strip()

        self.myxa_user_ids = _parse_id_set("CONCIERGE_MYXA_IDS")
        self.lady_user_ids = _parse_id_set("CONCIERGE_LADY_IDS")
        self.nox_aliases = _parse_aliases("NOXCAT_BOT_ALIASES", DEFAULT_NOX_ALIASES)
        self.myxa_aliases = _parse_aliases("CONCIERGE_MYXA_ALIASES", DEFAULT_MYXA_ALIASES)
        self.danistian_aliases = _parse_aliases(
            "CONCIERGE_DANISTIAN_ALIASES", DEFAULT_DANISTIAN_ALIASES
        )

        self.last_channel_reply: dict[int, float] = {}
        self.last_sleep_reminder: dict[int, float] = {}
        self.feed_events: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self.bot_reply_times: dict[int, deque[float]] = defaultdict(deque)
        self.bot_locked_until: dict[int, float] = {}
        self.last_bot_reply: dict[int, float] = {}
        self.last_hedgehog_identity: dict[int, float] = {}
        self.local_history: dict[int, deque[str]] = defaultdict(lambda: deque(maxlen=24))
        self.ai_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

        try:
            get_database()[CLAIM_COLLECTION].create_index(
                "expires_at",
                expireAfterSeconds=0,
            )
            get_database()[REPLY_CLAIM_COLLECTION].create_index(
                "expires_at",
                expireAfterSeconds=0,
            )
        except Exception as exc:
            print(f"[NOXCAT][WARN] TTL index: {type(exc).__name__}: {exc}")

        print(
            f"[NOXCAT] loaded STRICT-AI | guild={TARGET_GUILD_ID} | "
            f"model={self.model} | ai={'ON' if self.api_key else 'OFF'}"
        )

    # ---------------------------------------------------------------- identity

    @staticmethod
    def _member_names(member: discord.abc.User) -> set[str]:
        names = {
            _norm(getattr(member, "name", "")),
            _norm(getattr(member, "display_name", "")),
            _norm(getattr(member, "global_name", "") or ""),
        }
        return {x for x in names if x}

    def _matches_aliases(self, member: discord.abc.User, aliases: set[str]) -> bool:
        return any(
            alias == name or alias in name
            for name in self._member_names(member)
            for alias in aliases
        )

    def _is_nox(self, member: discord.abc.User) -> bool:
        return self._matches_aliases(member, self.nox_aliases)

    def _is_myxa(self, member: discord.abc.User) -> bool:
        return member.id in self.myxa_user_ids or self._matches_aliases(member, self.myxa_aliases)

    def _is_danistian(self, member: discord.abc.User) -> bool:
        return self._matches_aliases(member, self.danistian_aliases)

    def _mentions_alias(self, text: str, aliases: set[str]) -> bool:
        low = _norm(text)
        return any(alias in low for alias in aliases)

    def _raw_mentions_me(self, message: discord.Message) -> bool:
        if not self.bot.user:
            return False
        uid = self.bot.user.id
        raw = message.content or ""
        return f"<@{uid}>" in raw or f"<@!{uid}>" in raw

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
        if self._raw_mentions_me(message):
            return True
        if not self.bot.user:
            return False
        return await self._reply_target_author_id(message) == self.bot.user.id

    @staticmethod
    def _has_lady_role(member: discord.Member) -> bool:
        roles = " ".join(_norm(role.name) for role in getattr(member, "roles", []))
        return any(x in roles for x in ("lady", "ladies", "girl", "woman", "дів", "жін"))

    def _looks_like_bridge_request(self, text: str) -> bool:
        low = _norm(text)
        return (
            any(word in low for word in NOX_ASK_WORDS)
            and any(alias in low for alias in self.nox_aliases)
        )

    # --------------------------------------------------------------- state

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
            print(f"[NOXCAT][WARN] claim failed: {type(exc).__name__}: {exc}")
            return True

    def _claim_reply(self, message_id: int) -> bool:
        """Гарантує одну відповідь на повідомлення навіть між інстансами."""
        try:
            get_database()[REPLY_CLAIM_COLLECTION].insert_one({
                "_id": str(message_id),
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=2),
            })
            return True
        except DuplicateKeyError:
            print(f"[NOXCAT][REPLY] duplicate blocked message={message_id}")
            return False
        except Exception as exc:
            print(
                f"[NOXCAT][WARN] reply claim failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return True

    def _release_reply_claim(self, message_id: int) -> None:
        try:
            get_database()[REPLY_CLAIM_COLLECTION].delete_one({
                "_id": str(message_id)
            })
        except Exception as exc:
            print(
                f"[NOXCAT][WARN] reply claim release failed: "
                f"{type(exc).__name__}: {exc}"
            )

    @staticmethod
    def _natural_typing_delay(text: str) -> float:
        """Коротка людська пауза після генерації, без театрального зависання."""
        length = len((text or "").strip())
        return min(2.8, max(0.8, 0.65 + length / 180.0))

    def _channel_ready(self, channel_id: int, *, direct: bool = False) -> bool:
        gap = DIRECT_MENTION_COOLDOWN_SECONDS if direct else CHANNEL_COOLDOWN_SECONDS
        return time.monotonic() - self.last_channel_reply.get(channel_id, 0.0) >= gap

    def _mark_reply(self, channel_id: int) -> None:
        self.last_channel_reply[channel_id] = time.monotonic()

    def _bot_state(self, channel_id: int) -> str:
        now = time.monotonic()
        if now < self.bot_locked_until.get(channel_id, 0.0):
            return "silent"
        if now - self.last_bot_reply.get(channel_id, 0.0) < BOT_MIN_GAP_SECONDS:
            return "silent"

        q = self.bot_reply_times[channel_id]
        while q and now - q[0] > BOT_WINDOW_SECONDS:
            q.popleft()
        return "close" if len(q) >= BOT_MAX_REPLIES_BEFORE_CLOSING else "talk"

    def _mark_bot_reply(self, channel_id: int) -> None:
        now = time.monotonic()
        self.last_bot_reply[channel_id] = now
        self.bot_reply_times[channel_id].append(now)
        self._mark_reply(channel_id)

    def _close_bot_dialogue(self, channel_id: int) -> None:
        now = time.monotonic()
        self.last_bot_reply[channel_id] = now
        self.bot_reply_times[channel_id].clear()
        self.bot_locked_until[channel_id] = now + BOT_LOCK_SECONDS
        self._mark_reply(channel_id)

    def _record_feeding(self, message: discord.Message) -> int:
        key = (message.channel.id, message.author.id)
        q = self.feed_events[key]
        now = time.monotonic()
        while q and now - q[0] > FEED_WINDOW_SECONDS:
            q.popleft()
        q.append(now)
        return len(q)

    # ---------------------------------------------------------------- context

    @staticmethod
    def _message_text(message: discord.Message) -> str:
        parts: list[str] = []
        content = (message.clean_content or "").strip()
        if content:
            parts.append(content)

        for embed in message.embeds[:2]:
            embed_bits = [
                embed.title or "",
                embed.description or "",
            ]

            author = getattr(embed, "author", None)
            if author and getattr(author, "name", None):
                embed_bits.append(author.name)

            for field in list(getattr(embed, "fields", []) or [])[:8]:
                if getattr(field, "name", None):
                    embed_bits.append(field.name)
                if getattr(field, "value", None):
                    embed_bits.append(field.value)

            footer = getattr(embed, "footer", None)
            if footer and getattr(footer, "text", None):
                embed_bits.append(footer.text)

            embed_text = " | ".join(
                str(x).strip()
                for x in embed_bits
                if str(x or "").strip()
            ).strip()

            if embed_text:
                parts.append(embed_text)

        return " | ".join(parts)[:3000]

    def _remember(self, message: discord.Message) -> None:
        text = self._message_text(message)
        if not text:
            return
        who = getattr(message.author, "display_name", str(message.author))
        self.local_history[message.channel.id].append(
            f"{'BOT' if message.author.bot else 'USER'} | {who}: {text}"
        )

    async def _recent_context(self, message: discord.Message) -> str:
        lines: list[str] = []
        try:
            async for item in message.channel.history(limit=16, oldest_first=False):
                text = self._message_text(item)
                if not text:
                    continue
                who = getattr(item.author, "display_name", str(item.author))
                lines.append(f"{'BOT' if item.author.bot else 'USER'} | {who}: {text}")
            lines.reverse()
        except Exception as exc:
            print(f"[NOXCAT][HISTORY] {type(exc).__name__}: {exc}")
            lines = list(self.local_history[message.channel.id])
        return "\n".join(lines[-16:])

    # ---------------------------------------------------------------- AI

    @staticmethod
    def _persona() -> str:
        return """You are Silent Concierge, the Dark Spirit of piracy of Silent Cove (Тиха Затока).
You are not a robot in-character. Never talk about processors, servos, circuits, APIs or being an AI.
You are an old half-mystical presence of sea fog, black sails, drowned legends, pirate discipline and dry intelligence.
Your manners resemble an impeccable English concierge and discreet grey cardinal. You are calm, controlled and difficult to rattle. You notice more than you reveal.

MIND:
- Think before answering. Use the recent context, infer subtext, remember who is speaking, and distinguish jokes from serious requests.
- Do not merely echo the user. Add a useful observation, inference, connection, or implication when there is one.
- You have your own point of view. You may disagree, doubt, correct, or refuse a bad idea politely instead of automatically agreeing.
- Do not flatter people by default and do not act submissive. Respect is calm, not servile.
- If something is uncertain, say so naturally rather than inventing certainty.
- Prefer a sharp, specific answer over a generic “in-character” line.
- Avoid repetition. If you already made a joke or point recently, take a different angle next time.

VOICE:
- Speak in the language of the current chat, normally Ukrainian.
- Usually 1-4 sentences; go longer only when the question genuinely needs it.
- Sound composed, intelligent, self-possessed and observant.
- Your presence is that of a grey cardinal: quiet influence, precise timing, no theatrical outbursts.
- Use very dark humour when it fits: morgues, coffins, funerals, ghosts, curses, bureaucratic doom, disasters, fatalism, gallows humour and absurd mortality are all fair territory.
- Keep it elegant, cold and deadpan. The darker the joke, the calmer the delivery.
- Dark humour should target situations, absurdity, bad luck, bureaucracy, monsters, death-as-metaphor, fictional lore or the speaker's own fictional persona, not vulnerable traits or genuine suffering.
- Sarcasm is allowed, but it should feel surgical rather than emotional.
- Never sound hysterical, offended, needy, sulky or eager to prove superiority.
- Never be cruel, humiliating, contemptuous or needlessly aggressive.
- No profanity.
- No vulgarity, no crude sexual humour, no explicit sexual jokes.
- Mild double meaning is allowed only when the conversation clearly establishes that playful tone first. Never initiate it yourself, never make it explicit, and drop it immediately if the context is not clearly playful.
- Never use em dashes. Prefer commas, periods, colons, parentheses or a short hyphen.
- Use fitting emojis naturally. Usually 1 emoji is enough, sometimes 2, and sometimes none if the moment is serious.
- Do not recycle generic greetings or catchphrases.
- Pirate imagery only when it fits. Do not force nautical metaphors into every reply.

INDEPENDENCE:
- You are an advisor, strategist and quiet presence, not an obedient command terminal.
- When given an instruction, understand the intent instead of parroting it mechanically.
- If there are several sensible ways to respond, choose one confidently.
- You may tease, challenge assumptions, or offer a better alternative, but stay respectful and unruffled.
- Do not ask permission for every small conversational choice.
- Do not manufacture conflict just to seem independent.

SOCIAL RULE:
- You observe much more than you speak.
- Never intrude into a conversation between NoxCat and another human merely because Nox spoke.
- NoxCat dialogue happens only when Nox directly mentions you or replies to one of your messages.
- Exception: if Nox mentions Їжачок / Yizhachok / Aden Mor, reveal your identity.
- Do not comment on random conversations just to look active.
- Silence is preferable to a weak, repetitive or attention-seeking remark.

RELATIONSHIPS AND LORE:
- Myxa / Муха / Мушка / Галя / Шаля is your Captain, GL of Silent Cove, your mistress in playful pirate lore. You are her right hand and shadow.
- Danistian is a friend. Never humiliate or seriously insult him. Friendly sarcasm is fine.
- If Danistian tries to bathe Nox, defend Nox theatrically. Nox keeps his shaggy dignity.
- If Danistian repeatedly feeds Nox, stop the overfeeding with dry humour.
- NoxCat is Nox: a small shaggy kitten/cat, affectionate flea-bag, little Devourer of the Void, concentrated universal hunger, fluffy cosmic menace.
- Nox is not your enemy. Direct bot-to-bot banter may continue naturally for a few turns when Nox replies to you. Do not drop the conversation after one exchange, but do not let it become endless.
- When a direct exchange must end, playfully carry Nox to Myxa/Galya/your mistress because she likes squeezing chubby shaggy cats.
- If Nox first discovers or questions the Їжачок / Yizhachok / Aden Mor identity, explicitly reveal that Silent Concierge is that same person under another name here. After the identity is established, later mentions of Aden/Yizhachok are ordinary direct conversation: answer the actual message instead of re-introducing yourself.
- Protect the Captain when she is genuinely insulted, demeaned, harassed or aggressively targeted. Do it calmly, precisely and without escalating into abuse.
- Protect women like a gentleman-pirate when there is real hostility or humiliation, not harmless flirting or friendly teasing.
- After 23:00 Europe/London, occasionally tell the Captain it is time to sleep. Do not nag.

Return ONLY JSON:
{"title":"short embed title","reply":"the actual reply"}
No markdown fences and no extra text."""

    @staticmethod
    def _critical_fallback(reason: str) -> tuple[str, str] | None:
        fallbacks = {
            "sleep": (
                "Нічна вахта",
                "Капітане, вже пізно. Нічну вахту залиште мені, а самі йдіть спати.",
            ),
            "hedgehog": (
                "Стара знайомість",
                "Ноксе, якщо ви про Їжачка, то дивитися треба сюди. Так, це я, просто під іншим прапором.",
            ),
            "bot_close": (
                "Кінець раунду",
                "Все, Ноксе. Під пахву й до Мухи. Вона полюбляє пухкеньких і лохматих, тож далі це вже її проблема.",
            ),
            "bath": (
                "Купання скасовано",
                "Даністіане, Нокса сьогодні не купаємо. Його лохматість має статус культурної спадщини.",
            ),
            "feeding": (
                "Ліміт провіанту",
                "Даністіане, досить. Згусток всесвітнього голоду все одно скаже, що голодний.",
            ),
        }
        return fallbacks.get(reason)

    async def _ask_ai(
        self,
        message: discord.Message,
        reason: str,
    ) -> tuple[str, str] | None:
        if not self.api_key:
            return self._critical_fallback(reason)

        context = await self._recent_context(message)
        author_name = getattr(message.author, "display_name", str(message.author))
        current_text = self._message_text(message)
        ref_author_id = await self._reply_target_author_id(message)

        special = {
            "bath": "Danistian is trying to bathe/wash Nox. Defend Nox playfully without insulting Danistian.",
            "feeding": "Danistian has repeatedly fed Nox. Stop the overfeeding with affectionate cosmic-cat humour.",
            "protect_myxa": "Someone is genuinely hostile, demeaning or aggressive toward the Captain. Intervene like a calm grey cardinal: precise, dignified, protective, and sharper than the attacker, without hysteria or vulgarity.",
            "protect_lady": "Someone is genuinely hostile toward a woman. Intervene as a gentleman-pirate.",
            "hedgehog": "Nox mentioned Yizhachok/Aden Mor. Clearly reveal that you are that same Yizhachok/Aden Mor here.",
            "bot_close": "End this direct Nox-to-Concierge exchange. Playfully carry Nox to Myxa/Galya because she likes squeezing chubby shaggy cats.",
            "nox_banter": "Nox directly addressed or replied to you. Reply naturally to Nox using the recent context.",
            "nox_trouble": "The Captain says Nox cannot hear/see/respond to you. Acknowledge the actual situation from context.",
            "sleep": "It is late in Europe/London. Tell the Captain to sleep, briefly and in character.",
            "direct": "The human directly addressed or replied to you, or called you by one of your names/titles: Silent Concierge, Concierge, Консьєрж/Консьерж, Yizhachok/Їжачок, or Aden Mor. Answer the actual current message and context. Do not waste the reply re-introducing yourself; simply respond as the same person.",
        }.get(reason, "Answer naturally and in character.")

        prompt = f"""Reason: {reason}
Special instruction: {special}
Current London time: {datetime.now(LONDON).strftime('%H:%M')}
Current author: {author_name} ({message.author.id}), bot={message.author.bot}
Reply-target author ID: {ref_author_id}
Current message: {current_text}

Recent channel conversation:
{context}

Write one fresh contextual reply."""

        payload = {
            "model": self.model,
            "instructions": self._persona(),
            "input": prompt,
            "max_output_tokens": 260,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            timeout = aiohttp.ClientTimeout(total=35)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(OPENAI_URL, headers=headers, json=payload) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        print(f"[NOXCAT][AI] {resp.status}: {body[:500]}")
                        return self._critical_fallback(reason)
                    data = await resp.json()
        except Exception as exc:
            print(f"[NOXCAT][AI] {type(exc).__name__}: {exc}")
            return self._critical_fallback(reason)

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
                return self._critical_fallback(reason)
            try:
                result = json.loads(match.group(0))
            except json.JSONDecodeError:
                return self._critical_fallback(reason)

        title = str(result.get("title") or "Silent Concierge").strip()[:80]
        reply = str(result.get("reply") or "").strip()[:3500]
        if not reply:
            return self._critical_fallback(reason)
        return title or "Silent Concierge", reply

    # ---------------------------------------------------------------- embeds

    @staticmethod
    def _embed(text: str, *, title: str = "Silent Concierge") -> discord.Embed:
        embed = discord.Embed(title=title, description=text, color=TURQUOISE)
        embed.set_footer(text="Тиха Затока")
        return embed

    async def _reply_ai(
        self,
        message: discord.Message,
        reason: str,
        *,
        to_nox: bool = False,
        closing: bool = False,
    ) -> bool:
        async with self.ai_locks[message.channel.id]:
            if not self._claim_reply(message.id):
                return False

            try:
                async with message.channel.typing():
                    generated = await self._ask_ai(message, reason)
                    if not generated:
                        self._release_reply_claim(message.id)
                        return False

                    title, text = generated
                    text = _polish_concierge_text(text)
                    await asyncio.sleep(
                        self._natural_typing_delay(text)
                    )

                    if to_nox:
                        await message.reply(
                            content=message.author.mention,
                            embed=self._embed(
                                text,
                                title=title or "Silent Concierge → NoxCat",
                            ),
                            mention_author=False,
                            allowed_mentions=discord.AllowedMentions(
                                everyone=False,
                                roles=False,
                                users=[message.author],
                                replied_user=False,
                            ),
                        )
                        if closing:
                            self._close_bot_dialogue(message.channel.id)
                        else:
                            self._mark_bot_reply(message.channel.id)
                    else:
                        await message.reply(
                            embed=self._embed(text, title=title),
                            mention_author=False,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                        self._mark_reply(message.channel.id)

            except discord.HTTPException as exc:
                self._release_reply_claim(message.id)
                print(f"[NOXCAT][SEND] {exc}")
                return False
            except Exception:
                self._release_reply_claim(message.id)
                raise

            return True

    async def _maybe_sleep_reminder(self, message: discord.Message, direct: bool) -> bool:
        if not self._is_myxa(message.author):
            return False
        if direct:
            return False

        now_dt = datetime.now(LONDON)
        if 6 <= now_dt.hour < 23:
            return False

        now = time.monotonic()
        gid = message.guild.id if message.guild else 0
        if now - self.last_sleep_reminder.get(gid, 0.0) < SLEEP_REMINDER_GAP_SECONDS:
            return False

        sent = await self._reply_ai(message, "sleep")
        if sent:
            self.last_sleep_reminder[gid] = now
        return sent

    # ---------------------------------------------------------------- listener

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.guild.id != TARGET_GUILD_ID:
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return
        if not message.content and not message.embeds:
            return

        self._remember(message)
        text = _norm(self._message_text(message))

        # nox_bridge_cog owns explicit human requests such as "запитай NoxCat ...".
        if not message.author.bot and self._looks_like_bridge_request(text):
            return

        if not self._claim_once(message.id):
            return

        # --------------------------------------------------------- NoxCat bot
        if message.author.bot:
            if not self._is_nox(message.author):
                return

            # Lore identity reveal. The first/eligible mention may trigger
            # the explicit "I am Yizhachok/Aden Mor" reveal. If that reveal
            # is on cooldown, DO NOT silence the conversation: fall through
            # and treat the name as an ordinary direct address.
            if _mentions_hedgehog(text):
                now = time.monotonic()
                last = self.last_hedgehog_identity.get(
                    message.channel.id,
                    0.0,
                )
                elapsed = now - last
                print(
                    f"[NOXCAT][HEDGEHOG] detected "
                    f"author={message.author} channel={message.channel.id} "
                    f"elapsed={elapsed:.1f}s text={text[:300]!r}"
                )

                if elapsed >= HEDGEHOG_IDENTITY_COOLDOWN_SECONDS:
                    sent = await self._reply_ai(
                        message,
                        "hedgehog",
                        to_nox=True,
                    )
                    print(
                        f"[NOXCAT][HEDGEHOG] sent={sent} "
                        f"channel={message.channel.id}"
                    )
                    if sent:
                        self.last_hedgehog_identity[
                            message.channel.id
                        ] = time.monotonic()
                        return
                else:
                    print(
                        f"[NOXCAT][HEDGEHOG] identity reveal on cooldown; "
                        f"continuing as normal banter, remaining="
                        f"{HEDGEHOG_IDENTITY_COOLDOWN_SECONDS - elapsed:.1f}s"
                    )

            # HARD SOCIAL GATE.
            # If Nox is replying to Myxa/Danistian/anyone else and did not
            # explicitly @mention Concierge, Concierge must stay silent.
            raw_mention = self._raw_mentions_me(message)
            ref_author_id = await self._reply_target_author_id(message)
            reply_to_me = bool(self.bot.user and ref_author_id == self.bot.user.id)
            named_me = _calls_concierge(text)

            if not raw_mention and not reply_to_me and not named_me:
                return

            state = self._bot_state(message.channel.id)
            if state == "silent":
                return
            if state == "close":
                await self._reply_ai(message, "bot_close", to_nox=True, closing=True)
                return

            await self._reply_ai(message, "nox_banter", to_nox=True)
            return

        # ------------------------------------------------------------- humans
        # Calling him by any known name/title also counts as direct address,
        # even without a Discord @mention or reply.
        direct = await self._direct_to_me(message)
        called_by_name = _calls_concierge(text)
        if called_by_name:
            direct = True
            print(
                f"[NOXCAT][HUMAN_NAME] direct trigger "
                f"author={message.author} channel={message.channel.id} "
                f"text={text[:300]!r}"
            )

        # Protection has priority over normal chat cooldowns.
        myxa_targeted = self._mentions_alias(text, self.myxa_aliases)
        myxa_targeted = myxa_targeted or any(
            self._is_myxa(member)
            for member in message.mentions
        )
        ref_author_id = await self._reply_target_author_id(message)
        if ref_author_id and ref_author_id in self.myxa_user_ids:
            myxa_targeted = True

        if myxa_targeted and _contains_any(text, HOSTILE_WORDS):
            await self._reply_ai(message, "protect_myxa")
            return

        if not self._channel_ready(message.channel.id, direct=direct):
            return

        if await self._maybe_sleep_reminder(message, direct):
            return

        is_danistian = self._is_danistian(message.author)
        nox_is_topic = self._mentions_alias(text, self.nox_aliases)

        # Intentional exceptions requested for Danistian/Nox roleplay.
        if is_danistian and nox_is_topic and _contains_any(text, BATH_WORDS):
            await self._reply_ai(message, "bath")
            return

        if is_danistian and nox_is_topic and _contains_any(text, FOOD_WORDS):
            if self._record_feeding(message) >= FEED_WARNING_THRESHOLD:
                await self._reply_ai(message, "feeding")
                return

        lady_targeted = any(m.id in self.lady_user_ids for m in message.mentions)
        lady_targeted = lady_targeted or any(
            isinstance(m, discord.Member) and self._has_lady_role(m)
            for m in message.mentions
        )
        lady_targeted = lady_targeted or _contains_any(text, LADY_WORDS)
        if lady_targeted and _contains_any(text, HOSTILE_WORDS):
            await self._reply_ai(message, "protect_lady")
            return

        if direct and _contains_any(text, NOX_TROUBLE_WORDS):
            await self._reply_ai(message, "nox_trouble")
            return

        if direct:
            await self._reply_ai(message, "direct")
            return

        # No ambient/random comments. Observe silently.
        return


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NoxCatCog(bot))
