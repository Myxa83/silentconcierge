import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🔌 Бот увійшов як {bot.user} (ID: {bot.user.id})")
    print("✅ Slash-команди синхронізовано.")

async def main():
    async with bot:
        await bot.load_extension("raid_cog")  # Назва файлу Cog без .py
        await bot.start(os.getenv("DISCORD_TOKEN"))

import asyncio
asyncio.run(main())
