# -*- coding: utf-8 -*-
# cogs/maty_off_cog.py

import json
import random
import re
from calendar import monthrange
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks


STATE_FILE = Path("data/maty_off_stats.json")

TIMEZONE = ZoneInfo("Europe/London")

AWARD_CHANNEL_ID = 1331734685683945523
AWARD_HOUR = 21
AWARD_MINUTE = 0

DELETE_ORIGINAL_MESSAGE = True
SEND_CLEAN_COPY = True

IGNORE_ADMINS = False
LOG_TO_CONSOLE = True

WATCH_CHANNEL_IDS: set[int] = set()
IGNORE_ROLE_IDS: set[int] = set()

AWARD_ROLE_ID: int | None = None

AWARD_TITLE = "Великий Магістр Матюка - Почесний Пʼю Лайливого Мистецтва"


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
]


LETTER = r"A-Za-zА-Яа-яІіЇїЄєҐґЁё"
SEP = r"[\s\W_]*"

SWEAR_PATTERNS = [
    # бля / бляд / блять
    rf"(?<![{LETTER}])б{SEP}л{SEP}[яа@]{SEP}(?:д|т|х)?[{LETTER}]*",

    # blya / bljad
    rf"(?<![{LETTER}])b{SEP}l{SEP}(?:y|j)?{SEP}a{SEP}(?:d|t)?[{LETTER}]*",

    # хуй / хуя / хує / хер
    rf"(?<![{LETTER}])[хx]{SEP}[уy]{SEP}[йяєїиеюi][{LETTER}]*",
    rf"(?<![{LETTER}])х{SEP}е{SEP}р[{LETTER}]*",

    # huy / hui
    rf"(?<![{LETTER}])h{SEP}u{SEP}[yi][{LETTER}]*",
    rf"(?<![{LETTER}])x{SEP}u{SEP}[yi][{LETTER}]*",

    # пизд / пізд / пиздець
    rf"(?<![{LETTER}])п{SEP}[иіiы]{SEP}[зz3]{SEP}[дd][{LETTER}]*",
    rf"(?<![{LETTER}])p{SEP}i{SEP}z{SEP}d[{LETTER}]*",

    # єб / еб / їб / йоб
    rf"(?<![{LETTER}])(?:[еєe]{SEP}[бb]|ї{SEP}[бb]|й{SEP}о{SEP}[бb])[{LETTER}]*",

    # заєб / заїб / зайоб
    rf"(?<![{LETTER}])з{SEP}а{SEP}(?:[еєeї]{SEP}[бb]|й{SEP}о{SEP}[бb])[{LETTER}]*",
    rf"(?<![{LETTER}])z{SEP}a{SEP}(?:e{SEP}b|y{SEP}o{SEP}b)[{LETTER}]*",

    # сука / суки / суку, але НЕ сукня
    rf"(?<![{LETTER}])с{SEP}[уy]{SEP}к{SEP}[аоиуеі][{LETTER}]*",

    # сучка / сучий / сучара
    rf"(?<![{LETTER}])с{SEP}[уy]{SEP}ч{SEP}(?:к|ар|ий|а|е|і)[{LETTER}]*",

    # мудак / мудило / мудозвон, але НЕ мудрий
    rf"(?<![{LETTER}])м{SEP}[уy]{SEP}д{SEP}(?:а{SEP}к|и{SEP}л|о{SEP}з|н{SEP}[яею])[{LETTER}]*",

    # гівно / говно
    rf"(?<![{LETTER}])г{SEP}[іиiоo]{SEP}в{SEP}н[{LETTER}]*",

    # дерьмо
    rf"(?<![{LETTER}])д{SEP}е{SEP}р{SEP}ь?{SEP}м[{LETTER}]*",

    # срака / срати / сраний
    rf"(?<![{LETTER}])с{SEP}р{SEP}а{SEP}(?:к|т|н)[{LETTER}]*",

    # англійські
    rf"(?<![{LETTER}])f{SEP}u{SEP}c{SEP}k[{LETTER}]*",
    rf"(?<![{LETTER}])f{SEP}c{SEP}k[{LETTER}]*",
    rf"(?<![{LETTER}])s{SEP}h{SEP}i{SEP}t[{LETTER}]*",
    rf"(?<![{LETTER}])b{SEP}i{SEP}t{SEP}c{SEP}h[{LETTER}]*",
]


