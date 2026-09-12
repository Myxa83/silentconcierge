# -*- coding: utf-8 -*-
"""
Social behaviour for Silent Concierge on external servers.

Silent Concierge is the dark pirate spirit of Silent Cove: calm, elegant,
sardonic, loyal to Myxa, protective of NoxCat, and deliberately quiet unless
there is a reason to intervene.

The cog is active on non-home guilds by default. Optional env vars:
  NOXCAT_GUILD_IDS              comma-separated guild IDs
  CONCIERGE_MYXA_IDS            comma-separated user IDs
  CONCIERGE_LADY_IDS            comma-separated user IDs
  NOXCAT_BOT_ALIASES            comma-separated aliases
  CONCIERGE_MYXA_ALIASES        comma-separated aliases
  CONCIERGE_DANISTIAN_ALIASES   comma-separated aliases
"""

from __future__ import annotations

import os
import random
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands


LONDON = ZoneInfo("Europe/London")

# General silence / anti-spam.
CHANNEL_COOLDOWN_SECONDS = 55
DIRECT_MENTION_COOLDOWN_SECONDS = 18

# Bot-to-bot safety. NoxCat is the only bot Silent Concierge may answer.
# Two replies in ten minutes -> twenty minute bot-dialogue pause.
BOT_DIALOGUE_MIN_GAP_SECONDS = 90
BOT_DIALOGUE_WINDOW_SECONDS = 10 * 60
BOT_DIALOGUE_MAX_REPLIES_IN_WINDOW = 2
BOT_DIALOGUE_LOCK_SECONDS = 20 * 60

SLEEP_REMINDER_GAP_SECONDS = 60 * 60
FEED_WINDOW_SECONDS = 20 * 60
FEED_WARNING_THRESHOLD = 3
CONTEXT_LIMIT = 16

DEFAULT_NOX_ALIASES = {
    "noxcat", "nox cat", "нокс", "нокс кет", "нокс кэт", "nox",
}
DEFAULT_MYXA_ALIASES = {
    "myxa83", "myxa", "муха", "мушка", "шаля", "shalya",
}
DEFAULT_DANISTIAN_ALIASES = {
    "danistian", "даністіан", "данистиан",
}

BATH_WORDS = {
    "купати", "купаю", "купання", "купатись", "купатися", "ванна", "ванну",
    "душ", "мити", "помити", "шампунь", "мило", "губка",
    "bath", "bathe", "shower", "wash", "soap", "shampoo", "sponge",
}
FOOD_WORDS = {
    "годувати", "годує", "годуй", "нагодувати", "їсти", "їжа", "їжею",
    "смаколик", "смаколики", "печиво", "торт", "пиріг", "цукерки",
    "feed", "feeding", "food", "eat", "snack", "cake", "pie", "cookie", "treat",
}
HOSTILE_WORDS = {
    "заткнись", "замовкни", "тупа", "дурна", "ідіотка", "ненавиджу",
    "shut up", "stupid", "idiot", "hate you", "worthless", "pathetic",
}
LADY_WORDS = {
    "дівчина", "дівчину", "дівчат", "дівчата", "жінка", "жінку",
    "girl", "girls", "woman", "women", "lady", "ladies",
}
CHAOS_WORDS = {
    "ритуал", "жертв", "кров", "війна", "бунт", "пірат", "ром", "проклят",
    "ritual", "sacrifice", "blood", "war", "mutiny", "pirate", "curse",
}


@dataclass(slots=True)
class SeenLine:
    at: float
    author_id: int
    author_name: str
    is_bot: bool
    content: str


def _norm(text: str) -> str:
    text = (text or "").casefold()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _contains_any(text: str, words: set[str]) -> bool:
    low = _norm(text)
    return any(word in low for word in words)


def _parse_id_set(env_name: str) -> set[int]:
    raw = os.getenv(env_name, "")
    out: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            print(f"[NOXCAT][WARN] invalid ID in {env_name}: {part!r}")
    return out


