import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import asyncio

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("BOT_OWNER_ID"))

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ [MainBot] Увійшов як {bot.user}")
    try:
        guild = discord.Object(id=1323454227816906802)
        synced = await bot.tree.sync(guild=guild)
        print(f"🔄 Команд синхронізовано на сервері {guild.id}: {len(synced)}")
    except Exception as e:
        print(f"❌ Помилка синхронізації команд: {e}")

async def main():
    print("🚀 Старт бота з усіма когами...")
    async with bot:
        try:
            await bot.load_extension("cogs.welcome_cog")
            print("✅ Завантажено welcome_cog")
            await bot.load_extension("cogs.raid_cog")
            print("✅ Завантажено raid_cog")
            await bot.load_extension("cogs.vell_cog")
            print("✅ Завантажено vell_cog")
            await bot.load_extension("cogs.post_cog")
            print("✅ Завантажено post_cog")
            await bot.load_extension("cogs.timezone_cog")
            print("✅ Завантажено timezone_cog")
        except Exception as e:
            print(f"❌ Помилка при завантаженні когів: {e}")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
