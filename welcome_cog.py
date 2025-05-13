
import discord
from discord.ext import commands
from discord import app_commands, Interaction
import random
from PIL import Image, ImageDraw
import aiohttp
import io
import os

class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.background_path = "welcome.png"
        self.templates = [
            "🐉 ДРАКОН ПРОБУДИВСЯ! {mention} розгортає крила над сервером! Готуйтеся до вогню та хаосу!🔥",
            "🌌 Тінь пройшла крізь портал. {mention}, ласкаво просимо до Silent Cove!",
            "🎇 Сяйво нового духу: {mention} приєднався до нашого саду!",
            "💫 {mention} сходить із зірок прямо до нас. Магія тільки починається!",
            "🌿 Тиша порушена. {mention} з’явився у лісі Silent Cove!"
        ]

    async def cog_load(self):
        guild = discord.Object(id=1323454227816906802)
        self.bot.tree.add_command(self.test_welcome, guild=guild)

    async def generate_welcome_image(self, member: discord.Member):
        if not os.path.exists(self.background_path):
            return None

        try:
            # Завантаження аватарки
            async with aiohttp.ClientSession() as session:
                async with session.get(member.display_avatar.url) as resp:
                    avatar_data = await resp.read()

            avatar = Image.open(io.BytesIO(avatar_data)).convert("RGBA")

            avatar_size = 96
            avatar = avatar.resize((avatar_size, avatar_size))

            mask = Image.new("L", (avatar_size, avatar_size), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
            avatar.putalpha(mask)

            background = Image.open(self.background_path).convert("RGBA")
            bg_width, bg_height = background.size

            # Безпечні координати вставки
            x = max(0, bg_width - avatar_size - 20)
            y = max(0, bg_height - avatar_size - 20)

            background.paste(avatar, (x, y), avatar)

            buffer = io.BytesIO()
            background.save(buffer, format="PNG")
            buffer.seek(0)
            return discord.File(buffer, filename="welcome_final.png")

        except Exception as e:
            print(f"⚠️ Помилка генерації зображення: {e}")
            return None

    def build_caption(self, member: discord.Member):
        return random.choice(self.templates).format(mention=member.mention)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        channel_id = 1324854638276509828
        channel = self.bot.get_channel(channel_id)
        if channel:
            caption = self.build_caption(member)
            file = await self.generate_welcome_image(member)
            if file:
                await channel.send(content=caption, file=file)

    @app_commands.command(name="привіт", description="Надсилає вітання з аватаркою внизу")
    async def test_welcome(self, interaction: Interaction):
        caption = self.build_caption(interaction.user)
        file = await self.generate_welcome_image(interaction.user)
        if file:
            await interaction.response.send_message(content=caption, file=file)
        else:
            await interaction.response.send_message("❌ Не вдалося створити вітальне зображення.")
