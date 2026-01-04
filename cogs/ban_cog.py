# -*- coding: utf-8 -*-
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import asyncio

# ===================== КОНФІГУРАЦІЯ =====================
FAREWELL_CHANNEL_ID = 1350571574557675520
FAREWELL_COLOR_LEAVE = 0xAAAAAA    # 🚪 Вийшов сам
FAREWELL_COLOR_KICK = 0xFFA500     # 📤 Вигнали
FAREWELL_COLOR_BAN = 0xFF0000      # ⛔ Забанено
FAREWELL_COLOR_UNBAN = 0x05B2B4    # 📥 Розбанено

BAN_DM_IMAGE = "https://i.imgur.com/E0G8qTz.png"
BAN_DM_TEXT = "❌ Ви не виправдали наданої вам довіри, і ми вирішили з вами попрощатись!"

# ===================== ДОПОМІЖНІ =====================
def dbg(msg: str):
    print(f"[BANCOG] {msg}")

def get_avatar_url(user_or_member: [discord.User, discord.Member]) -> str:
    avatar_asset = user_or_member.display_avatar
    if avatar_asset.is_animated():
        return avatar_asset.with_format('gif').url
    return avatar_asset.url

def format_discord_time(dt_object: datetime, style: str = 'F') -> str:
    return f"<t:{int(dt_object.timestamp())}:{style}>"

