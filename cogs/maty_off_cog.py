# -*- coding: utf-8 -*-
# cogs/maty_off_cog.py

import json
import random
import re
import unicodedata
from calendar import monthrange
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks


# =========================
# НАЛАШТУВАННЯ
# =========================

STATE_FILE = Path("data/maty_off_stats.json")

TIMEZONE = ZoneInfo("Europe/London")

AWARD_CHANNEL_ID = 1331734685683945523
AWARD_HOUR = 21
AWARD_MINUTE = 0

DELETE_ORIGINAL_MESSAGE = True
SEND_CLEAN_COPY = True

IGNORE_ADMINS = False
LOG_TO_CONSOLE = True

# Якщо порожньо - бот реагує у всіх каналах
WATCH_CHANNEL_IDS: set[int] = set()

# Якщо порожньо - не ігнорує жодні ролі
IGNORE_ROLE_IDS: set[int] = set()

# Якщо хочеш реально видавати роль переможцю - встав ID ролі
# Якщо не треба - лишай None
AWARD_ROLE_ID: int | None = None

MAX_REUPLOAD_FILES = 10
MAX_REUPLOAD_BYTES = 25 * 1024 * 1024


AWARD_TITLE = "Великий Магістр Матюка - Почесний Пʼю Лайливого Мистецтва"


# =========================
# ФРАЗИ
# =========================

CENSOR_PHRASES = [
    "(Муха закрила вуха)",
    "(ай-ай-яй)",
    "(цензура від Мухи)",
    "(ротик під наглядом)",
    "(словниковий злочин)",
    "(куточок уже чекає)",
    "(Муха це бачила)",
    "(тут було некультурне слово, але Муха проти)",
    "(нецензурний писк)",
    "(пік-пік цензури)",
    "(мильний рот активовано)",
    "(слово втекло в куточок)",
    "(Муха поставила печатку ганьби)",
    "(тут пройшов тапок виховання)",
]


WARNING_PHRASES = [
    "Ай-ай-яй, Муха побачить - у куточок поставить.",
    "Муха все бачить. Навіть це.",
    "Куточок уже прогрівається.",
    "Муха записала. Муха запамʼятала.",
    "Словниковий патруль прибув.",
    "Так-так-так... це що за мовний демон виліз.",
    "Ротик щойно пройшов техогляд Мухи.",
    "Муха розчаровано дивиться з темряви.",
    "Варений горох у куточку вже твій: склизький, холодний, персонально для тебе.",
]


# =========================
# БІЛИЙ СПИСОК
# =========================

SAFE_WORDS = {
    # бляшка
    "бляшка",
    "бляшки",
    "бляшку",
    "бляшкою",
    "бляшці",
    "бляшках",
    "бляшками",
    "бляшковий",
    "бляшкова",
    "бляшкове",
    "бляшкові",
    "бляшкового",
    "бляшкової",
    "бляшкових",

    # стріляти
    "стріляти",
    "стріляє",
    "стріляють",
    "стріляв",
    "стріляла",
    "стріляли",
    "стрілятися",
    "пристріляти",
    "застріляти",
    "відстріляти",
    "постріляти",

    # мудрий
    "мудрий",
    "мудра",
    "мудре",
    "мудрі",
    "мудрого",
    "мудрої",
    "мудрим",
    "мудрість",
    "мудрості",

    # сукня / сукупність
    "сукня",
    "сукні",
    "сукню",
    "сукнею",
    "сукнях",
    "сукнями",
    "сукупність",
    "сукупності",
    "сукупний",
    "сукупна",
    "сукупне",
    "сукупні",
    "сукупного",
    "сукупної",
}


# Додаткові безпечні основи. Вони захищають звичайні слова від широких regex.
# Повний словник мови тут не потрібен: перевіряємо лише відомі конфлікти.
SAFE_WORD_PREFIXES = (
    "бляшк",
    "стріля",
    "пристріля",
    "застріля",
    "відстріля",
    "постріля",
    "мудр",
    "сукн",
    "сукуп",
    "херсон",
    "херувим",
    "херес",
    "херсонес",
    "дерма",
    "дермат",
    "дермаль",
    "лохин",
    "лохвиц",
    "лохмат",
)


