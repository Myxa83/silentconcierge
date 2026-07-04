# -*- coding: utf-8 -*-
# cogs/anti_swear_cog.py

import json
import random
import re
import unicodedata
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks


# =========================
# НАЛАШТУВАННЯ
# =========================

STATE_FILE = Path("data/anti_swear_stats.json")

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

# Якщо хочеш видати роль переможцю місяця - створи роль у Discord і встав ID сюди
# Якщо не треба роль - лишай None
AWARD_ROLE_ID: int | None = None


# =========================
# ТИТУЛ
# =========================

AWARD_TITLE = "Великий Магістр Матюка - Почесний Пʼю Лайливого Мистецтва"


# =========================
# ФРАЗИ ДЛЯ ЗАМІНИ МАТЮКІВ
# =========================

CENSOR_PHRASES = [
    "(Муха закрила вуха)",
    "(ай-ай-яй)",
    "(цензура від Мухи)",
    "(ротик під наглядом)",
    "(словниковий злочин)",
    "(куточок уже чекає)",
    "(Муха це бачила)",
    "(тут мав бути матюк, але Муха проти)",
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
    "Матюк зафіксовано. Муха незадоволено дивиться.",
    "Словниковий патруль прибув.",
    "Так-так-так... це що за мовний демон виліз.",
    "Муха записала. Муха запамʼятала.",
    "Ще трохи - і ротик піде на техобслуговування.",
]


# =========================
# МАТЮКИ / КОРЕНІ
# =========================
# Працює по коренях, тому ловить різні відмінки:
# бля, бляха, блядський, блядство
# хуй, хуя, хуєвий, хуйню
# пизд, пізд, пиздець, піздець
# їб, єб, еб, йоб, заїб, заєб
# і так далі

SWEAR_PATTERNS = [
    # бля / бляд
    r"б\s*л\s*[яа]\s*(?:д|т)?\s*[а-яіїєґёa-z]*",
    r"b\s*l\s*y\s*a\s*[a-zа-яіїєґё]*",
    r"b\s*l\s*j\s*a\s*[a-zа-яіїєґё]*",

    # хуй / хуя / хує
    r"х\s*[уy]\s*[йяєеїи]\s*[а-яіїєґёa-z]*",
    r"h\s*u\s*y\s*[a-zа-яіїєґё]*",
    r"h\s*u\s*i\s*[a-zа-яіїєґё]*",
    r"x\s*u\s*y\s*[a-zа-яіїєґё]*",
    r"x\s*u\s*i\s*[a-zа-яіїєґё]*",

    # пизд / пізд / пзд
    r"п\s*[иіi]\s*з\s*д\s*[а-яіїєґёa-z]*",
    r"п\s*з\s*д\s*[а-яіїєґёa-z]*",
    r"p\s*i\s*z\s*d\s*[a-zа-яіїєґё]*",
    r"p\s*i\s*z\s*d\s*e\s*c\s*[a-zа-яіїєґё]*",

    # єб / еб / їб / йоб
    r"[еєїиі]\s*б\s*[а-яіїєґёa-z]*",
    r"й\s*о\s*б\s*[а-яіїєґёa-z]*",
    r"y\s*o\s*b\s*[a-zа-яіїєґё]*",
    r"e\s*b\s*[a-zа-яіїєґё]*",

    # заєб / заїб / зайоб
    r"з\s*а\s*[еєїиі]\s*б\s*[а-яіїєґёa-z]*",
    r"з\s*а\s*й\s*о\s*б\s*[а-яіїєґёa-z]*",
    r"z\s*a\s*e\s*b\s*[a-zа-яіїєґё]*",
    r"z\s*a\s*y\s*o\s*b\s*[a-zа-яіїєґё]*",

    # сука / суч
    r"с\s*[уy]\s*к\s*[а-яіїєґёa-z]*",
    r"с\s*[уy]\s*ч\s*[а-яіїєґёa-z]*",
    r"s\s*u\s*k\s*a\s*[a-zа-яіїєґё]*",

    # мудак / мудил
    r"м\s*[уy]\s*д\s*[а-яіїєґёa-z]*",
    r"m\s*u\s*d\s*a\s*k\s*[a-zа-яіїєґё]*",

    # гівно / говно
    r"г\s*[іиiоo]\s*в\s*н\s*[а-яіїєґёa-z]*",
    r"g\s*o\s*v\s*n\s*[a-zа-яіїєґё]*",

    # срака / срати / сраний
    r"с\s*р\s*[аa]\s*[а-яіїєґёa-z]*",

    # англ
    r"f\s*u\s*c\s*k\s*[a-zа-яіїєґё]*",
    r"f\s*c\s*k\s*[a-zа-яіїєґё]*",
    r"s\s*h\s*i\s*t\s*[a-zа-яіїєґё]*",
    r"b\s*i\s*t\s*c\s*h\s*[a-zа-яіїєґё]*",
]


