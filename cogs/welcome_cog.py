# -*- coding: utf-8 -*-
import random
import time
from io import BytesIO

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

# --------- Канали ---------------------------------------------------------------
WELCOME_CHANNEL_ID = 1324854638276509828          # вітання
FAREWELL_CHANNEL_ID = 1350571574557675520         # прощання/бан/розбан
TEST_WELCOME_CHANNEL_ID = 1370522199873814528     # тест модераторів

# --------- Кольори --------------------------------------------------------------
WELCOME_COLOR = 0x05B2B4   # бірюзовий (вітання / розбан)
FAREWELL_COLOR = 0xFF0000  # червоний (вихід / бан)

# ----------------------------- Допоміжний логер ---------------------------------
def dbg(msg: str) -> None:
    print(f"[DEBUG] {msg}")

# =================================================================================
#                                      COG
# =================================================================================
class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Тексти / заголовки
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

        # Локальні фони
        self.backgrounds = [
            "assets/backgrounds/bg1.png",
            "assets/backgrounds/bg2.png",
            "assets/backgrounds/bg3.png",
        ]

        # Шрифт
        self.font_regular_path = "assets/FixelDisplay-Regular.otf"
        self.max_font_size = 44

        # Аватар
        self.avatar_size = 420

    # --------------------------- Генерація картинки ---------------------------
    async def generate_welcome_image(self, member: discord.Member, welcome_text: str) -> discord.File | None:
        start_time = time.perf_counter()
        try:
            dbg(f"🔄 Починаю створення картинки для {member.display_name}")

            # Фон
            bg_path = random.choice(self.backgrounds)
            dbg(f"📥 Завантажую фон: {bg_path}")
            try:
                bg = Image.open(bg_path).convert("RGBA")
            except Exception as e:
                dbg(f"❌ Помилка відкриття фону {bg_path}: {e}")
                return None
            dbg("✅ Фон завантажено")
            draw = ImageDraw.Draw(bg)

            # Текст
            dn_nbsp = str(member.display_name).replace(" ", "\u00A0")
            base_text = welcome_text.replace("{mention}", f"{dn_nbsp} Silent\u00A0Cove")
            dbg(f"📝 Додаю текст: {base_text}")

            try:
                font = ImageFont.truetype(self.font_regular_path, self.max_font_size)
            except Exception as e:
                dbg(f"⚠️ Не вдалося завантажити шрифт {self.font_regular_path}, fallback → default. {e}")
                font = ImageFont.load_default()

            # Проста центровка по сувою (координати можна підкрутити під твої фони)
            x, y = 400, 250
            draw.text((x, y), base_text, font=font, fill=(51, 29, 16, 255))
            dbg("✅ Текст додано")

            # Аватар
            avatar_url = str(member.display_avatar.url if member.display_avatar else member.default_avatar.url)
            dbg(f"📥 Завантажую аватар: {avatar_url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(avatar_url) as resp:
                    if resp.status == 200:
                        avatar_bytes = await resp.read()
                        av = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
                        av = av.resize((self.avatar_size, self.avatar_size))

                        # Коло
                        dbg("🖼 Обрізаю аватар у коло")
                        mask = Image.new("L", (self.avatar_size, self.avatar_size), 0)
                        ImageDraw.Draw(mask).ellipse([0, 0, self.avatar_size, self.avatar_size], fill=255)
                        av.putalpha(mask)

                        # Позиція
                        ax = bg.width - self.avatar_size - 50
                        ay = bg.height - self.avatar_size - 50
                        bg.paste(av, (ax, ay), av)
                        dbg("✅ Аватар додано на картинку")
                    else:
                        dbg(f"❌ Помилка завантаження аватара (код {resp.status})")

            # У буфер
            buf = BytesIO()
            bg.save(buf, format="PNG")
            buf.seek(0)
            dbg("💾 Картинка збережена у буфер")

            elapsed = time.perf_counter() - start_time
            dbg(f"⏱ Час генерації картинки: {elapsed:.2f} сек.")
            return discord.File(fp=buf, filename="welcome.png")

        except Exception as e:
            elapsed = time.perf_counter() - start_time
            dbg(f"❌ Помилка генерації картинки: {e}")
            dbg(f"⏱ Час до помилки: {elapsed:.2f} сек.")
            return None

    # --------------------------- Події ---------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            return

        dbg(f"👋 Новий учасник приєднався: {member.display_name}")
        file = await self.generate_welcome_image(member, random.choice(self.templates))
        if file:
            embed = discord.Embed(
                title=random.choice(self.titles),
                description=f"{member.mention}",
                color=WELCOME_COLOR
            )
            embed.set_image(url="attachment://welcome.png")
            embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
            await channel.send(file=file, embed=embed)
            dbg("✅ Привітальне повідомлення відправлено")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if not channel:
            return
        dbg(f"🚪 Учасник покинув сервер: {member.display_name}")

        embed = discord.Embed(
            title="🚪 Учасник покинув сервер",
            description=f"{member.mention} більше з нами нема...",
            color=FAREWELL_COLOR
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        if member.joined_at:
            embed.add_field(name="Дата приєднання", value=discord.utils.format_dt(member.joined_at, style="f"), inline=True)
        embed.add_field(name="Дата виходу", value=discord.utils.format_dt(discord.utils.utcnow(), style="f"), inline=True)
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if not channel:
            return
        dbg(f"⛔ Користувача забанено: {user.name}")

        # DM перед баном
        try:
            dm_embed = discord.Embed(
                title="⛔ Ви заблоковані на сервері Silent Cove",
                description="Ви не виправдали наданої вам довіри і тому ми прощаємось з вами.",
                color=FAREWELL_COLOR
            )
            dm_embed.set_image(url="https://imgur.com/E0G8qTz.png")
            await user.send(embed=dm_embed)
            dbg("✅ DM про бан відправлено")
        except Exception as e:
            dbg(f"⚠️ Не вдалося відправити DM: {e}")

        # Причина з audit log
        reason = "Не вказано"
        try:
            async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    reason = entry.reason or "Не вказано"
                    break
        except Exception as e:
            dbg(f"⚠️ Не вдалося отримати audit log: {e}")

        embed = discord.Embed(
            title="⛔ Користувача забанено!",
            description=f"{user.mention} порушив(ла) правила Silent Cove.",
            color=FAREWELL_COLOR
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Дата виходу", value=discord.utils.format_dt(discord.utils.utcnow(), style="f"), inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
        await channel.send(embed=embed)

    # --------------------------- Слеш-команди ---------------------------
    @app_commands.command(name="testwelcome", description="Тест привітання у мод-каналі")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_welcome(self, interaction: discord.Interaction):
        member = interaction.user
        channel = self.bot.get_channel(TEST_WELCOME_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message("❌ Тестовий канал не знайдено.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        dbg(f"🧪 Запуск тестового привітання для {member.display_name}")
        file = await self.generate_welcome_image(member, random.choice(self.templates))
        if file:
            embed = discord.Embed(
                title=random.choice(self.titles),
                description=f"{member.mention}",
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
        dbg(f"⚔️ Виклик /ban на {member.display_name}, причина: {reason}")

        # DM
        try:
            dm_embed = discord.Embed(
                title="⛔ Ви заблоковані на сервері Silent Cove",
                description="Ви не виправдали наданої вам довіри і тому ми прощаємось з вами.",
                color=FAREWELL_COLOR
            )
            dm_embed.set_image(url="https://imgur.com/E0G8qTz.png")
            await member.send(embed=dm_embed)
            dbg("✅ DM про бан відправлено")
        except Exception as e:
            dbg(f"⚠️ Не вдалося відправити DM: {e}")

        # Бан
        try:
            await guild.ban(member, reason=reason, delete_message_days=0)
            dbg("✅ Користувача забанено")
        except Exception as e:
            dbg(f"❌ Помилка бану: {e}")
            await interaction.followup.send(f"❌ Не вдалося забанити {member.mention}: {e}", ephemeral=True)
            return

        # Повідомлення у канал
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
        dbg(f"🟢 Виклик /unban на {user} (ID: {user.id}), причина: {reason}")

        try:
            await guild.unban(user, reason=reason)
            dbg("✅ Користувача розбанено")
        except Exception as e:
            dbg(f"❌ Помилка розбану: {e}")
            await interaction.followup.send(f"❌ Не вдалося розбанити {user.mention}: {e}", ephemeral=True)
            return

        # Повідомлення у канал
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
        dbg("🔄 Виконую syncall")
        try:
            synced = await self.bot.tree.sync()
            await interaction.followup.send(f"✅ Синхронізовано {len(synced)} слеш-команд.", ephemeral=True)
            dbg(f"✅ Синхронізовано {len(synced)} команд")
        except Exception as e:
            dbg(f"❌ Помилка syncall: {e}")
            await interaction.followup.send(f"❌ Помилка при синхронізації: {e}", ephemeral=True)

# ============================= SETUP ============================================
async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomeCog(bot))