COMPILED_PATTERNS = [
    re.compile(pattern, flags=re.IGNORECASE | re.UNICODE)
    for pattern in SWEAR_PATTERNS
]


def current_month_key() -> str:
    now = datetime.now(TIMEZONE)
    return f"{now.year:04d}-{now.month:02d}"


def is_last_day_of_month(now: datetime) -> bool:
    return now.day == monthrange(now.year, now.month)[1]


def clean_message_text(text: str) -> tuple[str, int]:
    total_count = 0

    def replace_match(match: re.Match) -> str:
        nonlocal total_count
        total_count += 1
        return random.choice(CENSOR_PHRASES)

    cleaned = text

    for pattern in COMPILED_PATTERNS:
        cleaned = pattern.sub(replace_match, cleaned)

    return cleaned, total_count


def safe_display_name(member: discord.Member | discord.User) -> str:
    return discord.utils.escape_markdown(member.display_name)


async def collect_attachment_files(message: discord.Message) -> tuple[list[discord.File], list[str]]:
    files: list[discord.File] = []
    failed_urls: list[str] = []

    for attachment in message.attachments:
        try:
            raw = await attachment.read()
            filename = attachment.filename or "attachment"
            files.append(discord.File(BytesIO(raw), filename=filename))
        except Exception as e:
            failed_urls.append(attachment.url)
            if LOG_TO_CONSOLE:
                print(f"[MATY_OFF] Не вдалося прочитати вкладення {attachment.filename}: {e}")

    return files, failed_urls


class MatyOffCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = self.load_data()
        self.processed_message_ids: set[int] = set()
        self.monthly_award_loop.start()

    def cog_unload(self):
        self.monthly_award_loop.cancel()

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild:
            return

        if message.author.bot:
            return

        if message.id in self.processed_message_ids:
            if LOG_TO_CONSOLE:
                print(f"[MATY_OFF_DUPLICATE_SKIP] msg_id={message.id}")
            return

        self.processed_message_ids.add(message.id)

        if len(self.processed_message_ids) > 5000:
            self.processed_message_ids.clear()

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
        warning = random.choice(WARNING_PHRASES)

        failed_block = ""
        if failed_urls:
            failed_block = "\n\nВкладення, які не вдалося перезалити:\n" + "\n".join(failed_urls)

        content = (
            f"**{author_name} написав/написала:**\n"
            f"> {cleaned_text}{failed_block}\n\n"
            f"{warning}"
        )

        try:
            await message.channel.send(
                content=content[:2000],
                files=files,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            if LOG_TO_CONSOLE:
                print(f"[MATY_OFF] Помилка відправки з файлами: {e}")

            try:
                await message.channel.send(
                    content=content[:2000],
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except Exception as e2:
                if LOG_TO_CONSOLE:
                    print(f"[MATY_OFF] Помилка відправки без файлів: {e2}")

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

        mention = f"<@{winner_id}>" if winner_member else discord.utils.escape_markdown(winner_name)

        embed = discord.Embed(
            title="Почесна ганьба місяця",
            description=(
                f"**{AWARD_TITLE}**\n\n"
                f"Титул отримує: {mention}\n"
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
    async def swear_stat_command(self, ctx: commands.Context, member: discord.Member | None = None):
        member = member or ctx.author
        month = current_month_key()

        month_data = self.data.get("months", {}).get(month, {})
        user_data = month_data.get(str(member.id), {})
        count = int(user_data.get("count", 0))

        await ctx.reply(
            f"{discord.utils.escape_markdown(member.display_name)} має зафіксованих некультурних слів за цей місяць: **{count}**.",
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
