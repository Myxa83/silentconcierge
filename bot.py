import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv

# Завантажуємо токен з .env файлу
load_dotenv()

# Нам потрібні слеш-команди, тому обираємо "default" + дозволяємо повідомлення
intents = discord.Intents.default()
intents.message_content = True  # якщо будете додавати текстові команди — залиште

# Створюємо бота
bot = commands.Bot(command_prefix="!", intents=intents)

# Подія, коли бот повністю увімкнено
@bot.event
async def on_ready():
    print(f"✅ Увійшли як {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"📡 Синхронізовано {len(synced)} слеш-команд.")
    except Exception as e:
        print(f"❌ Помилка синхронізації: {e}")

# Основна асинхронна функція, яка підключає Cog і запускає бота
async def main():
    async with bot:
        await bot.load_extension("raid_cog")  # Без .py
        await bot.start(os.getenv("TOKEN"))

# Запуск
asyncio.run(main())