# =========================
# ДОПОМІЖНІ ФУНКЦІЇ
# =========================

def normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return text


def make_regex(pattern: str) -> re.Pattern:
    return re.compile(
        pattern,
        flags=re.IGNORECASE | re.UNICODE,
    )


COMPILED_PATTERNS = [make_regex(pattern) for pattern in SWEAR_PATTERNS]


def current_month_key() -> str:
    now = datetime.now(TIMEZONE)
    return f"{now.year:04d}-{now.month:02d}"


def is_last_day_of_month(now: datetime) -> bool:
    last_day = monthrange(now.year, now.month)[1]
    return now.day == last_day


def clean_message_text(text: str) -> tuple[str, int]:
    """
    Повертає:
    - очищений текст
    - кількість знайдених матюків
    """
    text = normalize_unicode(text)

    total_count = 0

    def replacement(match: re.Match) -> str:
        nonlocal total_count
        total_count += 1
        return random.choice(CENSOR_PHRASES)

    cleaned = text

    for pattern in COMPILED_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)

    return cleaned, total_count


def safe_user_name(member: discord.Member | discord.User) -> str:
    name = getattr(member, "display_name", None) or member.name
    return discord.utils.escape_mentions(name)


# =========================
# COG
# =========================

class AntiSwearCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = self.load_data()
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
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            if LOG_TO_CONSOLE:
                print(f"[ANTI-SWEAR] Не вдалося прочитати state файл: {e}")

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

        self.data.setdefault("months", {})
        self.data["months"].setdefault(month, {})
        self.data["months"][month].setdefault(str(member.id), {
            "count": 0,
            "name": member.display_name,
        })

        self.data["months"][month][str(member.id)]["count"] += count
        self.data["months"][month][str(member.id)]["name"] = member.display_name

        self.save_data()

    def get_month_top(self, month: str) -> list[tuple[str, dict]]:
        month_data = self.data.get("months", {}).get(month, {})

        return sorted(
            month_data.items(),
            key=lambda item: item[1].get("count", 0),
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

        if not isinstance(message.author, discord.Member):
            return

        if not self.is_watched_channel(message.channel):
            return

        if self.is_ignored_user(message.author):
            return

        cleaned_text, swear_count = clean_message_text(message.content)

        if swear_count <= 0:
            return

        self.add_swear_count(message.author, swear_count)

        if LOG_TO_CONSOLE:
            print(
                f"[ANTI-SWEAR] Guild={message.guild.name} "
                f"Channel=#{getattr(message.channel, 'name', 'unknown')} "
                f"User={message.author} "
                f"Count={swear_count} "
                f"Original={message.content!r} "
                f"Cleaned={cleaned_text!r}"
            )

        author_name = safe_user_name(message.author)
        warning = random.choice(WARNING_PHRASES)

        # Discord не дозволяє редагувати чужі повідомлення.
        # Тому видаляємо оригінал і публікуємо очищену копію.
        if DELETE_ORIGINAL_MESSAGE:
            try:
                await message.delete()
            except discord.Forbidden:
                if LOG_TO_CONSOLE:
                    print("[ANTI-SWEAR] Немає прав видалити повідомлення.")
            except discord.HTTPException as e:
                if LOG_TO_CONSOLE:
                    print(f"[ANTI-SWEAR] Помилка видалення повідомлення: {e}")

        if not SEND_CLEAN_COPY:
            return

        cleaned_text = discord.utils.escape_mentions(cleaned_text)

        attachment_text = ""
        if message.attachments:
            urls = "\n".join(attachment.url for attachment in message.attachments)
            attachment_text = f"\n\nВкладення:\n{urls}"

        content = (
            f"**{author_name} написав/написала:**\n"
            f"> {cleaned_text}{attachment_text}\n\n"
            f"{warning}"
        )

        try:
            await message.channel.send(
                content,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            if LOG_TO_CONSOLE:
                print("[ANTI-SWEAR] Немає прав написати в канал.")
        except discord.HTTPException as e:
            if LOG_TO_CONSOLE:
                print(f"[ANTI-SWEAR] Помилка відправки очищеної копії: {e}")

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
                print(f"[ANTI-SWEAR] За {month} немає статистики.")
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
                    print(f"[ANTI-SWEAR] Не вдалося знайти award channel: {e}")
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
                                print(f"[ANTI-SWEAR] Не вдалося зняти роль: {e}")

                if winner_member:
                    try:
                        await winner_member.add_roles(
                            role,
                            reason="Переможець місячної ганьби матюкливості",
                        )
                    except Exception as e:
                        if LOG_TO_CONSOLE:
                            print(f"[ANTI-SWEAR] Не вдалося видати роль: {e}")

        mention = f"<@{winner_id}>" if winner_member else discord.utils.escape_mentions(winner_name)

        embed = discord.Embed(
            title="Почесна ганьба місяця",
            description=(
                f"**{AWARD_TITLE}**\n\n"
                f"Титул отримує: {mention}\n"
                f"Зафіксовано матюків: **{winner_count}**\n\n"
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
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except discord.Forbidden:
            if LOG_TO_CONSOLE:
                print("[ANTI-SWEAR] Немає прав написати нагороду в канал.")
            return
        except discord.HTTPException as e:
            if LOG_TO_CONSOLE:
                print(f"[ANTI-SWEAR] Помилка відправки нагороди: {e}")
            return

        self.data["awarded_months"].append(month)
        self.data["last_winner_id"] = winner_id
        self.save_data()

        if LOG_TO_CONSOLE:
            print(
                f"[ANTI-SWEAR] Нагорода за {month}: "
                f"{winner_name} ({winner_id}) - {winner_count}"
            )

    # ---------- COMMANDS ----------

    @commands.command(name="маттоп", aliases=["mat_top", "swear_top"])
    async def swear_top_command(self, ctx: commands.Context):
        month = current_month_key()
        top = self.get_month_top(month)

        if not top:
            await ctx.reply(
                "За цей місяць ще немає зафіксованих матюків. Підозріло культурно.",
                mention_author=False,
            )
            return

        lines = []
        for index, (user_id, data) in enumerate(top[:10], start=1):
            name = data.get("name", f"User {user_id}")
            count = data.get("count", 0)
            lines.append(f"{index}. {discord.utils.escape_mentions(name)} - {count}")

        embed = discord.Embed(
            title="Топ лайливих талантів місяця",
            description="\n".join(lines),
            color=discord.Color.dark_gold(),
        )

        embed.set_footer(text=f"Місяць: {month}")

        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="матстат", aliases=["mat_stat", "swear_stat"])
    async def swear_stat_command(self, ctx: commands.Context, member: discord.Member | None = None):
        member = member or ctx.author
        month = current_month_key()

        month_data = self.data.get("months", {}).get(month, {})
        user_data = month_data.get(str(member.id), {})
        count = user_data.get("count", 0)

        await ctx.reply(
            f"{member.display_name} має матюків за цей місяць: **{count}**.",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="матнагорода", aliases=["mat_award", "swear_award"])
    @commands.has_permissions(manage_guild=True)
    async def force_award_command(self, ctx: commands.Context):
        """
        Ручний тест нагороди.
        Команда тільки для тих, у кого є Manage Server.
        """
        month = current_month_key()
        await self.give_monthly_award(month)
        await ctx.reply(
            "Нагороду примусово перевірено.",
            mention_author=False,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiSwearCog(bot))
