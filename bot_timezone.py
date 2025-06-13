import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"[DEBUG] Завантаження TimezoneBot...")
    print(f"[DEBUG] TimezoneBot увійшов як {bot.user}")
    try:
        guild = discord.Object(id=1323454227816906802)  # ID твого сервера
        synced = await bot.tree.sync(guild=guild)
        print(f"[DEBUG] ✅ Slash-команди синхронізовано: {len(synced)} для сервера {guild.id}")
    except Exception as e:
        print(f"[DEBUG] ❌ Помилка синхронізації команд: {e}")

async def main():
    print("[DEBUG] Початок запуску TimezoneBot...")
    async with bot:
        print("[DEBUG] Завантажуємо розширення timezone_cog...")
        await bot.load_extension("cogs.timezone_cog")
        print("[DEBUG] Розширення timezone_cog завантажено.")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
