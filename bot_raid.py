import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    print(f"[RaidBot] Увійшов як {bot.user}#{bot.user.discriminator}")
    print(f"Синхронізовано {len(synced)} команд: {[cmd.name for cmd in synced]}")

async def main():
    async with bot:
        await bot.load_extension("cogs.raid_cog")
        await bot.start(TOKEN)

asyncio.run(main())