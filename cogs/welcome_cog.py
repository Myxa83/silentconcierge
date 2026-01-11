# -*- coding: utf-8 -*-
import random
import io
import unicodedata
import traceback
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


def _shorten(text: str, limit: int = 1800) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (trimmed)"


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Paths (важливо для Render)
        self.base_dir = Path(__file__).resolve().parents[1]  # корінь репо
        self.assets_dir = self.base_dir / "assets"
        self.backgrounds_dir = self.assets_dir / "backgrounds"
        self.fonts_dir = self.assets_dir / "fonts"

        # Local assets
        self.background_paths = sorted(self.backgrounds_dir.glob("bg*.png"))
        self.avatar_frame_path = self.backgrounds_dir / "ramka1.png"

        # Fonts
        self.font_main = self.fonts_dir / "Montserrat-Regular.ttf"

        # Fallback URLs (на випадок, якщо assets ще не запушені)
        self.background_urls_fallback = [
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/bg1.png",
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/bg2.png",
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/bg3.png",
        ]
        self.avatar_frame_url_fallback = (
            "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/ramka1.png"
        )

        # Positions, sizes
        self.avatar_size = 355
        self.frame_size_increase = 375
        self.avatar_absolute = (960, 515)
        self.text_color = (45, 26, 15, 255)

        # Scroll boxes mapping
        self.scroll_boxes = {
            "bg1.png": (130, 220, 575, 510),
            "bg2.png": (130, 220, 575, 510),
            "bg3.png": (130, 220, 575, 510),
        }

        # Text templates
        self.templates = [
            "{name} залетів на нашу базу Silent Cove [BDO EU] з двох ніг!",
            "ДРАКОН ПРОБУДИВСЯ! {name} розгортає крила над сервером!",
            "В нашій секті… ой, тобто на сервері, новий учасник - {name}!",
            "{name} сходить із зірок прямо до нас. Магія тільки починається!",
            "Тиша порушена. {name} з’явився у лісі Silent Cove!",
            "КРИТИЧНИЙ ВИБУХ КРУТОСТІ! {name} активував(ла) ульту!",
            "Пані та панове, зустрічайте! Найочікуваніший гість - {name}!",
        ]
        self.titles = [
            "Прибуття нового духу!",
            "Прибуття нової булочки!",
            "Прибуття нового котятка!",
            "Прибуття нової жертви!",
        ]

        dbg("✅ WelcomeCog init")
        dbg(f"base_dir={self.base_dir}")
        dbg(f"assets_dir exists={self.assets_dir.exists()} path={self.assets_dir}")
        dbg(f"backgrounds_dir exists={self.backgrounds_dir.exists()} path={self.backgrounds_dir}")
        dbg(f"fonts_dir exists={self.fonts_dir.exists()} path={self.fonts_dir}")
        dbg(f"found bg*.png={len(self.background_paths)}")
        dbg(f"frame exists={self.avatar_frame_path.exists()} path={self.avatar_frame_path}")
        dbg(f"font exists={self.font_main.exists()} path={self.font_main}")

    # ---------------- text helpers ----------------
    def normalize_name(self, name: str) -> str:
        normalized = unicodedata.normalize("NFKD", name)
        return "".join(c for c in normalized if ord(c) < 65536)

    def wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int):
        words = text.split()
        if not words:
            return [text]
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
                return font
            size -= 2
        return ImageFont.truetype(str(font_path), min_size)

    def draw_multiline_text_centered(self, draw, lines, font, box, fill):
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

    # ---------------- image helpers ----------------
    async def _fetch_image(self, session: aiohttp.ClientSession, url: str) -> Image.Image:
        async with session.get(url) as r:
            r.raise_for_status()
            return Image.open(io.BytesIO(await r.read())).convert("RGBA")

    def _load_local_image(self, path: Path) -> Image.Image:
        return Image.open(path).convert("RGBA")

    def _where(self) -> str:
        # корисно коли Render запускає з іншого cwd
        try:
            cwd = Path.cwd()
        except Exception:
            cwd = "unknown"
        return f"cwd={cwd} base={self.base_dir}"

    # ---------------- core render ----------------
    async def generate_welcome_image(self, member: discord.Member, text: str):
        """
        Returns: (discord.File | None, error_text | None)
        error_text містить тип помилки, файл:рядок, і шматок traceback.
        """
        dbg(f"generate_welcome_image for {member.display_name} {_shorten(self._where(), 300)}")

        try:
            timeout = aiohttp.ClientTimeout(total=25)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Background
                bg_name = "unknown.png"
                if self.background_paths:
                    bg_path = random.choice(self.background_paths)
                    bg_name = bg_path.name
                    dbg(f"BG local: {bg_path}")
                    bg = self._load_local_image(bg_path)
                else:
                    bg_url = random.choice(self.background_urls_fallback)
                    bg_name = Path(bg_url).name
                    dbg(f"BG url: {bg_url}")
                    bg = await self._fetch_image(session, bg_url)

                # Avatar
                avatar_url = str(member.display_avatar.url)
                dbg(f"Avatar url: {avatar_url}")
                avatar = await self._fetch_image(session, avatar_url)
                avatar = avatar.resize((self.avatar_size, self.avatar_size))

                # Frame
                if self.avatar_frame_path.exists():
                    dbg(f"Frame local: {self.avatar_frame_path}")
                    frame = self._load_local_image(self.avatar_frame_path)
                else:
                    dbg(f"Frame url: {self.avatar_frame_url_fallback}")
                    frame = await self._fetch_image(session, self.avatar_frame_url_fallback)

            # Round mask
            mask = Image.new("L", (self.avatar_size, self.avatar_size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, self.avatar_size, self.avatar_size), fill=255)
            avatar.putalpha(mask)

            combined = Image.new("RGBA", bg.size, (0, 0, 0, 0))
            combined.alpha_composite(avatar, self.avatar_absolute)

            frame_size = self.avatar_size + self.frame_size_increase
            frame = frame.resize((frame_size, frame_size))

            frame_pos = (
                self.avatar_absolute[0] - (frame_size - self.avatar_size) // 2,
                self.avatar_absolute[1] - (frame_size - self.avatar_size) // 2 + 50
            )
            combined.alpha_composite(frame, frame_pos)

            # Shadow
            offset_x, offset_y = 35, 20
            shadow = combined.copy().convert("L")
            shadow = shadow.filter(ImageFilter.GaussianBlur(50))
            shadow = Image.eval(shadow, lambda p: int(p * 0.5))
            shadow_rgba = Image.new("RGBA", shadow.size, (0, 0, 0, 0))
            shadow_rgba.putalpha(shadow)
            bg.alpha_composite(shadow_rgba, (offset_x, offset_y))
            bg.alpha_composite(combined)

            # Text
            username = self.normalize_name(member.display_name)
            text = text.replace("{name}", username)

            x1, y1, x2, y2 = self.scroll_boxes.get(bg_name, (100, 180, 520, 620))
            max_width = x2 - x1

            if not self.font_main.exists():
                raise FileNotFoundError(f"Missing font: {self.font_main}")

            font = self.get_scaled_font(text, max_width, self.font_main)
            draw = ImageDraw.Draw(bg)
            lines = self.wrap_text(text, font, max_width)
            self.draw_multiline_text_centered(draw, lines, font, (x1, y1, x2, y2), self.text_color)

            buf = io.BytesIO()
            bg.save(buf, format="PNG")
            buf.seek(0)
            return discord.File(fp=buf, filename="welcome.png"), None

        except Exception as e:
            tb = traceback.format_exc()
            dbg("WELCOME IMAGE FAIL:")
            dbg(tb)

            # Показуємо що саме впало: файл:рядок:помилка
            err = f"{type(e).__name__}: {e}\n\n{tb}"
            return None, err

    # ---------------- embed ----------------
    def make_embed(self, member: discord.Member) -> discord.Embed:
        embed = discord.Embed(
            title=random.choice(self.titles),
            description=f"{member.mention}",
            color=WELCOME_COLOR,
        )
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
        embed.set_image(url="attachment://welcome.png")
        return embed

    # ---------------- listeners ----------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return

        dbg(f"on_member_join: {member.display_name}")
        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            dbg(f"channel not found: {WELCOME_CHANNEL_ID}")
            return

        name = self.normalize_name(member.display_name)
        text = random.choice(self.templates).replace("{name}", name)

        file, err = await self.generate_welcome_image(member, text)
        if file:
            embed = self.make_embed(member)
            await channel.send(file=file, embed=embed)
            dbg("welcome sent to channel")
        else:
            dbg(f"welcome image failed: {err}")

        # DM
        try:
            dm = await member.create_dm()
            await dm.send(
                "Привіт, шукачу пригод!\n"
                "Ти віриш, що сьогодні чудовий день?\n"
                "Я ось вірю, адже ти завітав сьогодні!"
            )
        except discord.Forbidden:
            dbg(f"dm forbidden for {member.display_name}")
        except Exception:
            dbg("dm send failed:")
            dbg(traceback.format_exc())

    # ---------------- debug commands ----------------
    @app_commands.command(name="welcomedebug", description="Показати, які файли бачить WelcomeCog (assets/fonts/backgrounds)")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_debug(self, interaction: discord.Interaction):
        bg_list = [p.name for p in self.background_paths][:20]
        msg = (
            f"where: {self._where()}\n"
            f"assets_dir exists: {self.assets_dir.exists()} ({self.assets_dir})\n"
            f"backgrounds_dir exists: {self.backgrounds_dir.exists()} ({self.backgrounds_dir})\n"
            f"fonts_dir exists: {self.fonts_dir.exists()} ({self.fonts_dir})\n"
            f"found bg*.png: {len(self.background_paths)} sample: {bg_list}\n"
            f"frame exists: {self.avatar_frame_path.exists()} ({self.avatar_frame_path})\n"
            f"font exists: {self.font_main.exists()} ({self.font_main})\n"
        )
        await interaction.response.send_message(f"```text\n{_shorten(msg)}\n```", ephemeral=True)

    @app_commands.command(name="mockwelcome", description="Тест привітання (канал + DM)")
    @app_commands.checks.has_permissions(administrator=True)
    async def mock_welcome(self, interaction: discord.Interaction):
        member = interaction.user
        dbg(f"/mockwelcome by {member.display_name}")

        channel = self.bot.get_channel(TEST_WELCOME_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Тестовий канал не знайдено.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        name = self.normalize_name(member.display_name)
        text = random.choice(self.templates).replace("{name}", name)

        file, err = await self.generate_welcome_image(member, text)
        if file:
            embed = self.make_embed(member)
            msg = await channel.send(file=file, embed=embed)
            # DM
            dm_note = "DM: ✅"
            try:
                dm = await member.create_dm()
                await dm.send(
                    "Привіт, шукачу пригод!\n"
                    "Ти віриш, що сьогодні чудовий день?\n"
                    "Я ось вірю, адже ти завітав сьогодні!"
                )
            except Exception as e:
                dm_note = f"DM: ❌ {type(e).__name__}: {e}"

            await interaction.followup.send(
                f"✅ Тест у канал надіслано.\n{dm_note}\nJump: {msg.jump_url}",
                ephemeral=True
            )
        else:
            # Тут ти побачиш точний stack trace
            await interaction.followup.send(
                f"❌ Не вдалося створити картинку.\n```py\n{_shorten(err)}\n```",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
    dbg("✅ WelcomeCog loaded")
