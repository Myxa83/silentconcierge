# -*- coding: utf-8 -*-
import os
import random
import asyncio
from io import BytesIO

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# --------- Канали ---------------------------------------------------------------
WELCOME_CHANNEL_ID = 1324854638276509828   # тільки цей канал для вітальних ембедів
FAREWELL_CHANNEL_ID = int(os.getenv("FAREWELL_CHANNEL_ID", 1350571574557675520))
TEST_WELCOME_CHANNEL_ID = 1323457983853887518  # канал для тесту модераторами

# ----------------------------- Допоміжний логер ---------------------------------
def dbg(msg: str) -> None:
    print(f"[DEBUG] {msg}")

# =================================================================================
#                                      COG
# =================================================================================
class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._recent_joins: set[int] = set()

        # Тексти
        self.templates = [
            "@{mention} залетів на нашу базу Silent Cove [BDO EU] з двох ніг!",
            "ДРАКОН ПРОБУДИВСЯ! @{mention} розгортає крила над сервером!",
            "В нашій секті… ой, тобто на сервері, новий учасник – @{mention}!",
            "@{mention} сходить із зірок прямо до нас. Магія тільки починається!",
            "Тиша порушена. @{mention} з’явився у лісі Silent Cove!",
            "КРИТИЧНИЙ ВИБУХ КРУТОСТІ! @{mention} активував(ла) ульту!",
            "Пані та панове, зустрічайте! Найочікуваніший гість – @{mention}!",
        ]
        self.titles = [
            "Прибуття нового духу!",
            "Прибуття нової солодкої булочки!",
            "Прибуття нового котятка!",
            "Прибуття нової жертви!",
        ]

        # Нові бекграунди
        self.backgrounds = [
            "https://i.imgur.com/GICJCR9.png",
            "https://i.imgur.com/sdsY7Wx.png",
            "https://i.imgur.com/R81lLe0.png",
            "https://i.imgur.com/OfLmZHl.png",
        ]
        self.frame_url = "https://i.imgur.com/wlSSfWI.png"

        # Шрифти
        self.font_regular_path = "assets/FixelDisplay-Regular.otf"
        self.font_bold_path    = "assets/FixelDisplay-Bold.otf"

        # Поля сувою для кожної картинки
        self.scroll_boxes = {
            "GICJCR9.png": (360, 220, 1050, 940),
            "sdsY7Wx.png": (340, 200, 1080, 930),
            "R81lLe0.png": (350, 210, 1070, 940),
            "OfLmZHl.png": (330, 190, 1090, 950),
        }
        self.default_scroll_box = (340, 200, 1100, 950)

        self.line_spacing_factor = 1.65
        self.max_font_size = 44
        self.min_font_size = 24

        # Аватарка
        self.avatar_size = 420

    # --------------------------- Рендер вітальної картинки -----------------------
    async def generate_welcome_image(self, member: discord.Member, welcome_text: str) -> discord.File | None:
        try:
            bg_url = random.choice(self.backgrounds)
            async with aiohttp.ClientSession() as session:
                async with session.get(bg_url) as resp:
                    if resp.status != 200:
                        return None
                    bg_bytes = await resp.read()

            bg = Image.open(BytesIO(bg_bytes)).convert("RGBA")
            draw = ImageDraw.Draw(bg)

            key = bg_url.split("/")[-1]
            scroll_box = self.scroll_boxes.get(key, self.default_scroll_box)
            l, t, r, b = scroll_box
            box_w     = max(10, r - l)
            box_h     = b - t

            dn_nbsp   = str(member.display_name).replace(" ", "\u00A0")
            sc_phrase = "Silent\u00A0Cove"
            base_text = welcome_text.replace("{mention}", f"{dn_nbsp} {sc_phrase}")

            def wrap_lines(fnt: ImageFont.FreeTypeFont):
                words = base_text.split()
                lines, cur = [], ""
                for w in words:
                    test = (cur + " " + w).strip()
                    if draw.textlength(test, font=fnt) <= box_w:
                        cur = test
                    else:
                        if cur:
                            lines.append(cur)
                        cur = w
                if cur:
                    lines.append(cur)
                return lines

            font_size = self.max_font_size
            while font_size >= self.min_font_size:
                font      = ImageFont.truetype(self.font_regular_path, font_size)
                font_bold = ImageFont.truetype(self.font_bold_path, font_size) if os.path.exists(self.font_bold_path) else font
                lines     = wrap_lines(font)
                line_h    = int(font_size * self.line_spacing_factor)
                if len(lines) * line_h <= box_h:
                    break
                font_size -= 2
            else:
                font      = ImageFont.truetype(self.font_regular_path, self.min_font_size)
                font_bold = ImageFont.truetype(self.font_bold_path, self.min_font_size) if os.path.exists(self.font_bold_path) else font
                lines     = wrap_lines(font)
                line_h    = int(self.min_font_size * self.line_spacing_factor)

            text_color   = (51, 29, 16, 255)
            shadow_color = (36, 20, 11, 160)

            def draw_soft_shadow_text(base_img: Image.Image, xy: tuple[int, int], txt: str, fnt: ImageFont.FreeTypeFont):
                x, y = xy
                shadow_layer = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
                sdraw = ImageDraw.Draw(shadow_layer)
                sdraw.text((x + 2, y + 2), txt, font=fnt, fill=shadow_color)
                shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(4))
                base_img.alpha_composite(shadow_layer)

            total_h = len(lines) * int(font_size * self.line_spacing_factor)
            y = t + (box_h - total_h) // 2

            for line in lines:
                line_w = draw.textlength(line, font=font)
                x = l + (box_w - line_w) // 2
                draw_soft_shadow_text(bg, (x, y), line, font)
                ImageDraw.Draw(bg).text((x, y), line, font=font, fill=text_color)
                for target in (dn_nbsp, sc_phrase):
                    idx = line.find(target)
                    if idx != -1:
                        x_off = x + draw.textlength(line[:idx], font=font)
                        draw_soft_shadow_text(bg, (x_off, y), target, font_bold)
                        ImageDraw.Draw(bg).text((x_off, y), target, font=font_bold, fill=text_color)
                y += int(font_size * self.line_spacing_factor)

            # Аватар
            avatar_url = str(member.display_avatar.url if member.display_avatar else member.default_avatar.url)
            avatar_bytes = None
            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as resp:
                    if resp.status == 200:
                        avatar_bytes = await resp.read()

            if avatar_bytes:
                av = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
                av = av.resize((self.avatar_size, self.avatar_size))

                mask = Image.new("L", (self.avatar_size, self.avatar_size), 0)
                ImageDraw.Draw(mask).ellipse([0, 0, self.avatar_size, self.avatar_size], fill=255)
                av.putalpha(mask)

                x = bg.width - self.avatar_size - 50
                y = bg.height - self.avatar_size - 50
                bg.paste(av, (x, y), av)

                async with aiohttp.ClientSession() as session:
                    async with session.get(self.frame_url) as resp:
                        if resp.status == 200:
                            frame_bytes = await resp.read()
                            frame = Image.open(BytesIO(frame_bytes)).convert("RGBA")
                            frame = frame.resize((self.avatar_size, self.avatar_size))
                            bg.paste(frame, (x, y), frame)

            buf = BytesIO()
            bg.save(buf, format="PNG")
            buf.seek(0)
            return discord.File(fp=buf, filename="welcome.png")

        except Exception as e:
            dbg(f"Помилка генерації картинки: {e}")
            return None

    # ------------------------------ Ембед ----------------------------------------
    def build_embed(self, member: discord.Member) -> discord.Embed:
        title = random.choice(self.titles)
        embed = discord.Embed(title=title, description=f"{member.mention}", color=discord.Color.teal())
        embed.set_image(url="attachment://welcome.png")
        footer_icon = getattr(getattr(self.bot.user, "display_avatar", None), "url", None)
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=footer_icon)
        return embed

    # ------------------------------ Відправка повідомлення -----------------------
    async def send_welcome_message(self, target, member: discord.Member):
        text = random.choice(self.templates)
        file = await self.generate_welcome_image(member, text)
        if not file:
            return
        embed = self.build_embed(member)
        await target.send(file=file, embed=embed)

    # ------------------------------ Події серверу --------------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot or member.id in self._recent_joins:
            return
        self._recent_joins.add(member.id)

        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            return

        await asyncio.sleep(0.8)
        await self.send_welcome_message(channel, member)

        try:
            await member.send(
                "Вітаю тебе авантюристу в Тихій затоці!\n"
                "Чи віриш ти що сьогодні класний день!\n"
                "Я ось вірю, адже ти завітав!"
            )
        except discord.Forbidden:
            dbg(f"❌ Не вдалося відправити DM користувачу {member.display_name}")

        async def _unlock():
            await asyncio.sleep(10)
            self._recent_joins.discard(member.id)
        asyncio.create_task(_unlock())

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if not channel:
            return
        embed = discord.Embed(
            title="🚪 Учасник покинув сервер",
            description=f"{member.mention} більше з нами нема...",
            color=discord.Color.red(),
        )
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if not channel:
            return

        # DM перед баном
        try:
            dm_embed = discord.Embed(
                title="⛔ Ви заблоковані на сервері Silent Cove",
                description="Ви не виправдали довіри, яку вам надали, тому ми вирішили з вами попрощатися.",
                color=discord.Color.red()
            )
            dm_embed.set_image(url="https://i.imgur.com/E0G8qTz.png")
            await user.send(embed=dm_embed)
            await asyncio.sleep(1)
        except Exception as e:
            dbg(f"⚠️ Не вдалося надіслати DM при бані {user}: {e}")

        reason = "Не вказано"
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    reason = entry.reason or "Не вказано"
                    break
        except Exception as e:
            dbg(f"⚠️ Не вдалося прочитати audit log: {e}")

        embed = discord.Embed(
            title="⛔ Користувача забанено!",
            description=f"{user.mention} порушив(ла) правила Silent Cove.",
            color=discord.Color.red(),
        )
        embed.add_field(name="Причина", value=reason, inline=False)
        await channel.send(embed=embed)

    # --------------------------- Тестова команда ---------------------------
    @app_commands.command(name="testwelcome", description="Надіслати тестове привітання у мод-канал")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_welcome(self, interaction: discord.Interaction):
        member = interaction.user
        channel = self.bot.get_channel(TEST_WELCOME_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Тестовий канал не знайдено.", ephemeral=True)
            return
        await self.send_welcome_message(channel, member)
        await interaction.response.send_message("✅ Тестове привітання надіслано.", ephemeral=True)

# ============================= SETUP ============================================
async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))