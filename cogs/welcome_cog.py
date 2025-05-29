import os
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import random

class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.templates = [
            "{{mention}} залетів на нашу базу Silent Cove [BDO EU] з двох ніг!",
            "ДРАКОН ПРОБУДИВСЯ! {{mention}} розгортає крила над сервером!",
            "В нашій секті… ой, тобто на сервері, новий учасник – {{mention}}!",
            "{{mention}} сходить із зірок прямо до нас. Магія тільки починається!",
            "Тиша порушена. {{mention}} з’явився у лісі Silent Cove!",
            "КРИТИЧНИЙ ВИБУХ КРУТОСТІ! {{mention}} активував(ла) ульту!",
            "Пані та панове, зустрічайте! Найочікуваніший гість – {{mention}}!"
        ]

    @commands.Cog.listener()
    async def on_member_join(self, member):
        print(f"📥 [DEBUG] Користувач приєднався: {member}")
        channel = self.bot.get_channel(1324854638276509828)
        if not channel:
            print("❌ [DEBUG] Канал для привітання не знайдено")
            return

        bg_urls = [
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/corsair_scroll_dark.png",
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/scroll_2.png"
        ]
        background_url = random.choice(bg_urls)
        print(f"🖼️ [DEBUG] Обрано фон: {background_url}")
        response = requests.get(background_url)
        bg = Image.open(BytesIO(response.content)).convert("RGBA")

        draw = ImageDraw.Draw(bg)
        name_font = ImageFont.truetype("FixelDisplay-Bold.otf", 54)
        text_font = ImageFont.truetype("FixelDisplay-SemiBold.otf", 52)

        name = member.display_name
        lines = [
            "Пані та панове,",
            "Зустрічайте!",
            "Найочікуваніший",
            f"гість – {name}"
        ]

        text_color = (51, 29, 16)
        x_text = 100
        y_text = 360

        print("📝 [DEBUG] Рендеримо текст на сувої")
        for i, line in enumerate(lines):
            font = name_font if name in line else text_font
            draw.text((x_text, y_text + i * 64), line, font=font, fill=text_color)

        avatar_asset = member.display_avatar.replace(size=512)
        print(f"🖼️ [DEBUG] Завантажуємо аватар: {avatar_asset}")
        avatar_bytes = await avatar_asset.read()
        pfp = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((160, 160))

        x_offset, y_offset = 1040, 540
        print(f"🧷 [DEBUG] Вставляємо аватар на позицію ({x_offset}, {y_offset})")
        bg.paste(pfp, (x_offset, y_offset), mask=pfp)

        output_path = f"welcome_{member.id}.png"
        bg.save(output_path)
        print(f"✅ [DEBUG] Збережено зображення: {output_path}")

        embed = discord.Embed(
            title=random.choice([
                "📥 Прибуття нового духу!",
                "📥 Прибуття нової солодкої булочки!",
                "📥 Прибуття нового котятка!",
                "📥 Прибуття нового голого поросятка!",
                "📥 Прибуття нової жертви!"
            ]),
            description=f"{member.mention}",
            color=discord.Color.dark_teal()
        )
        embed.set_image(url=f"attachment://{output_path}")
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.avatar.url if self.bot.user.avatar else None)

        await channel.send(embed=embed, file=discord.File(output_path, filename=output_path))
        os.remove(output_path)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        print(f"📤 Користувач вийшов: {member}")
        channel = self.bot.get_channel(1350571574557675520)
        if channel:
            embed = discord.Embed(
                title="🚪 Учасник покинув сервер",
                description=f"{member.mention} більше з нами нема...",
                color=discord.Color.from_rgb(252, 3, 3)
            )
            if member.avatar:
                embed.set_thumbnail(url=member.avatar.url)
            if member.joined_at:
                embed.add_field(name="Дата приєднання", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            embed.add_field(name="Дата виходу", value=discord.utils.format_dt(discord.utils.utcnow(), style='f'), inline=True)
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        print(f"⛔ [DEBUG] BAN: {user}")
        channel = self.bot.get_channel(1350571574557675520)
        reason = "Не вказано"

        try:
            dm_embed = discord.Embed(
                title="⛔ Ви будете заблоковані на сервері Silent Cove",
                description=f"Нажаль ви ({user.name}) не виправдали наданої довіри і ми вимушені з вами попрощатись. Myxa",
                color=discord.Color.red()
            )
            dm_embed.set_image(url="https://github.com/Myxa83/silentconcierge/blob/main/BAN.png?raw=true")
            await user.send(embed=dm_embed)
            print("📩 [DEBUG] Надіслано попередження в особисті повідомлення")
        except Exception as e:
            print(f"⚠️ [DEBUG] Не вдалося надіслати попередження користувачу {user}: {e}")

        try:
            async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    reason = entry.reason or "Не вказано"
                    break
        except Exception as e:
            print(f"⚠️ [DEBUG] Помилка при отриманні причини бану: {e}")

        if channel:
            embed = discord.Embed(
                title="⛔ Користувача забанено!",
                description=f"{user.mention} порушив(ла) правила Silent Cove.",
                color=discord.Color.from_rgb(252, 3, 3)
            )
            embed.add_field(name="Причина:", value=reason, inline=False)
            embed.add_field(name="Дата приєднання", value="Невідомо", inline=True)
            embed.add_field(name="Покинув:", value=discord.utils.format_dt(discord.utils.utcnow(), style='f'), inline=True)
            if hasattr(user, 'avatar') and user.avatar:
                embed.set_thumbnail(url=user.avatar.url)
            await channel.send(embed=embed)
            print("📨 [DEBUG] Надіслано повідомлення про бан до каналу")

    async def cog_load(self):
        print("🔃 [DEBUG] WelcomeCog завантажено")
        pass

async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
