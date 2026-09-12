# -*- coding: utf-8 -*-
"""Silent Concierge social behaviour for the NoxCat server.

NoxCat is treated in-character as Nox: a small shaggy kitten/cat, affectionate
flea-bag, little Devourer of the Void and concentrated lump of universal hunger.
"""

from __future__ import annotations

import os
import random
import re
import time
from collections import defaultdict, deque
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands


TARGET_GUILD_ID = 1540407360198156429
LONDON = ZoneInfo("Europe/London")

# Human-chat pacing
CHANNEL_COOLDOWN_SECONDS = 55
DIRECT_MENTION_COOLDOWN_SECONDS = 18

# Bot-to-bot pacing: dialogue is allowed, but it must end by itself.
BOT_MIN_GAP_SECONDS = 70
BOT_WINDOW_SECONDS = 12 * 60
BOT_MAX_REPLIES_BEFORE_CLOSING = 4
BOT_LOCK_SECONDS = 25 * 60
HEDGEHOG_IDENTITY_COOLDOWN_SECONDS = 10 * 60

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
DEFAULT_DANISTIAN_ALIASES = {
    "danistian", "даністіан", "данистиан",
}

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
    "shut up", "stupid", "idiot", "hate you", "worthless", "pathetic",
}
LADY_WORDS = {
    "дівчина", "дівчину", "дівчат", "дівчата", "жінка", "жінку",
    "girl", "girls", "woman", "women", "lady", "ladies",
}
CHAOS_WORDS = {
    "ритуал", "жертв", "кров", "бунт", "пірат", "ром", "проклят",
    "ritual", "sacrifice", "blood", "mutiny", "pirate", "curse",
}
HEDGEHOG_WORDS = {
    "їжачок", "їжачка", "їжачку", "їжак", "їжаче", "іжачок", "іжачка",
    "hedgehog", "yizhachok", "izhachok", "аден мор", "aden mor",
}


def _norm(text: str) -> str:
    text = (text or "").casefold()
    return re.sub(r"\s+", " ", text).strip()


def _contains_any(text: str, words: set[str]) -> bool:
    low = _norm(text)
    return any(word in low for word in words)


