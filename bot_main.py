import discord
from discord.ext import commands
import os
import json
import asyncio
from datetime import datetime
import pytz
from dotenv import load_dotenv

# === Завантажуємо .env тільки для основного ===
load_dotenv("config/.env.main")

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

if not TOKEN or not GUILD_ID:
    raise ValueError("❌ Не знайдено DISCORD_TOKEN або GUILD_ID у config/.env.main")

GUILD_ID = int(GUILD_ID)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ====== Завантаження когів ======
async def load_cogs():
    cogs = [
        "cogs.guild_boss_command",
        "cogs.guild_status_cog",
        "cogs.post_cog",
        "cogs.ruin_cog",
        "cogs.seaquests_cog",
        "cogs.stream_cog",
        "cogs.sync_cog",
        "cogs.timezone_cog",
        "cogs.vell_cog",
        "cogs.welcome_cog",
        "cogs.interest_roles_cog"   # <-- ТУТ ДОДАНО ТВІЙ НОВИЙ КОГ
    ]
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            print(f"[INFO] Завантажено ког {cog}")
        except Exception as e:
            print(f"[ERROR] Не вдалося завантажити {cog}: {e}")

# ====== Цикл статусів ======
async def cycle_statuses(bot, status_file="config/status_phrases.json"):
    await bot.wait_until_ready()
    with open(status_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    day_phrases = data.get("day_phrases", [])
    night_phrases = data.get("night_phrases", [])

    i = 0
    while not bot.is_closed():
        now = datetime.now(pytz.timezone("Europe/London"))

        if 6 <= now.hour < 23:
            phrases = day_phrases
        else:
            phrases = night_phrases

        if not phrases:
            phrases = ["Silent Cove 🐚"]

        status_text = phrases[i % len(phrases)]
        await bot.change_presence(activity=discord.Game(name=status_text))
        print(f"[STATUS] SilentConcierge → {status_text}")
        i += 1
        await asyncio.sleep(60)

# ====== Події ======
@bot.event
async def on_ready():
    print(f"[INFO] SilentConcierge запущено як {bot.user} ({bot.user.id})")
    await load_cogs()
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"[DEBUG] Синхронізовано {len(synced)} команд для сервера {GUILD_ID}")
    except Exception as e:
        print(f"[ERROR] Не вдалося синхронізувати команди: {e}")
    bot.loop.create_task(cycle_statuses(bot))

# ====== Команда для примусового очищення і пушу ======
@bot.command()
@commands.is_owner()
async def clear_global(ctx):
    """Очистити глобальні команди і примусово запушити локальні"""
    await bot.tree.clear_commands(guild=None)
    await bot.tree.sync(guild=None)

    synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    await ctx.send(
        f"✅ Глобальні команди очищено.\n"
        f"📌 Примусово запушено {len(synced)} локальних команд для основного сервера."
    )

bot.run(TOKEN)
