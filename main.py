from dotenv import load_dotenv
import os

# Завантаження .env або Secrets
load_dotenv()

import discord
from discord import Embed
from discord.ext import commands
import random

# --- DEBUG: перевірка токена ---
print("DEBUG TOKEN:", os.getenv("DISCORD_BOT_TOKEN"))

# --- Інтенції ---
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# --- Створення бота ---
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Подія при вході нового учасника ---
@bot.event
async def on_member_join(member):
    channel = bot.get_channel(1324854638276509828)
    if channel:
        welcome_messages = [
            "📢 Важливе оголошення! В нашій секті… ой, тобто на сервері, новий учасник — {mention}! Тепер ти один із нас! 😜",
            "🔥 МОМЕНТАЛЬНИЙ ЛЕВЕЛ-АП! {mention} прокачав сервер до +100 до карми!",
            "⚠️ ОБЕРЕЖНО! Новий вибуховий елемент у чаті – {mention}!",
            "‼️НЕГАЙНО!!! Тут {mention} наближається!!!",
            "🎤 Пані та панове, зустрічайте – {mention}! 👏",
            "💀 КОД ЧОРНОГО ВІТРІЛА АКТИВОВАНО! {mention} на палубі!",
            "⚠️ КРИТИЧНИЙ ВИБУХ КРУТОСТІ! {mention} активував ульту!",
            "📣 Докладаю! {mention} залетів на базу!",
            "🌌 Всесвіт почув молитви – {mention} тут! 🤓"
        ]

        msg_text = random.choice(welcome_messages).format(mention=member.mention)

        embed = Embed(
            title="👋 Ласкаво просимо!",
            description=msg_text,
            color=0x00ffcc
        )

        # Безпечна перевірка аватарки
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)

        embed.set_image(url="https://i.ibb.co/tbwQYFZ/bench.jpg")  # фон за бажанням
        embed.set_footer(text="Silent Cove")

        await channel.send(embed=embed)

# --- Команда !hello ---
@bot.command()
async def hello(ctx):
    await ctx.send(f"Привіт, {ctx.author.name}! Я тут, як завжди")

# --- Запуск бота ---
bot.run(os.getenv("DISCORD_BOT_TOKEN"))