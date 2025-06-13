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
    print(f"[DEBUG] ✅ WelcomeBot увійшов як {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"[DEBUG] 🔄 Slash-команди синхронізовано: {len(synced)}")
    except Exception as e:
        print(f"[DEBUG] ❌ Помилка синхронізації команд: {e}")

async def main():
    print("[DEBUG] 🚀 Старт WelcomeBot...")
    async with bot:
        try:
            print("[DEBUG] 📥 Завантажуємо welcome_cog...")
            await bot.load_extension("cogs.welcome_cog")
            print("[DEBUG] ✅ WelcomeCog завантажено")
        except Exception as e:
            print(f"[DEBUG] ❌ Не вдалося завантажити WelcomeCog: {e}")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
