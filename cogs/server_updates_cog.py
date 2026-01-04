# bot.py
import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks
from discord import app_commands

# ===== Налаштування =====
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ DISCORD_TOKEN не знайдено в оточенні.")

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

# Таймзона і «тихі години»
TZ = ZoneInfo("Europe/London")
QUIET_START_HOUR = 23
QUIET_END_HOUR = 6

# Канал для новин
NEWS_CHANNEL_ID = 1370858832531820678

# Категорії, які треба ігнорувати
IGNORED_CATEGORIES = {
    1407668107379736708,
    1324007042532245504,
    1393917180466167939,
}

# Роль для DM
notify_role_id: int | None = None

# Файл для збереження відкладених новин
PENDING_FILE = "pending_news.json"
pending_news: list[dict] = []


# ===== Збереження/завантаження =====
def load_pending():
    global pending_news
    if os.path.exists(PENDING_FILE):
        try:
            with open(PENDING_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                pending_news = data
        except Exception:
            pending_news = []


def save_pending():
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(pending_news, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ===== Часові утиліти =====
def is_quiet_hours(dt_local: datetime) -> bool:
    hour = dt_local.hour
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


def next_morning_six(dt_local: datetime) -> datetime:
    six_today = dt_local.replace(hour=6, minute=0, second=0, microsecond=0)
    if dt_local.hour < QUIET_END_HOUR:
        return six_today
    return six_today + timedelta(days=1)


# ===== Embed =====
def add_footer(embed: discord.Embed) -> discord.Embed:
    if bot.user and bot.user.avatar:
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=bot.user.avatar.url)
    else:
        embed.set_footer(text="Silent Concierge by Myxa")
    return embed


def build_news_embed(guild: discord.Guild, channel: discord.abc.GuildChannel) -> discord.Embed:
    embed_news = discord.Embed(
        title="📢 НОВИЙ КАНАЛ!",
        description=f"На сервері **{guild.name}** створено новий канал: {channel.mention}",
        color=discord.Color.teal()
    )
    embed_news.add_field(name="Тип", value=str(channel.type).capitalize(), inline=True)
    embed_news.add_field(
        name="Інструкція",
        value="👉 Щоб приховати канал: ПКМ → *Hide* або налаштуй сповіщення.",
        inline=False
    )
    return add_footer(embed_news)


def build_dm_embed(channel: discord.abc.GuildChannel) -> discord.Embed:
    embed_dm = discord.Embed(
        title="🔔 Оновлення сервера",
        description=f"Створено новий канал: {channel.mention}",
        color=discord.Color.gold()
    )
    embed_dm.add_field(name="Тип", value=str(channel.type).capitalize(), inline=True)
    embed_dm.add_field(
        name="Порада",
        value="Можна приховати цей канал: ПКМ по каналу → *Hide*.",
        inline=False
    )
    return add_footer(embed_dm)


# ===== Надсилання =====
async def send_news_and_dms(guild: discord.Guild, embed: discord.Embed):
    # У новинний канал
    news_channel = guild.get_channel(NEWS_CHANNEL_ID)
    if news_channel and isinstance(news_channel, discord.TextChannel):
        await news_channel.send(embed=embed)

    # У ДМ
    if notify_role_id:
        role = guild.get_role(notify_role_id)
        if role:
            for member in role.members:
                if member.bot:
                    continue
                try:
                    await member.send(embed=embed)
                except:
                    continue


# ===== Команди =====
@bot.tree.command(name="set_notify_role", description="Вказати роль, яка отримує DM про оновлення")
@app_commands.describe(role="Роль для DM")
@app_commands.checks.has_permissions(administrator=True)
async def set_notify_role(interaction: discord.Interaction, role: discord.Role):
    global notify_role_id
    notify_role_id = role.id
    await interaction.response.send_message(
        f"✅ Роль для DM встановлено: {role.mention}", ephemeral=True
    )


@set_notify_role.error
async def set_notify_role_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("❌ Потрібні права адміністратора.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Сталася помилка.", ephemeral=True)


@bot.tree.command(name="announce_update", description="Створити новину про оновлення вручну")
@app_commands.describe(title="Заголовок новини", description="Опис/текст новини")
@app_commands.checks.has_permissions(administrator=True)
async def announce_update(interaction: discord.Interaction, title: str, description: str):
    guild = interaction.guild
    embed = discord.Embed(
        title=f"📢 {title}",
        description=description,
        color=discord.Color.blue()
    )
    embed = add_footer(embed)

    await send_news_and_dms(guild, embed)
    await interaction.response.send_message("✅ Новину опубліковано!", ephemeral=True)


# ===== Події =====
@bot.event
async def on_ready():
    load_pending()
    try:
        await bot.tree.sync()
    except Exception:
        pass
    if not nightly_dispatcher.is_running():
        nightly_dispatcher.start()
    print(f"✅ Бот {bot.user} запущено!")


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    guild = channel.guild
    now_local = datetime.now(TZ)

    # --- Ігноруємо категорії ---
    if channel.category and channel.category.id in IGNORED_CATEGORIES:
        return

    embed = build_news_embed(guild, channel)

    if is_quiet_hours(now_local):
        scheduled = next_morning_six(now_local)
        item = {
            "guild_id": guild.id,
            "embed": embed.to_dict(),  # збережемо embed у dict
            "scheduled_at_iso": scheduled.isoformat(),
        }
        pending_news.append(item)
        save_pending()
    else:
        await send_news_and_dms(guild, embed)


# ===== Планувальник =====
@tasks.loop(seconds=60)
async def nightly_dispatcher():
    if not pending_news:
        return

    now_local = datetime.now(TZ)
    due_indices = []

    for idx, item in enumerate(pending_news):
        try:
            scheduled_at = datetime.fromisoformat(item["scheduled_at_iso"])
        except:
            due_indices.append(idx)
            continue

        if now_local >= scheduled_at:
            guild = bot.get_guild(item["guild_id"])
            if guild is None:
                due_indices.append(idx)
                continue

            try:
                embed = discord.Embed.from_dict(item["embed"])
                await send_news_and_dms(guild, embed)
            finally:
                due_indices.append(idx)

    if due_indices:
        for i in sorted(due_indices, reverse=True):
            pending_news.pop(i)
        save_pending()


# ===== Запуск =====
if __name__ == "__main__":
    bot.run(TOKEN)