# ===================== КОГ =====================
class BanCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        dbg("✅ BanCog ініціалізовано")

    # ---------- ПОДІЇ ----------

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """🚪 або 📤 — вихід або вигнання (але не бан)."""
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if not channel:
            return

        is_kicked = False
        reason = "Не вказано"

        # --- Перевірка: не бан ---
        try:
            await asyncio.sleep(1)
            await member.guild.fetch_ban(member)
            return  # якщо забанили — не дублюємо
        except discord.NotFound:
            pass
        except Exception as e:
            dbg(f"⚠️ Перевірка бану: {e}")

        # --- Перевірка: чи це кік ---
        try:
            async for entry in member.guild.audit_logs(
                limit=10,
                action=discord.AuditLogAction.kick,
                after=datetime.utcnow() - timedelta(seconds=10)
            ):
                if entry.target.id == member.id:
                    is_kicked = True
                    reason = entry.reason or "Не вказано"
                    break
        except Exception as e:
            dbg(f"⚠️ Аудит Kick: {e}")

        # --- Формуємо ембед ---
        if is_kicked:
            emoji, color = "📤", FAREWELL_COLOR_KICK
            title = f"{emoji} Учасника вигнано"
            desc = f"{member.mention} був вигнаний із сервера."
        else:
            emoji, color = "🚪", FAREWELL_COLOR_LEAVE
            title = f"{emoji} Учасник покинув сервер"
            desc = f"{member.mention} вийшов сам."

        embed = discord.Embed(title=title, description=desc, color=color)
        embed.set_thumbnail(url=get_avatar_url(member))
        embed.add_field(name="Дата приєднання", value=format_discord_time(member.joined_at), inline=True)
        embed.add_field(name="Дата виходу", value=format_discord_time(datetime.utcnow()), inline=True)
        if is_kicked:
            embed.add_field(name="Причина", value=reason, inline=False)
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """⛔ Забанено (не через команду)."""
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if not channel:
            return

        reason = "Причина не вказана"
        executor = "Невідомо"

        try:
            async for entry in guild.audit_logs(
                limit=5,
                action=discord.AuditLogAction.ban,
                after=datetime.utcnow() - timedelta(seconds=5)
            ):
                if entry.target.id == user.id:
                    if entry.user.id == self.bot.user.id:
                        return
                    reason = entry.reason or "Не вказана"
                    executor = entry.user.mention if entry.user else "Невідомо"
                    break
        except Exception as e:
            dbg(f"⚠️ Аудит Ban: {e}")

        emoji, color = "⛔", FAREWELL_COLOR_BAN
        embed = discord.Embed(
            title=f"{emoji} Користувача забанено",
            description=f"{user.mention} забанений. 🚨",
            color=color
        )
        embed.set_thumbnail(url=get_avatar_url(user))
        embed.add_field(name="Виконавець", value=executor, inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        embed.add_field(name="Користувач ID", value=f"{user.id}", inline=False)
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        """📥 Розбанено."""
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if not channel:
            return

        try:
            async for entry in guild.audit_logs(
                limit=5,
                action=discord.AuditLogAction.unban,
                after=datetime.utcnow() - timedelta(seconds=5)
            ):
                if entry.target.id == user.id and entry.user.id == self.bot.user.id:
                    return
        except Exception as e:
            dbg(f"⚠️ Аудит Unban: {e}")

        emoji, color = "📥", FAREWELL_COLOR_UNBAN
        embed = discord.Embed(
            title=f"{emoji} Користувача розбанено",
            description=f"{user.mention} знову може приєднатись до Silent Cove.",
            color=color
        )
        embed.set_thumbnail(url=get_avatar_url(user))
        embed.add_field(name="Користувач ID", value=f"{user.id}", inline=False)
        embed.add_field(name="Час", value=format_discord_time(datetime.utcnow()), inline=True)
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
        await channel.send(embed=embed)

    # ---------- СЛЕШ-КОМАНДИ ----------

    @app_commands.command(name="ban", description="⛔ Забанити користувача з DM")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_user(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Не вказано"):
        guild = interaction.guild
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        dm_success = False

        try:
            dm_embed = discord.Embed(
                title="⛔ Вас забанили",
                description=f"{BAN_DM_TEXT}\n\nПричина: {reason}",
                color=FAREWELL_COLOR_BAN
            )
            dm_embed.set_image(url=BAN_DM_IMAGE)
            await member.send(embed=dm_embed)
            dm_success = True
        except Exception as e:
            dbg(f"⚠️ DM error: {e}")

        await guild.ban(member, reason=reason, delete_message_days=0)

        if channel:
            emoji, color = "⛔", FAREWELL_COLOR_BAN
            embed = discord.Embed(
                title=f"{emoji} Користувача забанено (Команда)",
                description=f"{member.mention} забанений.",
                color=color
            )
            embed.set_thumbnail(url=get_avatar_url(member))
            embed.add_field(name="Виконавець", value=interaction.user.mention, inline=True)
            embed.add_field(name="DM", value=f"{'✅' if dm_success else '❌'}", inline=True)
            embed.add_field(name="Причина", value=reason, inline=False)
            embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
            await channel.send(embed=embed)

        await interaction.response.send_message(
            f"✅ {member.mention} забанений. Причина: {reason}", ephemeral=True
        )

    @app_commands.command(name="unban", description="📥 Розбанити користувача (ID або нік)")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban_user(self, interaction: discord.Interaction, user: discord.User, reason: str = "Не вказано"):
        guild = interaction.guild
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)

        await guild.unban(user, reason=reason)

        if channel:
            emoji, color = "📥", FAREWELL_COLOR_UNBAN
            embed = discord.Embed(
                title=f"{emoji} Користувача розбанено (Команда)",
                description=f"{user.mention} тепер може повернутись.",
                color=color
            )
            embed.set_thumbnail(url=get_avatar_url(user))
            embed.add_field(name="Виконавець", value=interaction.user.mention, inline=True)
            embed.add_field(name="Час", value=format_discord_time(datetime.utcnow()), inline=True)
            embed.add_field(name="Причина", value=reason, inline=False)
            embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
            await channel.send(embed=embed)

        await interaction.response.send_message(
            f"✅ {user.mention} розбанений. Причина: {reason}", ephemeral=True
        )

# ===================== SETUP =====================
async def setup(bot: commands.Bot):