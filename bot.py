import discord
from discord.ext import commands
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Бот увійшов як {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Slash-команди синхронізовано: {len(synced)}")
    except Exception as e:
        print(f"❌ Помилка синхронізації команд: {e}")

async def load_all_cogs():
    await bot.load_extension("vell_cog")
    await bot.load_extension("raid_cog")
    await bot.load_extension("post_cog")
    await bot.load_extension("timezone_cog")
    await bot.load_extension("welcome_cog")

if __name__ == "__main__":
    import asyncio
    async def main():
        await load_all_cogs()
        await bot.start(TOKEN)
    asyncio.run(main())
