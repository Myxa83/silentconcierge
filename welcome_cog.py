import discord
from discord.ext import commands
from discord import app_commands, Interaction
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import requests
from io import BytesIO
import asyncio

class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.templates = [
            "Докладаю! {{mention}} залетів на нашу базу Silent Cove [BDO EU] з двох ніг!",
            "ДРАКОН ПРОБУДИВСЯ! {{mention}} розгортає крила над сервером!",
            "Важливе оголошення! В нашій секті… ой, тобто на сервері, новий учасник – {{mention}}!",
            "{{mention}} сходить із зірок прямо до нас. Магія тільки починається!",
            "Тиша порушена. {{mention}} з’явився у лісі Silent Cove!",
            "КРИТИЧНИЙ ВИБУХ КРУТОСТІ! {{mention}} активував(ла) ульту!",
            "Пані та панове, зустрічайте! Найочікуваніший гість – {{mention}}! Оплески!",
        ]
        self.titles = [
            "📥 Прибуття нового духу!",
            "📥 Прибуття нової жертви!"
        ]
        self.images = [
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/corsair_scroll_dark.png",
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/welcome.png"
        ]

    def build_caption(self, member: discord.Member):
        text = random.choice(self.templates).replace("{{mention}}", member.mention)
        return '\n'.join(self.wrap_text(text, width=18))

    def build_title(self, member: discord.Member):
        title = random.choice(self.titles)
        return f"{title} {member.mention}"

    def wrap_text(self, text, width=18):
        words = text.split()
        lines = []
        current_line = ""
        for word in words:
            if len(current_line) + len(word) + 1 <= width:
                current_line += (" " if current_line else "") + word
            else:
                lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    async def create_image_with_text(self, text: str, member: discord.Member) -> discord.File:
        print("🔧 Завантажуємо фон")
        url = random.choice(self.images)
        response = requests.get(url, timeout=5)
        background = Image.open(BytesIO(response.content)).convert("RGBA")
        draw = ImageDraw.Draw(background)

        print("🎨 Малюємо текст")
        font = ImageFont.truetype("FixelDisplay-Regular.otf", 56)
        draw.text((110, 120), text, font=font, fill=(90, 60, 40, 255), spacing=10)

        print("🖼️ Завантажуємо аватарку")
        avatar_url = str(member.display_avatar.replace(size=512))
        avatar_response = requests.get(avatar_url)
        avatar = Image.open(BytesIO(avatar_response.content)).convert("RGBA")
        avatar = avatar.resize((512, 512))

        mask = Image.new("L", (512, 512), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, 512, 512), fill=255)

        shadow = Image.new("RGBA", (532, 532), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.ellipse((5, 5, 527, 527), fill=(0, 0, 0, 150))
        shadow = shadow.filter(ImageFilter.GaussianBlur(4))

        avatar_x = background.width - 562
        avatar_y = background.height - 562

        background.paste(shadow, (avatar_x - 5, avatar_y - 5), shadow)
        background.paste(avatar, (avatar_x, avatar_y), mask)

        output = BytesIO()
        background.save(output, format="PNG")
        output.seek(0)
        print("📤 Готово — повертаємо файл")
        return discord.File(output, filename="welcome.png")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        print(f"📤 Користувач вийшов: {member}")
        channel = self.bot.get_channel(1350571574557675520)
        if channel:
            embed = discord.Embed(
                title="🚪 Учасник покинув сервер",
                description=f"{member.mention} більше з нами нема...",
                color=discord.Color.orange()
            )
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        print(f"⛔ BAN: {user}")
        channel = self.bot.get_channel(1350571574557675520)
        reason = "Не вказано"
        try:
            async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    reason = entry.reason or "Не вказано"
                    break
        except Exception as e:
            print(f"Помилка при отриманні причини бану: {e}")

        if channel:
            embed = discord.Embed(
                title="⛔ Користувача забанено",
                description=f"{user.mention} був вигнаний у тіньову безодню. Причина: {reason}",
                color=discord.Color.red()
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            await channel.send(embed=embed)

        try:
            dm_embed = discord.Embed(
                title="⛔ Ви були заблоковані на сервері Silent Cove",
                description=f"Причина: {reason}",
                color=discord.Color.red()
            )
            dm_embed.set_image(url="https://i.imgur.com/E0G8qTz.png")
            await user.send(embed=dm_embed)
        except Exception as e:
            print(f"Не вдалося надіслати DM користувачу {user}: {e}")


    @app_commands.command(name="привіт", description="Тестове привітання")
    async def test_hi(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)
        print("📥 Запуск /привіт")
        caption = self.build_caption(interaction.user)
        title = self.build_title(interaction.user)
        file = await self.create_image_with_text(caption, interaction.user)
        embed = discord.Embed(
            title=title,
            color=discord.Colour.teal()
        )
        embed.set_image(url="attachment://welcome.png")
        embed.set_footer(
            text="Silent Concierge by Myxa",
            icon_url=self.bot.user.display_avatar.url
        )
        print("📨 Відправляємо embed")
        await interaction.followup.send(embed=embed, file=file)

    
    async def cog_load(self):
        guild = discord.Object(id=1323454227816906802)
        self.bot.tree.add_command(self.test_hi, guild=guild)
        

async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
