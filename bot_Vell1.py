import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import asyncio

# Завантаження токена з .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Інтенти для бота
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Створення екземпляру бота
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    # Форс-синхронізація слеш-команд тільки для твого сервера
    guild = discord.Object(id=1323454227816906802)  # 👈 твій Server ID
    await bot.tree.sync(guild=guild)
    print(f"✅ Бот {bot.user} готовий працювати!")

async def load_cogs():
    # Завантаження когу Vell1
    await bot.load_extension("cogs.Vell1_cog")

async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)

# Запуск бота
asyncio.run(main())