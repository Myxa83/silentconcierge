import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    print(f"[DEBUG] Logged in as {bot.user}!")
    try:
        guild = discord.Object(id=1323454227816906802)
        bot.tree.clear_commands(guild=guild)  # Очистити старі команди на сервері (без await)
        await bot.tree.sync(guild=guild)       # Синхронізувати нові команди на сервері
        print(f"✅ Commands cleared and synced on server {guild.id}!")
    except Exception as e:
        print(f"❌ Failed to clear/sync commands: {e}")

async def load_extensions():
    await bot.load_extension("cogs.raid_cog")
    await bot.load_extension("cogs.post_cog")
    await bot.load_extension("cogs.timezone_cog")
    await bot.load_extension("cogs.welcome_cog")
    await bot.load_extension("cogs.vell_cog")

async def main():
    async with bot:
        await load_extensions()
        await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())
