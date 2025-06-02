import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}!")
    try:
        guild = discord.Object(id=1323454227816906802)  # <-- ТУТ твій сервер ID
        bot.tree.copy_global_to(guild=guild)  # <--- БЕЗ await!
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ Synced {len(synced)} commands in guild {guild.id}!")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")

async def main():
    async with bot:
        await bot.load_extension("cogs.vell_cog")
        await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())
