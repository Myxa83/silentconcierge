# bot_message_report.py
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True  # потрібно для підрахунку повідомлень

bot = commands.Bot(command_prefix="!", intents=intents)

# ===== Налаштування =====
TZ = ZoneInfo("Europe/London")

ALLOWED_CATEGORIES = {
    1323454228261245008,
    1324134662561468426,
    1407668107379736708,
}

IGNORED_CHANNELS = {
    1324455325910306848,
    1338860224282366022,
    1324986848866599004,
    1370858832531820678,
    1324983966381637643,
    1361710729182314646,
}

ROLE_ID = 1383410423704846396
REPORT_CHANNEL_ID = 1419243900140392498
TOP_THREAD_ID = 1419272978926927883

# { user_id: {"daily": int, "monthly": int} }
message_stats = {}


@bot.event
async def on_ready():
    if not daily_report.is_running():
        daily_report.start()
    if not monthly_report.is_running():
        monthly_report.start()
    print(f"✅ Бот {bot.user} запущено!")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    guild = message.guild
    if not guild:
        return

    role = guild.get_role(ROLE_ID)
    if not role or role not in message.author.roles:
        return

    # Перевірка категорій і каналів
    if not message.channel.category or message.channel.category.id not in ALLOWED_CATEGORIES:
        return
    if message.channel.id in IGNORED_CHANNELS:
        return

    # Запис у статистику
    stats = message_stats.setdefault(message.author.id, {"daily": 0, "monthly": 0})
    stats["daily"] += 1
    stats["monthly"] += 1


@tasks.loop(minutes=1)
async def daily_report():
    now = datetime.now(TZ)
    if now.hour == 0 and now.minute == 0:
        await send_daily_report(now.date() - timedelta(days=1))


async def send_daily_report(report_date: datetime.date):
    channel = bot.get_channel(REPORT_CHANNEL_ID)
    if not channel:
        return

    lines = [f"💬 Звіт за {report_date.strftime('%d.%m.%Y')}"]

    for user_id, data in list(message_stats.items()):
        count = data["daily"]
        if count > 0:
            user = bot.get_user(user_id)
            name = user.display_name if user else f"User {user_id}"
            lines.append(f"- {name} — {count} повідомлень")
        data["daily"] = 0  # обнулення добової статистики

    if len(lines) == 1:
        lines.append("Ніхто не писав повідомлень сьогодні.")

    await channel.send("\n".join(lines))


@tasks.loop(hours=1)
async def monthly_report():
    now = datetime.now(TZ)
    tomorrow = now + timedelta(days=1)
    if tomorrow.month != now.month and now.hour == 23 and now.minute >= 59:
        await send_monthly_top(now.date())


async def send_monthly_top(report_date: datetime.date):
    thread = bot.get_channel(TOP_THREAD_ID)
    if not thread:
        return

    # Знаходимо чемпіона
    best_user_id = None
    best_count = 0
    for user_id, data in list(message_stats.items()):
        count = data["monthly"]
        if count > best_count:
            best_count = count
            best_user_id = user_id
        data["monthly"] = 0  # обнуляємо місячну статистику

    if not best_user_id:
        await thread.send(f"💬 У {report_date.strftime('%B %Y')} ніхто не писав повідомлень.")
        return

    user = bot.get_user(best_user_id)
    name = user.display_name if user else f"User {best_user_id}"

    embed = discord.Embed(
        title="🏆 Чемпіон місяця (чат)",
        description=f"**{name}** написав найбільше повідомлень ({best_count})!",
        color=discord.Color.gold()
    )
    embed.set_image(url="https://i.imgur.com/ZB1CzyI.png")
    embed.set_footer(text="Silent Concierge by Myxa")

    await thread.send(embed=embed)


if __name__ == "__main__":
    bot.run(TOKEN)
