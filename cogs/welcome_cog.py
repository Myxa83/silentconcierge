# -*- coding: utf-8 -*-
import random
import time
from io import BytesIO
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

# --------- Канали ---------------------------------------------------------------
WELCOME_CHANNEL_ID = 1324854638276509828          # вітання
FAREWELL_CHANNEL_ID = 1350571574557675520         # прощання/бан/розбан
TEST_WELCOME_CHANNEL_ID = 1370522199873814528     # тест модераторів

# --------- Кольори --------------------------------------------------------------
WELCOME_COLOR = 0x05B2B4   # бірюзовий (вітання / розбан)
FAREWELL_COLOR = 0xFF0000  # червоний (вихід / бан)

def dbg(msg: str) -> None:
    print(f"[DEBUG] {msg}")

# =================================================================================
#                                      COG
# =================================================================================
class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
            "Прибуття нової булочки!",
            "Прибуття нового котятка!",
            "Прибуття нової жертви!",
        ]

        # Фони
        self.backgrounds = [
            "assets/backgrounds/bg1.png",
            "assets/backgrounds/bg2.png",
            "assets/backgrounds/bg3.png",
            "assets/backgrounds/bg4.png",
            "assets/backgrounds/bg5.png",
        ]
        # координати сувою (усі однакові)
        self.scroll_boxes = {
            "bg1.png": (100, 180, 520, 620),
            "bg2.png": (100, 180, 520, 620),
            "bg3.png": (100, 180, 520, 620),
            "bg4.png": (100, 180, 520, 620),
            "bg5.png": (100, 180, 520, 620),
        }

        # Шрифт
        self.font_regular_path = "assets/FixelDisplay-Regular.otf"
        self.max_font_size = 44
        self.min_font_size = 20
        self.line_spacing = 1.25

        # Аватар + рамка
        self.avatar_size = 250
        self.avatar_shadow = 16
        self.avatar_absolute = (1150, 730)
        self.frame_path = "assets/backgrounds/ramka1.png"
        self.frame_alpha_threshold = 10

    # --------------------------- Генерація картинки ---------------------------
    async def generate_welcome_image(self, member: discord.Member, welcome_text: str) -> discord.File | None:
        start_time = time.perf_counter()
        try:
            bg_path = random.choice(self.backgrounds)
            bg_name = Path(bg_path).name
            bg = Image.open(bg_path).convert("RGBA")
            W, H = bg.size
            draw = ImageDraw.Draw(bg)

            nick = str(member.display_name).replace(" ", "\u00A0")
            base_text = welcome_text.replace("{mention}", nick)

            L, T, R, B = self.scroll_boxes[bg_name]
            box_w, box_h = (R - L, B - T)

            def try_load_font(size: int):
                try:
                    return ImageFont.truetype(self.font_regular_path, size)
                except:
                    return ImageFont.load_default()

            def wrap_for_width(text: str, fnt, max_w: int) -> list[str]:
                words, lines, cur = text.split(), [], []
                for w in words:
                    test = (" ".join(cur + [w])) if cur else w
                    if draw.textlength(test, font=fnt) <= max_w:
                        cur.append(w)
                    else:
                        if cur:
                            lines.append(" ".join(cur))
                        cur = [w]
                if cur:
                    lines.append(" ".join(cur))
                return lines

            chosen_lines, font = [], None
            size = self.max_font_size
            while size >= self.min_font_size:
                f = try_load_font(size)
                lines = wrap_for_width(base_text, f, box_w)
                ascent, descent = f.getmetrics()
                line_h = ascent + descent
                total_h = int(len(lines) * line_h * self.line_spacing)
                if total_h <= box_h:
                    chosen_lines, font = lines, f
                    break
                size -= 2
            if not chosen_lines:
                font = try_load_font(self.min_font_size)
                chosen_lines = wrap_for_width(base_text, font, box_w)

            ascent, descent = font.getmetrics()
            line_h = ascent + descent
            total_h = int(len(chosen_lines) * line_h * self.line_spacing)

            # Центрування по вертикалі
            y = T + (box_h - total_h) // 2

            for line in chosen_lines:
                line_w = int(draw.textlength(line, font=font))
                x = L + (box_w - line_w) // 2
                draw.text((x, int(y)), line, font=font, fill=(51, 29, 16, 255))
                y += int(line_h * self.line_spacing)

            # Аватар
            avatar_url = str(member.display_avatar.url or member.default_avatar.url)
            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as resp:
                    if resp.status == 200:
                        avatar_bytes = await resp.read()
                        av = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
                        av = av.resize((self.avatar_size, self.avatar_size), Image.LANCZOS)
                        mask = Image.new("L", (self.avatar_size, self.avatar_size), 0)
                        ImageDraw.Draw(mask).ellipse([0, 0, self.avatar_size, self.avatar_size], fill=255)
                        av.putalpha(mask)

                        ax, ay = self.avatar_absolute

                        # тінь
                        shadow_size = self.avatar_size + 2 * self.avatar_shadow
                        shadow = Image.new("RGBA", (shadow_size, shadow_size), (0, 0, 0, 0))
                        sh_mask = Image.new("L", (self.avatar_size, self.avatar_size), 0)
                        ImageDraw.Draw(sh_mask).ellipse([0, 0, self.avatar_size, self.avatar_size], fill=180)
                        sh_mask = ImageOps.expand(sh_mask, border=self.avatar_shadow, fill=0)
                        shadow.putalpha(sh_mask.filter(ImageFilter.GaussianBlur(radius=12)))
                        bg.alpha_composite(shadow, dest=(ax - self.avatar_shadow, ay - self.avatar_shadow))

                        bg.paste(av, (ax, ay), av)

                        if Path(self.frame_path).exists():
                            frame = Image.open(self.frame_path).convert("RGBA")
                            alpha = frame.split()[3]
                            thr = self.frame_alpha_threshold
                            transp = alpha.point(lambda a: 255 if a < thr else 0, mode="L")
                            bbox = transp.getbbox()
                            if bbox:
                                inner_w = bbox[2] - bbox[0]
                                inner_h = bbox[3] - bbox[1]
                                inner_d = min(inner_w, inner_h)
                                scale = self.avatar_size / float(inner_d)
                                new_w = int(frame.width * scale * (450/self.avatar_size))
                                new_h = int(frame.height * scale * (450/self.avatar_size))
                                frame_resized = frame.resize((new_w, new_h), Image.LANCZOS)
                                off_x = int(bbox[0] * scale)
                                off_y = int(bbox[1] * scale)
                                fx = ax - off_x
                                fy = ay - off_y
                                bg.alpha_composite(frame_resized, dest=(fx, fy))
                            else:
                                fx = ax - (frame.width - self.avatar_size)//2
                                fy = ay - (frame.height - self.avatar_size)//2
                                bg.alpha_composite(frame, dest=(fx, fy))

            buf = BytesIO()
            bg.save(buf, format="PNG")
            buf.seek(0)
            return discord.File(fp=buf, filename="welcome.png")
        except Exception as e:
            dbg(f"❌ Помилка генерації: {e}")
            return None

    # --------------------------- Події ---------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        text = random.choice(self.templates).replace("{mention}", member.display_name)
        file = await self.generate_welcome_image(member, text)
        if file:
            embed = discord.Embed(
                title=random.choice(self.titles),
                description=f"{member.display_name}",
                color=WELCOME_COLOR
            )
            embed.set_image(url="attachment://welcome.png")
            embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
            await channel.send(file=file, embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        embed = discord.Embed(
            title="🚪 Учасник покинув сервер",
            description=f"{member.display_name} більше з нами нема...",
            color=FAREWELL_COLOR
        )
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        embed = discord.Embed(
            title="⛔ Користувача забанено!",
            description=f"{user.mention} порушив правила Silent Cove.",
            color=FAREWELL_COLOR
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
        await channel.send(embed=embed)

    # --------------------------- Команди ---------------------------
    @app_commands.command(name="testwelcome", description="Тест привітання у мод-каналі")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_welcome(self, interaction: discord.Interaction):
        member = interaction.user
        channel = self.bot.get_channel(TEST_WELCOME_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Тестовий канал не знайдено.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        file = await self.generate_welcome_image(member, random.choice(self.templates))
        if file:
            embed = discord.Embed(
                title=random.choice(self.titles),
                description=f"{member.display_name}",
                color=WELCOME_COLOR
            )
            embed.set_image(url="attachment://welcome.png")
            embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
            msg = await channel.send(file=file, embed=embed)
            await interaction.followup.send(f"✅ Тестове привітання: [jump]({msg.jump_url})", ephemeral=True)
        else:
            await interaction.followup.send("❌ Не вдалося створити картинку.", ephemeral=True)

    @app_commands.command(name="ban", description="Забанити користувача на сервері")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_user(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Не вказано"):
        guild = interaction.guild
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)

        await interaction.response.defer(ephemeral=True)
        try:
            await guild.ban(member, reason=reason, delete_message_days=0)
        except Exception as e:
            await interaction.followup.send(f"❌ Не вдалося забанити {member.mention}: {e}", ephemeral=True)
            return

        if channel:
            embed = discord.Embed(
                title="⛔ Користувача забанено!",
                description=f"{member.mention} порушив(ла) правила Silent Cove.",
                color=FAREWELL_COLOR
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            if member.joined_at:
                embed.add_field(name="Дата приєднання", value=discord.utils.format_dt(member.joined_at, style="f"), inline=True)
            embed.add_field(name="Дата виходу", value=discord.utils.format_dt(discord.utils.utcnow(), style="f"), inline=True)
            embed.add_field(name="Причина", value=reason, inline=False)
            embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
            await channel.send(embed=embed)

        await interaction.followup.send(f"✅ {member.mention} був забанений. Причина: {reason}", ephemeral=True)

    @app_commands.command(name="unban", description="Розбанити користувача (за user або ID)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban_user(self, interaction: discord.Interaction, user: discord.User, reason: str = "Не вказано"):
        guild = interaction.guild
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)

        await interaction.response.defer(ephemeral=True)
        try:
            await guild.unban(user, reason=reason)
        except Exception as e:
            await interaction.followup.send(f"❌ Не вдалося розбанити {user.mention}: {e}", ephemeral=True)
            return

        if channel:
            embed = discord.Embed(
                title="🟢 Користувача розбанено",
                description=f"{user.mention} знову може приєднатись до Silent Cove.",
                color=WELCOME_COLOR
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.add_field(name="Причина", value=reason, inline=False)
            embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
            await channel.send(embed=embed)

        await interaction.followup.send(f"✅ {user.mention} розбанений. Причина: {reason}", ephemeral=True)

    @app_commands.command(name="syncall", description="Форсована синхронізація всіх слеш-команд")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_all(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            synced = await self.bot.tree.sync()
            await interaction.followup.send(f"✅ Синхронізовано {len(synced)} слеш-команд.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Помилка при синхронізації: {e}", ephemeral=True)

# ============================= SETUP ============================================
async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))