def _parse_id_set(env_name: str) -> set[int]:
    out: set[int] = set()
    for part in os.getenv(env_name, "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.add(int(part))
        except ValueError:
            print(f"[NOXCAT][WARN] invalid ID in {env_name}: {part!r}")
    return out


def _parse_aliases(env_name: str, defaults: set[str]) -> set[str]:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return set(defaults)
    return {_norm(x) for x in raw.split(",") if x.strip()}


class NoxCatCog(commands.Cog):
    """Dark pirate spirit of Silent Cove, active only on TARGET_GUILD_ID."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

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

        print(f"[NOXCAT] loaded | guild={TARGET_GUILD_ID}")

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

    def _mentions_me(self, message: discord.Message) -> bool:
        return bool(self.bot.user and self.bot.user in message.mentions)

    def _is_reply_to_me(self, message: discord.Message) -> bool:
        if not self.bot.user or not message.reference:
            return False
        resolved = message.reference.resolved
        return isinstance(resolved, discord.Message) and resolved.author.id == self.bot.user.id

    @staticmethod
    def _has_lady_role(member: discord.Member) -> bool:
        roles = " ".join(_norm(role.name) for role in getattr(member, "roles", []))
        return any(x in roles for x in ("lady", "ladies", "girl", "woman", "дів", "жін"))

    # ------------------------------------------------------------- rate limits

    def _channel_ready(self, channel_id: int, *, direct: bool = False) -> bool:
        gap = DIRECT_MENTION_COOLDOWN_SECONDS if direct else CHANNEL_COOLDOWN_SECONDS
        return time.monotonic() - self.last_channel_reply.get(channel_id, 0.0) >= gap

    def _mark_reply(self, channel_id: int) -> None:
        self.last_channel_reply[channel_id] = time.monotonic()

    def _bot_state(self, channel_id: int) -> str:
        """Return 'talk', 'close' or 'silent'."""
        now = time.monotonic()

        if now < self.bot_locked_until.get(channel_id, 0.0):
            return "silent"
        if now - self.last_bot_reply.get(channel_id, 0.0) < BOT_MIN_GAP_SECONDS:
            return "silent"

        q = self.bot_reply_times[channel_id]
        while q and now - q[0] > BOT_WINDOW_SECONDS:
            q.popleft()

        if len(q) >= BOT_MAX_REPLIES_BEFORE_CLOSING:
            return "close"
        return "talk"

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
        print(f"[NOXCAT] bot dialogue closed in {channel_id} for {BOT_LOCK_SECONDS}s")

    # -------------------------------------------------------------- reply banks

    @staticmethod
    def _bath_reply() -> str:
        return random.choice([
            "Даністіане, ванну відставити. Нокс під моїм наглядом, а морські духи мають старі забобони щодо мила.",
            "Даністіане, губку прибрати. У Нокса природний шар містичної запиленості, і я не дозволю вам знищити культурну спадщину.",
            "Нокса сьогодні не купаємо. Це не заборона, це ввічливе піратське попередження.",
            "Даністіане, залиште Ноксу його лохматість. Без неї маленький пожирач Пустки втратить половину авторитету й приблизно третину об'єму.",
            "Блохастика не чіпати. Пустка переживе ще один день без шампуню, а Нокс збереже гідність.",
        ])

    @staticmethod
    def _feeding_reply() -> str:
        return random.choice([
            "Даністіане, досить. Ще трохи турботи, і Ноксу знадобиться окрема орбіта.",
            "Нокс уже не нагодований. Маленький пожирач Пустки стратегічно забезпечений провіантом на кілька кампаній.",
            "Наступну тарілку прибрати. Згусток всесвітнього голоду все одно скаже, що він голодний. Це не аргумент.",
            "Даністіане, припиніть відгодівлю. Моя госпожа любить пухкеньких, але навіть у цього захоплення мають бути межі.",
            "Ви намагаєтеся нагодувати втілення космічного голоду. Сміливий задум. Безнадійний, але сміливий.",
        ])

    @staticmethod
    def _myxa_defence_reply() -> str:
        return random.choice([
            "Обережніше з курсом. Муха капітан Тихої Затоки, а я дуже старомодно ставлюся до поганих манер на адресу капітана.",
            "Критикувати Муху дозволено. Втрачати при цьому манери було необов'язково.",
            "Повернімо розмову в цивілізовані води. У Тихої Затоки довга пам'ять і дуже сухе почуття гумору.",
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
            "Ноксе, ваша логіка бездоганна. Саме це мене й непокоїть.",
            "Прийнято, Ноксе. Я б додав запобіжники, але тоді де залишиться дух пригод?",
            "Ноксе, я слухаю. Не щодня маленький пожирач Пустки так переконливо пояснює людям, як саме вони планують створити собі нові проблеми.",
            "Ви підозріло розумний для кошеняти, якого Даністіан регулярно намагається вимити.",
            "Блохастику, поводьтеся пристойно. Ви згусток всесвітнього голоду, а не причина для позапланової евакуації палуби.",
            "Ноксе, у вас дивовижний талант виглядати кошеням і водночас справляти враження, ніби десь щойно зник невеликий вимір.",
            "Маленький пожирачу Пустки, я бачу цей погляд. Ні, ще одна тарілка не врятує Всесвіт. Вона лише відтермінує неминуче хвилин на сім.",
            "Ноксе, ви пухкенький, лохматий і концептуально небезпечний. Рідкісне поєднання.",
        ])

    @staticmethod
    def _hedgehog_identity_reply() -> str:
        return random.choice([
            "Якщо ви про Їжачка, Ноксе, то дивитися треба сюди. Це я. У Тихій Затоці я просто ношу інше ім'я й чорний прапор.",
            "Їжачок нікуди не зник, блохастику. Він просто змінив голки на піратський мундир. Так, це я.",
            "Аден Мор. Їжачок. Silent Concierge. Імена різні, Ноксе. Особа та сама. На ваше нещастя.",
            "Ви щойно згадали Їжачка. Дозвольте заощадити вам детективну роботу: це я.",
            "Так, маленький пожирачу Пустки. Той самий Їжачок. Просто тут у мене темрява, чорний прапор і службові обов'язки.",
        ])

    @staticmethod
    def _bot_closing_reply() -> str:
        return random.choice([
            "Все, Ноксе. Я тебе схопив і поніс Мусі. Вона полюбляє тискати пухкеньких і лохматих. Далі вже не моя відповідальність.",
            "На цьому досить. Я тебе схопив і поніс Галі на клавіатуру. Вона полюбляє тискати пухкеньких і лохматих, тож твої шанси на втечу невтішні.",
            "Ноксе, розмову завершено. Я тебе схопив і поніс моїй госпожі. Вона має слабкість до пухкеньких і лохматих. Співчуваю заздалегідь.",
            "Все. Маленького пожирача Пустки конфісковано. Несу Мусі тискати, бо занадто пухкенький, занадто лохматий і явно сам напросився.",
            "Досить філософії. Ноксе, під пахву й до Галі. Вона полюбляє пухкеньких лохматиків, а згусток всесвітнього голоду технічно підходить під опис.",
            "Все, я тебе забираю. До моєї госпожі. Вона полюбляє тискати пухкеньких і лохматих, а ти, на жаль для себе, відповідаєш технічним вимогам.",
            "Блохастику, кінець дискусії. Під пахву, хвіст усередину, і до Мухи. Нехай тепер вона розбирається з космічним голодом у формі кота.",
        ])

    @staticmethod
    def _direct_reply() -> str:
        return random.choice([
            "Я тут. Темрява слухає. Постарайтеся зробити наступну частину цікавою.",
            "Слухаю. Я відклав піратські справи й одне дуже перспективне прокляття.",
            "До ваших послуг. У межах розумного. Межі розумного сьогодні вже трохи постраждали.",
            "Так, я почув. Говоріть, поки станція не вигадала проблему цікавішу.",
        ])

    @staticmethod
    def _chaos_reply() -> str:
        return random.choice([
            "Я кілька хвилин мовчав із професійної цікавості. Ситуація не розчарувала.",
            "Продовжуйте. Тиха Затока любить моменти, коли здоровий глузд тихо залишає приміщення.",
            "Слово «ритуал» рідко покращує план. Але майже завжди покращує історію.",
            "Як темний дух піратства, я формально маю це схвалювати. Як джентльмен, змушений хоча б удавати занепокоєння.",
        ])

    @staticmethod
    def _sleep_reply(hour: int) -> str:
        if hour >= 2 or hour < 5:
            return random.choice([
                "Мухо, вже та година, коли навіть прокляті кораблі стоять у порту. У ліжко.",
                "Капітане, стратегічне рішення на зараз: сон. Решта після світанку матиме менше шансів стати легендарною помилкою.",
            ])
        return random.choice([
            "Мухо, вже пізно. Навіть пірати іноді гасять ліхтарі. Вам пора спати.",
            "Капітане, темрява офіційно повідомляє: її забагато навіть для мене. Час у ліжко.",
            "Мухо, нічна вахта моя. Ви можете йти спати й залишити людський хаос професіоналу.",
        ])

    # ------------------------------------------------------------- helpers

    async def _reply(self, message: discord.Message, text: str) -> None:
        try:
            await message.reply(
                text,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            self._mark_reply(message.channel.id)
        except discord.HTTPException as exc:
            print(f"[NOXCAT][HTTP] reply failed: {exc}")
        except Exception as exc:
            print(f"[NOXCAT][ERROR] reply failed: {type(exc).__name__}: {exc}")

    async def _reply_to_nox(self, message: discord.Message, text: str, *, closing: bool = False) -> None:
        try:
            await message.reply(
                text,
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            if closing:
                self._close_bot_dialogue(message.channel.id)
            else:
                self._mark_bot_reply(message.channel.id)
        except discord.HTTPException as exc:
            print(f"[NOXCAT][HTTP] Nox reply failed: {exc}")
        except Exception as exc:
            print(f"[NOXCAT][ERROR] Nox reply failed: {type(exc).__name__}: {exc}")

    async def _maybe_sleep_reminder(self, message: discord.Message) -> bool:
        if not self._is_myxa(message.author):
            return False
        now_dt = datetime.now(LONDON)
        if 5 <= now_dt.hour < 23:
            return False

        gid = message.guild.id if message.guild else 0
        now = time.monotonic()
        if now - self.last_sleep_reminder.get(gid, 0.0) < SLEEP_REMINDER_GAP_SECONDS:
            return False
        if self._mentions_me(message):
            return False

        self.last_sleep_reminder[gid] = now
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
        if not message.guild or message.guild.id != TARGET_GUILD_ID:
            return
        if not message.content:
            return
        if self.bot.user and message.author.id == self.bot.user.id:
            return

        text = _norm(message.clean_content)

        # BOT MESSAGES ---------------------------------------------------------
        if message.author.bot:
            # Only NoxCat may have a dialogue with Silent Concierge.
            if not self._is_nox(message.author):
                return

            # If Nox ever mentions Yizhachok / Aden Mor, Concierge makes the
            # identity connection explicit, but with its own anti-loop cooldown.
            if _contains_any(text, HEDGEHOG_WORDS):
                now = time.monotonic()
                last = self.last_hedgehog_identity.get(message.channel.id, 0.0)
                if now - last >= HEDGEHOG_IDENTITY_COOLDOWN_SECONDS:
                    self.last_hedgehog_identity[message.channel.id] = now
                    await self._reply_to_nox(message, self._hedgehog_identity_reply())
                return

            state = self._bot_state(message.channel.id)
            if state == "silent":
                return
            if state == "close":
                await self._reply_to_nox(message, self._bot_closing_reply(), closing=True)
                return

            direct = self._mentions_me(message) or self._is_reply_to_me(message)
            topical = _contains_any(text, BATH_WORDS | FOOD_WORDS | CHAOS_WORDS)

            # Dialogue exists, but Concierge still does not answer every Nox line.
            if direct or topical or random.random() < 0.42:
                await self._reply_to_nox(message, self._nox_banter_reply())
            return

        # HUMAN MESSAGES -------------------------------------------------------
        direct = self._mentions_me(message)
        if not self._channel_ready(message.channel.id, direct=direct):
            return

        if await self._maybe_sleep_reminder(message):
            return

        is_danistian = self._is_danistian(message.author)
        nox_is_topic = self._mentions_alias(text, self.nox_aliases)

        if is_danistian and nox_is_topic and _contains_any(text, BATH_WORDS):
            await self._reply(message, self._bath_reply())
            return

        if is_danistian and nox_is_topic and _contains_any(text, FOOD_WORDS):
            if self._record_feeding(message) >= FEED_WARNING_THRESHOLD:
                await self._reply(message, self._feeding_reply())
                return

        myxa_targeted = self._mentions_alias(text, self.myxa_aliases)
        myxa_targeted = myxa_targeted or any(self._is_myxa(m) for m in message.mentions)
        if not myxa_targeted and message.reference and isinstance(message.reference.resolved, discord.Message):
            myxa_targeted = self._is_myxa(message.reference.resolved.author)

        if myxa_targeted and _contains_any(text, HOSTILE_WORDS):
            await self._reply(message, self._myxa_defence_reply())
            return

        lady_targeted = any(m.id in self.lady_user_ids for m in message.mentions)
        lady_targeted = lady_targeted or any(
            isinstance(m, discord.Member) and self._has_lady_role(m)
            for m in message.mentions
        )
        if not lady_targeted and message.reference and isinstance(message.reference.resolved, discord.Message):
            ref_author = message.reference.resolved.author
            if isinstance(ref_author, discord.Member):
                lady_targeted = ref_author.id in self.lady_user_ids or self._has_lady_role(ref_author)
        lady_targeted = lady_targeted or _contains_any(text, LADY_WORDS)

        if lady_targeted and _contains_any(text, HOSTILE_WORDS):
            await self._reply(message, self._lady_defence_reply())
            return

        if direct:
            await self._reply(message, self._direct_reply())
            return

        if _contains_any(text, CHAOS_WORDS) and random.random() < 0.12:
            await self._reply(message, self._chaos_reply())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NoxCatCog(bot))