def _parse_aliases(env_name: str, defaults: set[str]) -> set[str]:
    raw = os.getenv(env_name, "")
    if not raw.strip():
        return set(defaults)
    return {_norm(x) for x in raw.split(",") if x.strip()}


class NoxCatCog(commands.Cog):
    """Social brain for Silent Concierge on the NoxCat server."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

        self.target_guild_ids = _parse_id_set("NOXCAT_GUILD_IDS")
        self.myxa_user_ids = _parse_id_set("CONCIERGE_MYXA_IDS")
        self.lady_user_ids = _parse_id_set("CONCIERGE_LADY_IDS")

        self.nox_aliases = _parse_aliases("NOXCAT_BOT_ALIASES", DEFAULT_NOX_ALIASES)
        self.myxa_aliases = _parse_aliases("CONCIERGE_MYXA_ALIASES", DEFAULT_MYXA_ALIASES)
        self.danistian_aliases = _parse_aliases(
            "CONCIERGE_DANISTIAN_ALIASES", DEFAULT_DANISTIAN_ALIASES
        )

        self.context: dict[int, Deque[SeenLine]] = defaultdict(
            lambda: deque(maxlen=CONTEXT_LIMIT)
        )
        self.last_channel_reply: dict[int, float] = {}
        self.last_sleep_reminder: dict[int, float] = {}
        self.feed_events: dict[tuple[int, int], Deque[float]] = defaultdict(deque)

        self.bot_reply_times: dict[int, Deque[float]] = defaultdict(deque)
        self.bot_dialogue_locked_until: dict[int, float] = {}
        self.last_bot_reply: dict[int, float] = {}

        print(
            "[NOXCAT] loaded | "
            f"guild_filter={sorted(self.target_guild_ids) or 'all external guilds'}"
        )

    # ---------------------------------------------------------------- identity

    def _is_target_guild(self, guild: discord.Guild | None) -> bool:
        if guild is None:
            return False
        if self.target_guild_ids:
            return guild.id in self.target_guild_ids

        # By default this roleplay never runs on the bot's home guild.
        home_id = getattr(self.bot, "home_guild_id", None)
        return not home_id or guild.id != home_id

    @staticmethod
    def _member_names(member: discord.abc.User) -> set[str]:
        names = {
            _norm(getattr(member, "name", "")),
            _norm(getattr(member, "display_name", "")),
            _norm(getattr(member, "global_name", "") or ""),
        }
        return {x for x in names if x}

    def _matches_aliases(self, member: discord.abc.User, aliases: set[str]) -> bool:
        for name in self._member_names(member):
            for alias in aliases:
                if alias == name or alias in name:
                    return True
        return False

    def _is_nox(self, member: discord.abc.User) -> bool:
        return self._matches_aliases(member, self.nox_aliases)

    def _is_myxa(self, member: discord.abc.User) -> bool:
        if member.id in self.myxa_user_ids:
            return True
        return self._matches_aliases(member, self.myxa_aliases)

    def _is_danistian(self, member: discord.abc.User) -> bool:
        return self._matches_aliases(member, self.danistian_aliases)

    def _mentions_alias(self, text: str, aliases: set[str]) -> bool:
        low = _norm(text)
        return any(alias in low for alias in aliases)

    def _mentions_me(self, message: discord.Message) -> bool:
        return bool(self.bot.user and self.bot.user in message.mentions)

    def _is_reply_to_me(self, message: discord.Message) -> bool:
        if not self.bot.user or not message.reference:
            return False
        resolved = message.reference.resolved
        return isinstance(resolved, discord.Message) and resolved.author.id == self.bot.user.id

    @staticmethod
    def _has_lady_role(member: discord.Member) -> bool:
        role_text = " ".join(_norm(role.name) for role in getattr(member, "roles", []))
        return any(
            marker in role_text
            for marker in ("lady", "ladies", "girl", "woman", "дів", "жін")
        )

    # ---------------------------------------------------------------- context

    def _remember(self, message: discord.Message) -> None:
        if not message.guild:
            return
        self.context[message.channel.id].append(
            SeenLine(
                at=time.monotonic(),
                author_id=message.author.id,
                author_name=getattr(message.author, "display_name", message.author.name),
                is_bot=message.author.bot,
                content=(message.clean_content or "")[:700],
            )
        )

    def _recent_mentions_nox(self, channel_id: int, within: int = 180) -> bool:
        now = time.monotonic()
        for line in reversed(self.context[channel_id]):
            if now - line.at > within:
                break
            if self._mentions_alias(line.content, self.nox_aliases):
                return True
        return False

    # ------------------------------------------------------------- rate limits

    def _channel_ready(self, channel_id: int, direct: bool = False) -> bool:
        gap = DIRECT_MENTION_COOLDOWN_SECONDS if direct else CHANNEL_COOLDOWN_SECONDS
        last = self.last_channel_reply.get(channel_id, 0.0)
        return time.monotonic() - last >= gap

    def _mark_reply(self, channel_id: int) -> None:
        self.last_channel_reply[channel_id] = time.monotonic()

    def _bot_dialogue_allowed(self, channel_id: int) -> bool:
        now = time.monotonic()

        if now < self.bot_dialogue_locked_until.get(channel_id, 0.0):
            return False

        if now - self.last_bot_reply.get(channel_id, 0.0) < BOT_DIALOGUE_MIN_GAP_SECONDS:
            return False

        q = self.bot_reply_times[channel_id]
        while q and now - q[0] > BOT_DIALOGUE_WINDOW_SECONDS:
            q.popleft()

        if len(q) >= BOT_DIALOGUE_MAX_REPLIES_IN_WINDOW:
            self.bot_dialogue_locked_until[channel_id] = now + BOT_DIALOGUE_LOCK_SECONDS
            q.clear()
            print(
                f"[NOXCAT] bot dialogue paused in channel {channel_id} "
                f"for {BOT_DIALOGUE_LOCK_SECONDS}s"
            )
            return False

        return True

    def _mark_bot_reply(self, channel_id: int) -> None:
        now = time.monotonic()
        self.last_bot_reply[channel_id] = now
        self.bot_reply_times[channel_id].append(now)
        self._mark_reply(channel_id)

    # -------------------------------------------------------------- reply banks

    @staticmethod
    def _bath_reply() -> str:
        return random.choice([
            "Даністіане, ванну відставити. Нокс під моїм наглядом, а морські духи мають старі забобони щодо мила.",
            "Даністіане, обережніше з губкою. Тиха Затока ще не оговталася від попередніх великих рішень.",
            "Нокса сьогодні не купаємо. Це не заборона. Це ввічливе піратське попередження, а вони традиційно переживають заборони.",
            "Даністіане, залиште Ноксу його природний рівень містичної запиленості. Він йому пасує.",
        ])

    @staticmethod
    def _feeding_reply() -> str:
        return random.choice([
            "Даністіане, досить. Ще трохи турботи, і Ноксу знадобиться окрема орбіта.",
            "Я високо ціную вашу гостинність, Даністіане. Але Нокс уже перейшов зі стану «нагодували» у стан «формують стратегічний запас».",
            "Приберіть наступну тарілку, Даністіане. Темрява має бути загадковою, а не ситою до нерухомості.",
            "Нокс нагодований. Повторю: нагодований. Тиха Затока не фінансує програму його промислової відгодівлі.",
        ])

    @staticmethod
    def _myxa_defence_reply() -> str:
        return random.choice([
            "Обережніше з курсом. Муха капітан Тихої Затоки, а я дуже старомодно ставлюся до поганих манер на адресу капітана.",
            "Панове, критикувати Муху дозволено. Втрачати при цьому манери було необов'язково.",
            "Я б радив повернути розмову в цивілізовані води. У Тихої Затоки довга пам'ять і напрочуд сухе почуття гумору.",
            "Капітана можна не любити. Це навіть корисно для характеру. Але говорити з нею варто пристойно.",
        ])

    @staticmethod
    def _lady_defence_reply() -> str:
        return random.choice([
            "Пане, змініть курс. Джентльмен може програти суперечку, але не повинен програвати манери.",
            "До леді трохи спокійніше. Ми все-таки пірати, а не дикуни. Різниця тонка, але я за нею стежу.",
            "Сарказм залишимо, зневагу приберемо. Чорний прапор не є ліцензією на погані манери.",
        ])

    @staticmethod
    def _nox_banter_reply() -> str:
        return random.choice([
            "Ноксе, продовжуйте. Я саме перевіряв, скільки здорового глузду ця станція витримає за один вечір.",
            "Цікаво, Ноксе. Темрява Тихої Затоки занотувала це під рубрикою «можливо геніально, можливо наслідки».",
            "Ноксе, ваша логіка бездоганна. Це мене й непокоїть.",
            "Прийнято, Ноксе. Я б додав запобіжники, але тоді де залишиться дух пригод і робота для ремонтної бригади?",
            "Ноксе, я слухаю. Не щодня інший бот так переконливо пояснює людям, як саме вони планують створити собі нові проблеми.",
        ])

    @staticmethod
    def _direct_reply() -> str:
        return random.choice([
            "Я тут. Темрява слухає. Постарайтеся зробити наступну частину цікавою.",
            "Слухаю. Я відклав піратські справи й одне дуже перспективне прокляття.",
            "До ваших послуг. У межах розумного. Межі розумного сьогодні, щоправда, вже трохи постраждали.",
            "Так, я почув. Говоріть, поки станція не вигадала проблему цікавішу.",
        ])

    @staticmethod
    def _chaos_reply() -> str:
        return random.choice([
            "Я кілька хвилин мовчав із професійної цікавості. Ситуація не розчарувала.",
            "Продовжуйте. Тиха Затока любить моменти, коли здоровий глузд тихо залишає приміщення.",
            "Нагадую: слово «ритуал» рідко покращує план. Але майже завжди покращує історію.",
            "Як темний дух піратства, я формально маю це схвалювати. Як джентльмен, я змушений хоча б удавати занепокоєння.",
        ])

    @staticmethod
    def _sleep_reply(hour: int) -> str:
        if hour >= 2 or hour < 5:
            return random.choice([
                "Мухо, вже та година, коли навіть прокляті кораблі стоять у порту. У ліжко.",
                "Капітане, стратегічне рішення на зараз: сон. Усе інше після світанку матиме менше шансів стати легендарною помилкою.",
            ])
        return random.choice([
            "Мухо, вже пізно. Навіть пірати іноді гасять ліхтарі. Вам пора спати.",
            "Капітане, темрява офіційно повідомляє: її забагато навіть для мене. Час у ліжко.",
            "Мухо, нічна вахта моя. Ви можете йти спати й залишити людський хаос професіоналу.",
        ])

    # ------------------------------------------------------------- reply helper

    async def _reply(self, message: discord.Message, text: str, *, bot_turn: bool = False) -> None:
        try:
            await message.reply(
                text,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    roles=False,
                    users=False,
                    replied_user=False,
                ),
            )
            if bot_turn:
                self._mark_bot_reply(message.channel.id)
            else:
                self._mark_reply(message.channel.id)
        except discord.HTTPException as exc:
            print(f"[NOXCAT][HTTP] reply failed: {exc}")
        except Exception as exc:
            print(f"[NOXCAT][ERROR] reply failed: {type(exc).__name__}: {exc}")

    async def _maybe_sleep_reminder(self, message: discord.Message) -> bool:
        if not self._is_myxa(message.author):
            return False

        now_dt = datetime.now(LONDON)
        if 5 <= now_dt.hour < 23:
            return False

        now = time.monotonic()
        guild_id = message.guild.id if message.guild else 0
        if now - self.last_sleep_reminder.get(guild_id, 0.0) < SLEEP_REMINDER_GAP_SECONDS:
            return False

        if self._mentions_me(message):
            return False

        self.last_sleep_reminder[guild_id] = now
        await self._reply(message, self._sleep_reply(now_dt.hour))
        return True

    def _record_feeding(self, message: discord.Message) -> int:
        key = (message.channel.id, message.author.id)
        q = self.feed_events[key]
        now = time.monotonic()
        while q and now - q[0] > FEED_WINDOW_SECONDS:
            q.popleft()
        q.append(now)
        return len(q)

    # ---------------------------------------------------------------- listener

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not self._is_target_guild(message.guild):
            return
        if not message.content:
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return

        self._remember(message)
        text = _norm(message.clean_content)

        # BOT MESSAGES ---------------------------------------------------------
        if message.author.bot:
            # All bots except NoxCat are ignored completely.
            if not self._is_nox(message.author):
                return
            if not self._bot_dialogue_allowed(message.channel.id):
                return

            direct = self._mentions_me(message) or self._is_reply_to_me(message)
            bath_context = _contains_any(text, BATH_WORDS)
            food_context = _contains_any(text, FOOD_WORDS)

            # A direct NoxCat ping/reply gets a turn if the limiter allows it.
            # Otherwise occasional banter only, so two bots cannot take over chat.
            if direct or bath_context or food_context or random.random() < 0.22:
                await self._reply(message, self._nox_banter_reply(), bot_turn=True)
            return

        # HUMAN MESSAGES -------------------------------------------------------
        direct = self._mentions_me(message)
        if not self._channel_ready(message.channel.id, direct=direct):
            return

        # Sparse late-night reminder for Myxa after 23:00 UK time.
        if await self._maybe_sleep_reminder(message):
            return

        is_danistian = self._is_danistian(message.author)
        nox_is_topic = (
            self._mentions_alias(text, self.nox_aliases)
            or self._recent_mentions_nox(message.channel.id)
        )

        # Danistian may be teased, never attacked.
        if is_danistian and nox_is_topic and _contains_any(text, BATH_WORDS):
            await self._reply(message, self._bath_reply())
            return

        if is_danistian and nox_is_topic and _contains_any(text, FOOD_WORDS):
            feed_count = self._record_feeding(message)
            if feed_count >= FEED_WARNING_THRESHOLD:
                await self._reply(message, self._feeding_reply())
                return

        # Protect Myxa / Муха / Шаля when explicitly targeted with hostility.
        myxa_targeted = self._mentions_alias(text, self.myxa_aliases)
        myxa_targeted = myxa_targeted or any(self._is_myxa(m) for m in message.mentions)
        if not myxa_targeted and message.reference and message.reference.resolved:
            ref_msg = message.reference.resolved
            if isinstance(ref_msg, discord.Message):
                myxa_targeted = self._is_myxa(ref_msg.author)

        if myxa_targeted and _contains_any(text, HOSTILE_WORDS):
            await self._reply(message, self._myxa_defence_reply())
            return

        # Protect girls without guessing gender from names. Explicit IDs, lady
        # roles, direct lady wording, and replies to a configured/lady-role user
        # are recognized.
        lady_targeted = any(m.id in self.lady_user_ids for m in message.mentions)
        lady_targeted = lady_targeted or any(
            isinstance(m, discord.Member) and self._has_lady_role(m)
            for m in message.mentions
        )
        if not lady_targeted and message.reference and message.reference.resolved:
            ref_msg = message.reference.resolved
            if isinstance(ref_msg, discord.Message) and isinstance(ref_msg.author, discord.Member):
                lady_targeted = (
                    ref_msg.author.id in self.lady_user_ids
                    or self._has_lady_role(ref_msg.author)
                )
        lady_targeted = lady_targeted or _contains_any(text, LADY_WORDS)

        if lady_targeted and _contains_any(text, HOSTILE_WORDS):
            await self._reply(message, self._lady_defence_reply())
            return

        # Direct mention of Silent Concierge always gets a short in-character line.
        if direct:
            await self._reply(message, self._direct_reply())
            return

        # Rare ambient intervention. He watches far more than he speaks.
        if _contains_any(text, CHAOS_WORDS) and random.random() < 0.12:
            await self._reply(message, self._chaos_reply())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NoxCatCog(bot))
