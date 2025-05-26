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

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ [WelcomeBot] Увійшов як {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Команд синхронізовано: {len(synced)}")
    except Exception as e:
        print(f"❌ Sync error: {e}")

async def main():
    async with bot:
        await bot.load_extension("cogs.welcome_cog")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
