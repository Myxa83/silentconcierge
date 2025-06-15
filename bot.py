import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
from pathlib import Path
import asyncio
import sys
import time

# Завантажити .env з підпапки config
load_dotenv(dotenv_path=Path("config/.env"))

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 1323454227816906802
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", 279395551198445568))

if not TOKEN:
    raise ValueError("❌ DISCORD_TOKEN не знайдено у файлі config/.env")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"[DEBUG] ✅ Silent Concierge#7620 підключено!")
    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        print(f"[DEBUG] 🔄 Форсовано синхронізовано слеш-команди на сервері {guild.id}: {len(synced)}")
    except Exception as e:
        print(f"[DEBUG] ❌ Помилка синхронізації команд: {e}")

    if not heartbeat_loop.is_running():
        heartbeat_loop.start()

@tasks.loop(minutes=15)
async def heartbeat_loop():
    print("[DEBUG] 🌀 Перевірка активності: бот живий.")
    try:
        await bot.change_presence(activity=discord.Game(name="Я майже Джарвіс 😎"))
    except Exception as e:
        print(f"[DEBUG] ⚠️ Не вдалося оновити статус: {e}")

async def main():
    print("[DEBUG] 🚀 Старт SilentConcierge...")
    while True:
        try:
            async with bot:
                extensions = [
                    "cogs.post_cog",
                    "cogs.raid_cog",
                    "cogs.vell_cog",
                    "cogs.welcome_cog",
                    "cogs.timezone_cog",
                ]
                for ext in extensions:
                    try:
                        print(f"[DEBUG] 📥 Завантажуємо: {ext}")
                        await bot.load_extension(ext)
                        print(f"[DEBUG] ✅ Завантажено: {ext}")
                    except Exception as e:
                        print(f"[DEBUG] ❌ Помилка у {ext}: {e}")
                await bot.start(TOKEN)
        except Exception as e:
            print(f"[DEBUG] ⚠️ Бот аварійно зупинився. Перезапуск через 30 сек... Помилка: {e}")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())
