import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv

# Завантаження .env
load_dotenv()
TOKEN = os.getenv("TOKEN")

# Ініціалізація інтентів
intents = discord.Intents.default()
intents.message_content = True  # потрібен, якщо плануєш використовувати текстові команди

# Створення бота
bot = commands.Bot(command_prefix="!", intents=intents)

# Подія — бот увійшов у Discord
@bot.event
async def on_ready():
    print(f"✅ [RaidBot] Увійшов як {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Команд синхронізовано: {len(synced)}")
    except Exception as e:
        print(f"❌ Помилка синхронізації: {e}")

# Основна функція запуску
async def main():
    async with bot:
        await bot.load_extension("cogs.raid_cog")       # головний рейд ког
        await bot.load_extension("cogs.vell_cog")       # для Вела (якщо є)
        await bot.load_extension("cogs.timezone_cog")   # збереження таймзони
        await bot.load_extension("cogs.welcome_cog")    # привітання нових
        await bot.start(TOKEN)

# Запуск
if __name__ == "__main__":
    asyncio.run(main())
