import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def main():
    async with bot:
        await bot.load_extension("cogs.welcome_cog")
        await bot.load_extension("cogs.vell_cog")
        await bot.load_extension("cogs.post_cog")
        await bot.load_extension("cogs.raid_cog")
        await bot.load_extension("cogs.timezone_cog")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
