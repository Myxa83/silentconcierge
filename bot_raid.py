import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True  # Обов'язково для доступу до контенту повідомлень (на майбутнє)

bot = commands.Bot(command_prefix="!", intents=intents)

async def load_extensions():
    await bot.load_extension("cogs.raid_cog")  # Підключаємо твій ког raid_cog

@bot.event
async def on_ready():
    print(f"[DEBUG] {bot.user} готовий!")
    try:
        guild = discord.Object(id=1323454227816906802)  # ID твого сервера
        await bot.tree.sync(guild=guild)
        print(f"[DEBUG] ✅ Slash-команди синхронізовано для {guild.id}!")
    except Exception as e:
        print(f"[DEBUG] ❌ Помилка синхронізації: {e}")

async def main():
    async with bot:
        await load_extensions()
        await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())