import os
import discord
from discord.ext import commands
from discord import app_commands, Interaction
import random
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import asyncio
from dotenv import load_dotenv

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}!")
    try:
        synced = await bot.tree.sync()
        print(f"🔁 Synced {len(synced)} commands")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

async def load_cogs():
    extensions = [
        "cogs.welcome_cog",
        "cogs.vell_cog",
        "cogs.raid_cog",
        "cogs.timezone_cog",
        "cogs.post_cog"
    ]
    for ext in extensions:
        try:
            await bot.load_extension(ext)
            print(f"✅ Loaded {ext}")
        except Exception as e:
            print(f"❌ Failed to load {ext}: {e}")

async def main():
    await load_cogs()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())