# Точні образливі слова, для яких не можна використовувати пошук підрядка.
# Джерела для звірки:
# https://github.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words
# https://github.com/kateryna-bobrovnyk/obscene-ukr
# Список адаптовано вручну, щоб прибрати медичні, нейтральні та двозначні слова.
EXACT_SWEAR_WORDS = {
    "asshole",
    "bastard",
    "bullshit",
    "cunt",
    "dickhead",
    "motherfucker",
    "slut",
    "whore",
    "виродок",
    "гнида",
    "дебіл",
    "дебілка",
    "довбень",
    "довбенька",
    "ідіот",
    "ідіотка",
    "лох",
    "лошара",
    "мерзота",
    "мразь",
    "падло",
    "паскуда",
    "покидьок",
    "придурок",
    "придурка",
    "сволота",
    "тварюка",
    "ублюдок",
    "чмо",
}


# =========================
# REGEX
# =========================

LETTER = r"A-Za-zА-Яа-яІіЇїЄєҐґЁё"
SEP = r"[\s\W_]*"

URL_PATTERN = re.compile(
    r"https?://\S+|www\.\S+",
    flags=re.IGNORECASE | re.UNICODE,
)

EXACT_SWEAR_PATTERN = re.compile(
    rf"(?<![{LETTER}])(?:" + "|".join(
        re.escape(word) for word in sorted(EXACT_SWEAR_WORDS, key=len, reverse=True)
    ) + rf")(?![{LETTER}])",
    flags=re.IGNORECASE | re.UNICODE,
)


SWEAR_PATTERNS = [
    # бля / бляд / блять / бляха, але НЕ бляшка
    rf"(?<![{LETTER}])бля(?!ш)[{LETTER}]*",
    rf"(?<![{LETTER}])б{SEP}л{SEP}[яа@](?!{SEP}ш)(?:{SEP}(?:д|т|х|ь|а))*",

    # blya / bljad
    rf"(?<![{LETTER}])blya[a-zа-яіїєґё]*",
    rf"(?<![{LETTER}])bljad[a-zа-яіїєґё]*",
    rf"(?<![{LETTER}])b{SEP}l{SEP}y{SEP}a(?:{SEP}(?:d|t))*",

    # хуй / хуя / хує / хуйню / нахуй / похуй
    rf"(?<![{LETTER}])х[уy][йяєїиеюi][{LETTER}]*",
    rf"(?<![{LETTER}])(?:на|по|за|о)?х[уy][йяєїиеюi][{LETTER}]*",
    rf"(?<![{LETTER}])[хx]{SEP}[уy]{SEP}[йяєїиеюi]",

    # хер
    rf"(?<![{LETTER}])хер[{LETTER}]*",

    # huy / hui / xuy / xui
    rf"(?<![{LETTER}])(?:huy|hui|xuy|xui)[a-zа-яіїєґё]*",
    rf"(?<![{LETTER}])(?:h|x){SEP}u{SEP}(?:y|i)",

    # пизд / пізд / пиздець / піздець
    rf"(?<![{LETTER}])п[иіiы][зz3][дd][{LETTER}]*",
    rf"(?<![{LETTER}])п{SEP}[иіiы]{SEP}[зz3]{SEP}[дd]",
    rf"(?<![{LETTER}])pizd[a-zа-яіїєґё]*",
    rf"(?<![{LETTER}])p{SEP}i{SEP}z{SEP}d",

    # єб / еб / їб / йоб
    rf"(?<![{LETTER}])(?:єб|еб|їб|иб|йоб)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:[еєe]{SEP}[бb]|ї{SEP}[бb]|й{SEP}о{SEP}[бb])",

    # заєб / заїб / зайоб / заеб
    rf"(?<![{LETTER}])за(?:єб|еб|їб|йоб)[{LETTER}]*",
    rf"(?<![{LETTER}])z(?:a|а)(?:eb|yob)[a-zа-яіїєґё]*",

    # сука / суки / суку / сукою / суками, але НЕ сукня і НЕ сукупність
    rf"(?<![{LETTER}])с[уy]к(?:а|и|у|ою|ами|ах|е|о)(?![{LETTER}])",
    rf"(?<![{LETTER}])suka[a-zа-яіїєґё]*",

    # сучка / сучий / сучара
    rf"(?<![{LETTER}])с[уy]ч(?:ка|ки|ку|кою|ара|ари|ий|ого|ому|і|е)[{LETTER}]*",

    # мудак / мудило / мудозвон, але НЕ мудрий
    rf"(?<![{LETTER}])м[уy]д(?:ак|ака|аку|аком|аки|ило|ила|илу|озвон|озвін)[{LETTER}]*",
    rf"(?<![{LETTER}])mudak[a-zа-яіїєґё]*",

    # гівно / говно
    rf"(?<![{LETTER}])г[іиi]вн[{LETTER}]*",
    rf"(?<![{LETTER}])говн[{LETTER}]*",
    rf"(?<![{LETTER}])govn[a-zа-яіїєґё]*",

    # дерьмо
    rf"(?<![{LETTER}])дерь?м[{LETTER}]*",

    # срака / срати / сраний
    rf"(?<![{LETTER}])сра(?:к|т|н)[{LETTER}]*",

    # англійські
    rf"(?<![{LETTER}])fuck[a-zа-яіїєґё]*",
    rf"(?<![{LETTER}])f{SEP}u{SEP}c{SEP}k",
    rf"(?<![{LETTER}])fck[a-zа-яіїєґё]*",
    rf"(?<![{LETTER}])shit[a-zа-яіїєґё]*",
    rf"(?<![{LETTER}])s{SEP}h{SEP}i{SEP}t",
    rf"(?<![{LETTER}])bitch[a-zа-яіїєґё]*",

    # додаткові українські, російські та транслітеровані форми
    rf"(?<![{LETTER}])(?:курв|kurv)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:шлюх|шльондр|shalav)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:піда?р|підор|пидор|pidar|pedik)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:довбойоб|долбо[еє]б|dolboyeb)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:[еєї]блан|йобнут|yobnut)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:залуп|zalup)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:манда|мандовош|manda)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:гандон|gandon)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:жоп|zhop)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:дроч|droch)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:трах|trakh)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:ссать|сцяти|сцик|перд)[{LETTER}]*",
    rf"(?<![{LETTER}])(?:asshole|motherfucker|bastard|cunt|whore|slut|dickhead|bullshit)[a-z]*",

    # повторені літери та розділювачі: бблляя, ххууй, f-u-c-k
    rf"(?<![{LETTER}])б+{SEP}л+{SEP}[яа@]+(?:{SEP}(?:д|т|х|ь|а))*",
    rf"(?<![{LETTER}])[хx]+{SEP}[уy]+{SEP}[йяєїиеюi]+",
    rf"(?<![{LETTER}])п+{SEP}[иіiы]+{SEP}[зz3]+{SEP}[дd]+",
    rf"(?<![{LETTER}])(?:[еєe]+{SEP}[бb]+|ї+{SEP}[бb]+|й+{SEP}о+{SEP}[бb]+)",
    rf"(?<![{LETTER}])f+{SEP}u+{SEP}c+{SEP}k+",
    rf"(?<![{LETTER}])s+{SEP}h+{SEP}i+{SEP}t+",
]


