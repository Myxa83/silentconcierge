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
            "{{mention}} залетів на нашу базу Silent Cove [BDO EU] з двох ніг!",
            "ДРАКОН ПРОБУДИВСЯ! {{mention}} розгортає крила над сервером!",
            "В нашій секті… ой, тобто на сервері, новий учасник – {{mention}}!",
            "{{mention}} сходить із зірок прямо до нас. Магія тільки починається!",
            "Тиша порушена. {{mention}} з’явився у лісі Silent Cove!",
            "КРИТИЧНИЙ ВИБУХ КРУТОСТІ! {{mention}} активував(ла) ульту!",
            "Пані та панове, зустрічайте! Найочікуваніший гість – {{mention}}!",
        ]
        self.titles = [
            "📥 Прибуття нового духу!",
            "📥 Прибуття нової солодкої булочки!",
            "📥 Прибуття нового котятка!",
            "📥 Прибуття нового голого поросятка!",
            "📥 Прибуття нової легенди туману!",
            "📥 Прибуття нової жертви!"
        ]
        self.images = [
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/welcome.png",
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/corsair_scroll_dark.png"
        ]

    def build_caption(self, member: discord.Member):
        text = random.choice(self.templates).replace("{{mention}}", member.display_name)
        return '\n'.join(self.wrap_text(text, width=18))

    def build_title(self, member: discord.Member):
        title = random.choice(self.titles)
        return f"{title}"

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

    def rounded_mask(self, w, h, r):
        mask = Image.new('L', (w, h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, w, h), radius=r, fill=255)
        return mask

    async def create_image_with_text(self, text: str, member: discord.Member) -> discord.File:
        print("🟢 [DEBUG] Початок створення зображення...")

        url = random.choice(self.images)
        print(f"🔗 [DEBUG] Завантаження фону з: {url}")
        response = requests.get(url, timeout=5)
        background = Image.open(BytesIO(response.content)).convert("RGBA")

        print("🎨 [DEBUG] Фон успішно відкрито")
        draw = ImageDraw.Draw(background)

        font_regular = ImageFont.truetype("FixelDisplay-SemiBold.otf", 48)
        font_bold = ImageFont.truetype("FixelDisplay-Bold.otf", 44)

        lines = text.split('\n')
        y = 240 + 40
        print(f"📄 [DEBUG] Рендерим {len(lines)} рядків...")
        for line in lines:
            print(f"📝 [DEBUG] Рядок: {line}")
            x = 190  # зміщено вліво на 50 пікселів
            if member.display_name in line:
                before, sep, after = line.partition(member.display_name)
                if before:
                    draw.text((x, y), before, font=font_regular, fill=(13, 9, 7, 255), stroke_width=2, stroke_fill=(0, 0, 0, 100))
                    x += draw.textlength(before, font=font_regular)
                draw.text((x, y), member.display_name, font=font_bold, fill=(45, 30, 20, 255), stroke_width=2, stroke_fill=(0, 0, 0, 100))
                x += draw.textlength(member.display_name, font=font_bold)
                if after:
                    draw.text((x, y), after, font=font_regular, fill=(13, 9, 7, 255), stroke_width=2, stroke_fill=(0, 0, 0, 100))
            else:
                draw.text((x, y), line, font=font_regular, fill=(13, 9, 7, 255), stroke_width=2, stroke_fill=(0, 0, 0, 100))
            y += 92

        avatar_url = str(member.display_avatar.replace(size=512))
        print(f"🖼️ [DEBUG] Завантажуємо аватар з: {avatar_url}")
        avatar_response = requests.get(avatar_url)
        avatar = Image.open(BytesIO(avatar_response.content)).convert("RGBA")
        avatar = avatar.resize((320, 320))

        print("🌀 [DEBUG] Створюємо маску з радіусом 60")
        mask = self.rounded_mask(320, 320, 60)

        print("🌑 [DEBUG] Додаємо тінь під аватар")
        shadow = Image.new("RGBA", avatar.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle((0, 0, 320, 320), radius=60, fill=(0, 0, 0, 180))
        shadow = shadow.filter(ImageFilter.GaussianBlur(12))

        avatar_x = background.width - 360 - 55
        avatar_y = background.height - 360 - 40

        background.alpha_composite(shadow, (avatar_x, avatar_y))
        print(f"📍 [DEBUG] Вставляємо аватар на позицію: ({avatar_x}, {avatar_y})")
        background.paste(avatar, (avatar_x, avatar_y), mask)

        output = BytesIO()
        background.save(output, format="PNG")
        output.seek(0)
        print("✅ [DEBUG] Зображення готове!")

        return discord.File(output, filename="welcome.png")

    @app_commands.command(name="привіт", description="Тестове привітання")
    async def test_hi(self, interaction: Interaction):
        await interaction.response.defer(thinking=True)
        caption = self.build_caption(interaction.user)
        title = self.build_title(interaction.user)
        file = await self.create_image_with_text(caption, interaction.user)
        embed = discord.Embed(
            title=title,
            description=interaction.user.mention,
            color=discord.Colour.teal()
        )
        embed.set_image(url="attachment://welcome.png")
        embed.set_footer(
            text="Silent Concierge by Myxa",
            icon_url=self.bot.user.display_avatar.url
        )
        await interaction.followup.send(embed=embed, file=file)

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

    async def cog_load(self):
        guild = discord.Object(id=1323454227816906802)
        self.bot.tree.add_command(self.test_hi, guild=guild)

async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
