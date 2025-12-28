# -*- coding: utf-8 -*-
import random
import io
import unicodedata
from pathlib import Path
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WELCOME_CHANNEL_ID = 1324854638276509828
TEST_WELCOME_CHANNEL_ID = 1370522199873814528
WELCOME_COLOR = 0x05B2B4


def dbg(msg: str):
    print(f"[WELCOME] {msg}")


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        dbg("✅ WelcomeCog ініціалізовано")

        base_dir = Path(__file__).resolve().parent.parent
        fonts_dir = base_dir / "assets" / "fonts"
        self.font_main = fonts_dir / "Montserrat-Regular.ttf"  # основний текст
        self.font_name = self.font_main                       # той самий для ніку

        # фони
        self.backgrounds = [
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/bg1.png",
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/bg2.png",
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/bg3.png",
        ]
        self.avatar_frame = (
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/ramka1.png"
        )

        # позиції та стилі
        self.avatar_size = 355
        self.frame_size_increase = 375
        self.avatar_absolute = (960, 515)
        self.text_color = (45, 26, 15, 255)

        # координати сувою
        self.scroll_boxes = {
            "bg1.png": (130, 220, 575, 510),
            "bg2.png": (130, 220, 575, 510),
            "bg3.png": (130, 220, 575, 510),
        }

        # тексти
        self.templates = [
            "{name} залетів на нашу базу Silent Cove [BDO EU] з двох ніг!",
            "ДРАКОН ПРОБУДИВСЯ! {name} розгортає крила над сервером!",
            "В нашій секті… ой, тобто на сервері, новий учасник – {name}!",
            "{name} сходить із зірок прямо до нас. Магія тільки починається!",
            "Тиша порушена. {name} з’явився у лісі Silent Cove!",
            "КРИТИЧНИЙ ВИБУХ КРУТОСТІ! {name} активував(ла) ульту!",
            "Пані та панове, зустрічайте! Найочікуваніший гість – {name}!",
        ]
        self.titles = [
            "Прибуття нового духу!",
            "Прибуття нової булочки!",
            "Прибуття нового котятка!",
            "Прибуття нової жертви!",
        ]

    # -------------------------------------------------------------------
    def normalize_name(self, name: str) -> str:
        normalized = unicodedata.normalize("NFKD", name)
        return ''.join(c for c in normalized if ord(c) < 65536)

    def wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int):
        words = text.split()
        lines = []
        line = words[0]
        for w in words[1:]:
            if font.getlength(line + " " + w) <= max_width:
                line += " " + w
            else:
                lines.append(line)
                line = w
        lines.append(line)
        return lines

    def get_scaled_font(self, text: str, max_width: int, font_path: Path, start_size=80, min_size=50):
        size = start_size
        while size > min_size:
            font = ImageFont.truetype(str(font_path), size)
            bbox = font.getbbox(text)
            if bbox[2] - bbox[0] <= max_width or size == min_size:
                dbg(f"📐 Обраний розмір шрифту: {size}px")
                return font
            size -= 2
        return ImageFont.truetype(str(font_path), min_size)

    def draw_multiline_text_centered(self, draw, lines, font, box, fill, username, font_name):
        x1, y1, x2, y2 = box
        max_width = x2 - x1
        max_height = y2 - y1
        line_height = font.getbbox("Ay")[3] - font.getbbox("Ay")[1]
        spacing = int(line_height * 0.3)
        total_height = len(lines) * line_height + (len(lines) - 1) * spacing
        y = y1 + (max_height - total_height) / 2

        for line in lines:
            w = font.getlength(line)
            x = x1 + (max_width - w) / 2
            draw.text((x, y), line, font=font, fill=fill)
            y += line_height + spacing

    # -------------------------------------------------------------------
    async def generate_welcome_image(self, member: discord.Member, text: str):
        dbg(f"▶ Створюється картинка для {member.display_name}")
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                bg_url = random.choice(self.backgrounds)
                bg_name = Path(bg_url).name
                async with session.get(bg_url) as r:
                    bg = Image.open(io.BytesIO(await r.read())).convert("RGBA")

                async with session.get(str(member.display_avatar.url)) as r:
                    avatar = Image.open(io.BytesIO(await r.read())).convert("RGBA").resize(
                        (self.avatar_size, self.avatar_size)
                    )

                async with session.get(self.avatar_frame) as r:
                    frame = Image.open(io.BytesIO(await r.read())).convert("RGBA")
                    frame_size = self.avatar_size + self.frame_size_increase
                    frame = frame.resize((frame_size, frame_size))

            mask = Image.new("L", (self.avatar_size, self.avatar_size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, self.avatar_size, self.avatar_size), fill=255)
            avatar.putalpha(mask)

            combined = Image.new("RGBA", bg.size, (0, 0, 0, 0))
            combined.alpha_composite(avatar, self.avatar_absolute)
            frame_pos = (
                self.avatar_absolute[0] - (frame_size - self.avatar_size) // 2,
                self.avatar_absolute[1] - (frame_size - self.avatar_size) // 2 + 50
            )
            combined.alpha_composite(frame, frame_pos)

            offset_x, offset_y = 35, 20
            shadow = combined.copy().convert("L")
            shadow = shadow.filter(ImageFilter.GaussianBlur(50))
            shadow = Image.eval(shadow, lambda p: int(p * 0.5))
            shadow_rgba = Image.new("RGBA", shadow.size, (0, 0, 0, 0))
            shadow_rgba.putalpha(shadow)
            bg.alpha_composite(shadow_rgba, (offset_x, offset_y))
            bg.alpha_composite(combined)

            username = self.normalize_name(member.display_name)
            text = text.replace("{name}", username)
            x1, y1, x2, y2 = self.scroll_boxes.get(bg_name, (100, 180, 520, 620))
            max_width = x2 - x1
            font = self.get_scaled_font(text, max_width, self.font_main)
            draw = ImageDraw.Draw(bg)
            lines = self.wrap_text(text, font, max_width)
            self.draw_multiline_text_centered(draw, lines, font, (x1, y1, x2, y2), self.text_color, username, font)

            buf = io.BytesIO()
            bg.save(buf, format="PNG")
            buf.seek(0)
            dbg("✅ Зображення створено")
            return discord.File(fp=buf, filename="welcome.png")

        except Exception as e:
            dbg(f"❌ Помилка при генерації картинки: {type(e).__name__}: {e}")
            return None

    # -------------------------------------------------------------------
    def make_embed(self, member: discord.Member) -> discord.Embed:
        embed = discord.Embed(
            title=random.choice(self.titles),
            description=f"{member.mention}",
            color=WELCOME_COLOR,
        )
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
        embed.set_image(url="attachment://welcome.png")
        return embed

    # -------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        dbg(f"🟢 Новий учасник: {member.display_name}")
        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            dbg("❌ Канал не знайдено!")
            return

        name = self.normalize_name(member.display_name)
        text = random.choice(self.templates).replace("{name}", name)
        file = await self.generate_welcome_image(member, text)
        if file:
            embed = self.make_embed(member)
            await channel.send(file=file, embed=embed)
            dbg("✅ Відправлено публічне привітання")

        try:
            dm = await member.create_dm()
            await dm.send(
                "Привіт, шукачу пригод!\n"
                "Ти віриш, що сьогодні чудовий день?\n"
                "Я ось вірю, адже ти завітав сьогодні!"
            )
            dbg("✅ Привітання у DM відправлено")
        except discord.Forbidden:
            dbg(f"⚠️ Не вдалося надіслати DM {member.display_name} — повідомлення закриті.")
        except Exception as e:
            dbg(f"❌ Помилка при відправці DM: {type(e).__name__}: {e}")

    # -------------------------------------------------------------------
    @app_commands.command(name="mockwelcome", description="Тест привітання (канал + DM)")
    @app_commands.checks.has_permissions(administrator=True)
    async def mock_welcome(self, interaction: discord.Interaction):
        member = interaction.user
        dbg(f"/mockwelcome викликано від {member.display_name}")
        channel = self.bot.get_channel(TEST_WELCOME_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Тестовий канал не знайдено.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)

        name = self.normalize_name(member.display_name)
        text = random.choice(self.templates).replace("{name}", name)
        file = await self.generate_welcome_image(member, text)
        if file:
            embed = self.make_embed(member)
            msg = await channel.send(file=file, embed=embed)
            try:
                dm = await member.create_dm()
                await dm.send(
                    "Привіт, шукачу пригод!\n"
                    "Ти віриш, що сьогодні чудовий день?\n"
                    "Я ось вірю, адже ти завітав сьогодні!"
                )
                await interaction.followup.send(f"✅ Тест у канал + DM надіслано!\n[jump]({msg.jump_url})", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"⚠️ Тест у канал пройшов, але DM не відправлено: {e}", ephemeral=True)
        else:
            await interaction.followup.send("❌ Не вдалося створити картинку.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
    dbg("✅ WelcomeCog (Montserrat без static, фінальний) підвантажено")