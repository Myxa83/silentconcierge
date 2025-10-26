# -*- coding: utf-8 -*-
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta
import asyncio

# ===================== КОНФІГУРАЦІЯ =====================
FAREWELL_CHANNEL_ID = 1350571574557675520 # ID каналу для повідомлень (бан/вихід/розбан)
FAREWELL_COLOR_LEAVE = 0xAAAAAA          # Сірий колір для самостійного виходу
FAREWELL_COLOR_KICK = 0xFFA500           # Помаранчевий для вигнання (Kick)
FAREWELL_COLOR_BAN = 0xFF0000            # Червоний для бану
FAREWELL_COLOR_UNBAN = 0x05B2B4          # Бірюзовий для розбану

BAN_DM_IMAGE = "https://i.imgur.com/E0G8qTz.png"
BAN_DM_TEXT = "❌ Ви не виправдали наданої вам довіри, і ми вирішили з вами попрощатись!"

def dbg(msg: str) -> None:
    """Синхронна функція для налагодження (debug)."""
    print(f"[DEBUG] {msg}")

def get_avatar_url(user_or_member: [discord.User, discord.Member]) -> str:
    """Отримує URL аватара, примусово використовуючи GIF, якщо він анімований."""
    avatar_asset = user_or_member.display_avatar
    if avatar_asset.is_animated():
        return avatar_asset.with_format('gif').url
    return avatar_asset.url

def format_discord_time(dt_object: datetime, style: str = 'F') -> str:
    """Конвертує datetime у формат мітки часу Discord: <t:TIMESTAMP:STYLE>"""
    timestamp = int(dt_object.timestamp())
    return f"<t:{timestamp}:{style}>"

class BanCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # --------------------------- ПОДІЇ (АСИНХРОННІ) ---------------------------
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """
        Обробка: Учасник покинув сервер (Leave) АБО його вигнали (Kick).
        """
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if not channel:
            return

        is_kicked = False
        reason = "Не вказано"
        
        # Виправлення таймінгу для Kick
        await asyncio.sleep(1) 
        
        # ПЕРЕВІРКА НА ВИГНАННЯ (Kick) через Аудит-логи
        try:
            async for entry in member.guild.audit_logs(
                limit=10, 
                action=discord.AuditLogAction.kick, 
                after=datetime.utcnow() - timedelta(seconds=10) 
            ):
                if entry.target.id == member.id:
                    is_kicked = True
                    reason = entry.reason if entry.reason else "Не вказано"
                    break
        except Exception as e:
            dbg(f"⚠️ Помилка читання аудит-логів (Kick): {e}")

        
        # СТВОРЕННЯ EMBED
        if is_kicked:
            title_text = "🚫 Учасника вигнано (Kick)!"
            description_text = f"Такого ми втратили: {member.mention}."
            color_used = FAREWELL_COLOR_KICK
            fields = [("Причина", reason, False)]
        else:
            title_text = "🚪 Учасник покинув сервер"
            description_text = f"{member.mention} більше з нами нема."
            color_used = FAREWELL_COLOR_LEAVE
            fields = [] 

        embed = discord.Embed(title=title_text, description=description_text, color=color_used)
        embed.set_thumbnail(url=get_avatar_url(member))
        
        # Динамічний час приєднання та виходу
        joined_time = format_discord_time(member.joined_at)
        leave_time = format_discord_time(datetime.utcnow())
        
        embed.add_field(name="Дата приєднання", value=joined_time, inline=True)
        embed.add_field(name="Дата виходу", value=leave_time, inline=True)
        
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
            
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)

        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """
        Обробка бану, який був викликаний не через команду бота.
        """
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if not channel:
            return
            
        reason = "Причина не вказана"
        executor = "Невідомо"
        
        # Перевіряємо Аудит-логи, щоб визначити, чи це не бан від команди бота
        try:
            async for entry in guild.audit_logs(
                limit=5, 
                action=discord.AuditLogAction.ban,
                after=datetime.utcnow() - timedelta(seconds=5)
            ):
                if entry.target.id == user.id:
                    # Якщо виконавець - сам бот, команда `/ban` сама надішле повідомлення
                    if entry.user.id == self.bot.user.id:
                        return
                        
                    reason = entry.reason if entry.reason else "Не вказана"
                    executor = entry.user.mention if entry.user else "Невідомо"
                    break
        except Exception as e:
            dbg(f"⚠️ Помилка читання аудит-логів (Ban): {e}")

        # СТВОРЕННЯ ЄДИНОГО EMBED
        embed = discord.Embed(
            title="⛔ Користувача забанено! (Системно)",
            description=f"{user.mention} забанений. :rotating_light:",
            color=FAREWELL_COLOR_BAN
        )
        
        embed.set_thumbnail(url=get_avatar_url(user))
        
        embed.add_field(name="Користувач ID", value=f"{user.id}", inline=False)
        embed.add_field(name="Виконавець", value=executor, inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)

        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        """
        Обробка розбану, який був викликаний не через команду бота (для уникнення дублювання).
        """
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        if not channel:
            return
        
        # Перевіряємо Аудит-логи, щоб ігнорувати розбани від команди `/unban`
        try:
            async for entry in guild.audit_logs(
                limit=5, 
                action=discord.AuditLogAction.unban,
                after=datetime.utcnow() - timedelta(seconds=5)
            ):
                # Якщо виконавець - сам бот, команда `/unban` сама надішле повідомлення.
                if entry.target.id == user.id and entry.user.id == self.bot.user.id:
                    return # Ігноруємо
        except Exception as e:
            dbg(f"⚠️ Помилка читання аудит-логів (Unban): {e}")
        
        # Повідомлення для системних розбанів
        embed = discord.Embed(
            title="🟢 Користувача розбанено (Системно)",
            description=f"{user.mention} знову може приєднатись до Silent Cove.",
            color=FAREWELL_COLOR_UNBAN
        )
        
        embed.set_thumbnail(url=get_avatar_url(user))
        embed.add_field(name="Користувач ID", value=f"{user.id}", inline=False)
        embed.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)

        await channel.send(embed=embed)

    # --------------------------- КОМАНДИ СЛЭШ (АСИНХРОННІ) ---------------------------
    
    @app_commands.command(name="ban", description="Забанити користувача з повідомленням у DM")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_user(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Не вказано"):
        guild = interaction.guild
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)
        dm_success = False

        # 1. DM перед баном
        try:
            dm_embed = discord.Embed(
                title="⛔ Вас забанили",
                description=f"{BAN_DM_TEXT}\n\nПричина: {reason}",
                color=FAREWELL_COLOR_BAN
            )
            dm_embed.set_image(url=BAN_DM_IMAGE)
            
            await asyncio.sleep(0.5) 
            await member.send(embed=dm_embed)
            dm_success = True
        except discord.errors.Forbidden:
            dbg("⚠️ Не вдалося надіслати DM (Forbidden)")
        except Exception as e:
            dbg(f"⚠️ Не вдалося надіслати DM: {e}")

        # 2. АСИНХРОННИЙ бан
        await guild.ban(member, reason=reason, delete_message_days=0)

        # 3. Повідомлення у канал
        if channel:
            embed = discord.Embed(
                title="⛔ Користувача забанено! (Команда)",
                description=f"{member.mention} забанений. :rotating_light:",
                color=FAREWELL_COLOR_BAN
            )
            
            embed.set_thumbnail(url=get_avatar_url(member))
            
            embed.add_field(name="Виконавець", value=interaction.user.mention, inline=True)
            embed.add_field(name="DM", value=f"Надіслано: {'✅' if dm_success else '❌'}", inline=True)
            embed.add_field(name="Причина", value=reason, inline=False)
            await channel.send(embed=embed)

        await interaction.response.send_message(f"✅ {member.mention} забанений. Причина: {reason}", ephemeral=True)

    @app_commands.command(name="unban", description="Розбанити користувача. Введіть ID або нік.")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban_user(self, interaction: discord.Interaction, user: discord.User, reason: str = "Не вказано"):
        guild = interaction.guild
        channel = self.bot.get_channel(FAREWELL_CHANNEL_ID)

        # АСИНХРОННИЙ розбан
        await guild.unban(user, reason=reason)

        if channel:
            embed = discord.Embed(
                title="🟢 Користувача розбанено (Команда)",
                description=f"{user.mention} знову може приєднатись до Silent Cove.",
                color=FAREWELL_COLOR_UNBAN
            )
            
            unban_time = format_discord_time(datetime.utcnow())
            
            embed.set_thumbnail(url=get_avatar_url(user))
            
            # ОНОВЛЕНО: Клікабельний виконавець
            embed.add_field(name="Виконавець", value=interaction.user.mention, inline=True) 
            # ОНОВЛЕНО: Час розбану в форматі Discord
            embed.add_field(name="Час розбану", value=unban_time, inline=True) 
            # ОНОВЛЕНО: ID користувача
            embed.add_field(name="Користувач ID", value=f"{user.id}", inline=False) 
            embed.add_field(name="Причина", value=reason, inline=False)
            await channel.send(embed=embed)

        # ОНОВЛЕНО: Підказка для модератора у відповіді на команду
        await interaction.response.send_message(
            f"✅ {user.mention} розбанений. Причина: {reason}\n"
            f"**💡 Підказка:** Для цієї команди потрібно вводити **ID** або **нік** користувача, а не згадку (@).", 
            ephemeral=True
        )

# ============================= SETUP ============================================
async def setup(bot: commands.Bot):
    await bot.add_cog(BanCog(bot))