COMPILED_PATTERNS = [
    EXACT_SWEAR_PATTERN,
    *[
        re.compile(pattern, flags=re.IGNORECASE | re.UNICODE)
        for pattern in SWEAR_PATTERNS
    ],
]


# =========================
# ДОПОМІЖНІ ФУНКЦІЇ
# =========================

def current_month_key() -> str:
    now = datetime.now(TIMEZONE)
    return f"{now.year:04d}-{now.month:02d}"


def is_last_day_of_month(now: datetime) -> bool:
    return now.day == monthrange(now.year, now.month)[1]


def compact_word(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", value)

    replacements = {
        "@": "а",
        "0": "о",
        "1": "і",
        "3": "з",
        "$": "с",
        "!": "і",
        "|": "і",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)
    return value


def is_safe_word(value: str) -> bool:
    compact = compact_word(value)

    if compact in SAFE_WORDS:
        return True

    return any(compact.startswith(prefix) for prefix in SAFE_WORD_PREFIXES)


def clean_message_text(text: str) -> tuple[str, int]:
    """
    Чистить тільки звичайний текст.
    URL захищаємо, щоб бот не шукав мат у посиланнях, хешах і параметрах.
    """
    total_count = 0
    protected_urls: list[str] = []

    def protect_url(match: re.Match) -> str:
        protected_urls.append(match.group(0))
        return f"__PROTECTED_URL_{len(protected_urls) - 1}__"

    protected_text = URL_PATTERN.sub(protect_url, text)

    def replace_match(match: re.Match) -> str:
        nonlocal total_count

        original = match.group(0)

        if is_safe_word(original):
            return original

        total_count += 1
        return random.choice(CENSOR_PHRASES)

    cleaned = protected_text

    for pattern in COMPILED_PATTERNS:
        cleaned = pattern.sub(replace_match, cleaned)

    for index, url in enumerate(protected_urls):
        cleaned = cleaned.replace(f"__PROTECTED_URL_{index}__", url)

    return cleaned, total_count


def safe_display_name(member: discord.Member | discord.User) -> str:
    name = getattr(member, "display_name", None) or getattr(member, "name", "User")
    return discord.utils.escape_markdown(name)


def render_mentions_as_names(text: str, guild: discord.Guild | None) -> str:
    """
    Робить з <@123> нормальний @Нік, але без реального пінгу.
    """
    if guild is None:
        return text

    def replace_user(match: re.Match) -> str:
        user_id = int(match.group(1))
        member = guild.get_member(user_id)

        if member:
            return f"@{discord.utils.escape_markdown(member.display_name)}"

        return "@unknown-user"

    def replace_role(match: re.Match) -> str:
        role_id = int(match.group(1))
        role = guild.get_role(role_id)

        if role:
            return f"@{discord.utils.escape_markdown(role.name)}"

        return "@unknown-role"

    def replace_channel(match: re.Match) -> str:
        channel_id = int(match.group(1))
        channel = guild.get_channel(channel_id)

        if channel:
            return f"#{discord.utils.escape_markdown(channel.name)}"

        return "#unknown-channel"

    text = re.sub(r"<@!?(\d+)>", replace_user, text)
    text = re.sub(r"<@&(\d+)>", replace_role, text)
    text = re.sub(r"<#(\d+)>", replace_channel, text)

    return text


def quote_text(text: str) -> str:
    if not text.strip():
        return "> (порожнє повідомлення)"

    lines = text.splitlines()
    return "\n".join(f"> {line}" if line.strip() else ">" for line in lines)


def trim_content(content: str, limit: int = 2000) -> str:
    if len(content) <= limit:
        return content

    suffix = "\n\n...текст обрізано, бо Discord має ліміт 2000 символів."
    return content[: limit - len(suffix)] + suffix


async def collect_attachment_files(message: discord.Message) -> tuple[list[discord.File], list[str]]:
    """
    Читаємо вкладення ДО видалення повідомлення.
    Якщо файл великий або їх забагато - не перезаливаємо, а додаємо URL у failed_urls.
    """
    files: list[discord.File] = []
    failed_urls: list[str] = []

    for attachment in message.attachments:
        try:
            if len(files) >= MAX_REUPLOAD_FILES:
                failed_urls.append(attachment.url)
                continue

            if attachment.size and attachment.size > MAX_REUPLOAD_BYTES:
                failed_urls.append(attachment.url)
                continue

            raw = await attachment.read()
            filename = attachment.filename or "attachment"
            files.append(discord.File(BytesIO(raw), filename=filename))

        except Exception as e:
            failed_urls.append(attachment.url)
            if LOG_TO_CONSOLE:
                print(f"[MATY_OFF] Не вдалося прочитати вкладення {attachment.filename}: {e}")

    return files, failed_urls


# =========================
# COG
# =========================

class MatyOffCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = self.load_data()
        self.processed_message_ids: set[int] = set()
        self.monthly_award_loop.start()

    def cog_unload(self):
        self.monthly_award_loop.cancel()

    # ---------- DATA ----------

    def load_data(self) -> dict:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        if not STATE_FILE.exists():
            return {
                "months": {},
                "awarded_months": [],
                "last_winner_id": None,
            }

        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))

            if not isinstance(data, dict):
                raise ValueError("state file is not dict")

            data.setdefault("months", {})
            data.setdefault("awarded_months", [])
            data.setdefault("last_winner_id", None)

            return data

        except Exception as e:
            if LOG_TO_CONSOLE:
                print(f"[MATY_OFF] Не вдалося прочитати state файл: {e}")

            return {
                "months": {},
                "awarded_months": [],
                "last_winner_id": None,
            }

    def save_data(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_swear_count(self, member: discord.Member, count: int):
        if count <= 0:
            return

        month = current_month_key()
        user_id = str(member.id)

        self.data.setdefault("months", {})
        self.data["months"].setdefault(month, {})
        self.data["months"][month].setdefault(user_id, {
            "count": 0,
            "name": member.display_name,
        })

        self.data["months"][month][user_id]["count"] += count
        self.data["months"][month][user_id]["name"] = member.display_name

        self.save_data()

    def get_month_top(self, month: str) -> list[tuple[str, dict]]:
        month_data = self.data.get("months", {}).get(month, {})

        return sorted(
            month_data.items(),
            key=lambda item: int(item[1].get("count", 0)),
            reverse=True,
        )

    # ---------- FILTERS ----------

    def is_watched_channel(self, channel: discord.abc.GuildChannel) -> bool:
        if not WATCH_CHANNEL_IDS:
            return True

        return channel.id in WATCH_CHANNEL_IDS

    def is_ignored_user(self, member: discord.Member) -> bool:
        if IGNORE_ADMINS and member.guild_permissions.manage_messages:
            return True

        if IGNORE_ROLE_IDS:
            user_role_ids = {role.id for role in member.roles}

            if user_role_ids & IGNORE_ROLE_IDS:
                return True

        return False

    # ---------- MESSAGE LISTENER ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return

        if message.author.bot:
            return

        # Захист від подвійної обробки одного й того самого повідомлення
        if message.id in self.processed_message_ids:
            if LOG_TO_CONSOLE:
                print(f"[MATY_OFF_DUPLICATE_SKIP] msg_id={message.id}")
            return

        self.processed_message_ids.add(message.id)

        # Щоб set не ріс безкінечно
        if len(self.processed_message_ids) > 5000:
            self.processed_message_ids.clear()

        if not isinstance(message.author, discord.Member):
            return

        if not self.is_watched_channel(message.channel):
            return

        if self.is_ignored_user(message.author):
            return

        # Якщо тексту немає, а є тільки картинка/файл - не чіпаємо
        if not message.content.strip():
            return

        cleaned_text, swear_count = clean_message_text(message.content)

        if swear_count <= 0:
            return

        self.add_swear_count(message.author, swear_count)

        # Вкладення читаємо ДО видалення повідомлення
        files, failed_urls = await collect_attachment_files(message)

        if LOG_TO_CONSOLE:
            print(
                f"[MATY_OFF] guild={message.guild.name} "
                f"channel=#{getattr(message.channel, 'name', 'unknown')} "
                f"user={message.author} "
                f"msg_id={message.id} "
                f"count={swear_count} "
                f"original={message.content!r} "
                f"cleaned={cleaned_text!r}"
            )

        if DELETE_ORIGINAL_MESSAGE:
            try:
                await message.delete()
            except discord.Forbidden:
                if LOG_TO_CONSOLE:
                    print("[MATY_OFF] Немає прав видалити повідомлення.")
            except discord.HTTPException as e:
                if LOG_TO_CONSOLE:
                    print(f"[MATY_OFF] Помилка видалення повідомлення: {e}")

        if not SEND_CLEAN_COPY:
            return

        author_name = safe_display_name(message.author)

        cleaned_text = render_mentions_as_names(cleaned_text, message.guild)
        warning = random.choice(WARNING_PHRASES)

        failed_block = ""
        if failed_urls:
            failed_lines = "\n".join(failed_urls)
            failed_block = f"\n\nВкладення, які не вдалося перезалити:\n{failed_lines}"

        quoted = quote_text(cleaned_text + failed_block)

        content = (
            f"**{author_name} написав/написала:**\n"
            f"{quoted}\n\n"
            f"{warning}"
        )

        content = trim_content(content)

        try:
            send_kwargs = {
                "content": content,
                "allowed_mentions": discord.AllowedMentions.none(),
            }

            if files:
                send_kwargs["files"] = files

            await message.channel.send(**send_kwargs)

        except discord.HTTPException as e:
            if LOG_TO_CONSOLE:
                print(f"[MATY_OFF] Помилка відправки з файлами: {e}")

            try:
                await message.channel.send(
                    content=content,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except Exception as e2:
                if LOG_TO_CONSOLE:
                    print(f"[MATY_OFF] Помилка відправки без файлів: {e2}")

    # ---------- MONTHLY AWARD ----------

    @tasks.loop(minutes=30)
    async def monthly_award_loop(self):
        now = datetime.now(TIMEZONE)

        if not is_last_day_of_month(now):
            return

        if now.hour < AWARD_HOUR:
            return

        month = f"{now.year:04d}-{now.month:02d}"

        self.data.setdefault("awarded_months", [])

        if month in self.data["awarded_months"]:
            return

        await self.give_monthly_award(month)

    @monthly_award_loop.before_loop
    async def before_monthly_award_loop(self):
        await self.bot.wait_until_ready()

    async def give_monthly_award(self, month: str):
        top = self.get_month_top(month)

        if not top:
            if LOG_TO_CONSOLE:
                print(f"[MATY_OFF] За {month} немає статистики.")
            return

        winner_id_str, winner_data = top[0]
        winner_id = int(winner_id_str)
        winner_count = int(winner_data.get("count", 0))
        winner_name = winner_data.get("name", f"User {winner_id}")

        channel = self.bot.get_channel(AWARD_CHANNEL_ID)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(AWARD_CHANNEL_ID)
            except Exception as e:
                if LOG_TO_CONSOLE:
                    print(f"[MATY_OFF] Не вдалося знайти award channel: {e}")
                return

        guild = getattr(channel, "guild", None)
        winner_member = None

        if guild:
            winner_member = guild.get_member(winner_id)

            if winner_member is None:
                try:
                    winner_member = await guild.fetch_member(winner_id)
                except Exception:
                    winner_member = None

        # Роль переможцю, якщо AWARD_ROLE_ID прописаний
        if guild and AWARD_ROLE_ID:
            role = guild.get_role(AWARD_ROLE_ID)

            if role:
                previous_winner_id = self.data.get("last_winner_id")

                if previous_winner_id:
                    previous_member = guild.get_member(int(previous_winner_id))

                    if previous_member and role in previous_member.roles:
                        try:
                            await previous_member.remove_roles(
                                role,
                                reason="Нова місячна ганьба матюкливості",
                            )
                        except Exception as e:
                            if LOG_TO_CONSOLE:
                                print(f"[MATY_OFF] Не вдалося зняти роль: {e}")

                if winner_member:
                    try:
                        await winner_member.add_roles(
                            role,
                            reason="Переможець місячної ганьби матюкливості",
                        )
                    except Exception as e:
                        if LOG_TO_CONSOLE:
                            print(f"[MATY_OFF] Не вдалося видати роль: {e}")

        if winner_member:
            winner_display = f"@{discord.utils.escape_markdown(winner_member.display_name)}"
        else:
            winner_display = discord.utils.escape_markdown(winner_name)

        embed = discord.Embed(
            title="Почесна ганьба місяця",
            description=(
                f"**{AWARD_TITLE}**\n\n"
                f"Титул отримує: {winner_display}\n"
                f"Зафіксовано некультурних слів: **{winner_count}**\n\n"
                f"Муха все бачила.\n"
                f"Муха все записала.\n"
                f"Муха розчаровано поставила печатку."
            ),
            color=discord.Color.dark_gold(),
        )

        embed.set_footer(text=f"Місяць: {month}")

        try:
            await channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            if LOG_TO_CONSOLE:
                print(f"[MATY_OFF] Помилка відправки нагороди: {e}")
            return

        self.data.setdefault("awarded_months", [])
        self.data["awarded_months"].append(month)
        self.data["last_winner_id"] = winner_id
        self.save_data()

        if LOG_TO_CONSOLE:
            print(
                f"[MATY_OFF] Нагорода за {month}: "
                f"{winner_name} ({winner_id}) - {winner_count}"
            )

    # ---------- COMMANDS ----------

    @commands.command(name="маттоп", aliases=["mat_top", "swear_top"])
    async def swear_top_command(self, ctx: commands.Context):
        month = current_month_key()
        top = self.get_month_top(month)

        if not top:
            await ctx.reply(
                "За цей місяць ще немає зафіксованих некультурних слів. Підозріло культурно.",
                mention_author=False,
            )
            return

        lines = []

        for index, (user_id, data) in enumerate(top[:10], start=1):
            name = discord.utils.escape_markdown(data.get("name", f"User {user_id}"))
            count = int(data.get("count", 0))
            lines.append(f"{index}. {name} - {count}")

        embed = discord.Embed(
            title="Топ лайливих талантів місяця",
            description="\n".join(lines),
            color=discord.Color.dark_gold(),
        )

        embed.set_footer(text=f"Місяць: {month}")

        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="матстат", aliases=["mat_stat", "swear_stat"])
    async def swear_stat_command(
        self,
        ctx: commands.Context,
        member: discord.Member | None = None,
    ):
        member = member or ctx.author
        month = current_month_key()

        month_data = self.data.get("months", {}).get(month, {})
        user_data = month_data.get(str(member.id), {})
        count = int(user_data.get("count", 0))

        name = discord.utils.escape_markdown(member.display_name)

        await ctx.reply(
            f"{name} має зафіксованих некультурних слів за цей місяць: **{count}**.",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="матнагорода", aliases=["mat_award", "swear_award"])
    @commands.has_permissions(manage_guild=True)
    async def force_award_command(self, ctx: commands.Context):
        month = current_month_key()
        await self.give_monthly_award(month)

        await ctx.reply(
            "Нагороду примусово перевірено.",
            mention_author=False,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(MatyOffCog(bot))
