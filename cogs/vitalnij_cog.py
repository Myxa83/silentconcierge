# -*- coding: utf-8 -*-
import json
import asyncio
import re
from pathlib import Path
from datetime import datetime

import discord
from discord.ext import commands
from discord import app_commands

# ============================ IDs / CONFIG ============================
BASE_DIR = Path(__file__).resolve().parents[1]
GUILD_TAGS_PATH = BASE_DIR / "config" / "guild_tags.json"

WELCOME_CHAN = 1420430254375178280
CATEGORY_TICKETS = 1323454227816906803
MODLOG_CHAN = 1350571574557675520

ROLE_LEADER = 1323454517664157736
ROLE_MODERATOR = 1375070910138028044
ROLE_RECRUIT = 1323455304708522046
ROLE_FRIEND = 1325124628330446951
ROLE_GUEST = 1325118787019866253
ROLE_NEWBIE = 1420436236987924572
ROLE_SVITOCH = 1383410423704846396

# ============================== UI COMPONENTS ================================

class RecruitModal(discord.ui.Modal, title="Анкета в Silent Cove"):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.family = discord.ui.TextInput(label="Family Name", required=True)
        self.display = discord.ui.TextInput(label="Як до тебе звертатися?", required=True)
        self.guild = discord.ui.TextInput(label="Твоя гільдія (в грі)", required=False, placeholder="Silent Cove, Angry Beavers...")
        for i in (self.family, self.display, self.guild): self.add_item(i)

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        await self.cog.create_ticket(itx, "guild", self.family.value, self.display.value, self.guild.value)

class WelcomeView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Хочу в гільдію", style=discord.ButtonStyle.success, custom_id="welcome_guild")
    async def g(self, itx: discord.Interaction, _):
        await itx.response.send_modal(RecruitModal(self.cog))

    @discord.ui.button(label="Друг", style=discord.ButtonStyle.primary, custom_id="welcome_friend")
    async def f(self, itx: discord.Interaction, _):
        await itx.response.defer(ephemeral=True)
        await self.cog.create_ticket(itx, "friend", itx.user.display_name, itx.user.display_name, "")

    @discord.ui.button(label="Ще не визначився", style=discord.ButtonStyle.secondary, custom_id="welcome_guest")
    async def s(self, itx: discord.Interaction, _):
        await itx.response.defer(ephemeral=True)
        await self.cog.create_ticket(itx, "guest", itx.user.display_name, itx.user.display_name, "")

class TicketModeratorView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="✅ Прийняти", style=discord.ButtonStyle.success, custom_id="mod_accept")
    async def acc(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user): return
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_member(itx)

    @discord.ui.button(label="⛔ Бан", style=discord.ButtonStyle.danger, custom_id="mod_ban")
    async def b(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user): return
        await itx.response.defer(ephemeral=True)
        await self.cog.ban_member(itx)

# ============================== MAIN COG ==============================

class VitalnijCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_tags = self.load_tags()

    def load_tags(self):
        """Завантажує теги з config/guild_tags.json"""
        try:
            if GUILD_TAGS_PATH.exists():
                with open(GUILD_TAGS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return {k.lower().strip(): v for k, v in data.items()}
            return {}
        except Exception as e:
            print(f"[Vitalnij] Помилка завантаження тегів: {e}")
            return {}

    async def is_moderator(self, user):
        return any(r.id in {ROLE_MODERATOR, ROLE_LEADER} for r in user.roles)

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(WelcomeView(self))
        self.bot.add_view(TicketModeratorView(self))
        print("[VitalnijCog] Готовий до роботи.")

    # Команда для адміна
    @app_commands.command(name="send_welcome", description="Надіслати вітальний ембед")
    async def send_welcome(self, itx: discord.Interaction):
        if not itx.user.guild_permissions.administrator:
            return await itx.response.send_message("Немає прав", ephemeral=True)
        
        e = discord.Embed(
            title="<a:SilentCove:1425637670197133444> · Ласкаво просимо до Silent Cove",
            description="Оберіть вашу роль нижче. Наші модератори допоможуть вам.",
            color=discord.Color.dark_teal()
        )
        e.set_footer(text="Silent Concierge by Myxa")
        await itx.channel.send(embed=e, view=WelcomeView(self))
        await itx.response.send_message("✅ Готово", ephemeral=True)

    # Логіка створення тікета
    async def create_ticket(self, itx, typ, family, display, guild_name):
        g = itx.guild
        cat = g.get_channel(CATEGORY_TICKETS)
        
        ch = await g.create_text_channel(
            name=f"{typ}-{itx.user.name}",
            category=cat,
            overwrites={
                g.default_role: discord.PermissionOverwrite(view_channel=False),
                itx.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                g.get_role(ROLE_MODERATOR): discord.PermissionOverwrite(view_channel=True)
            }
        )
        
        meta = {"user_id": itx.user.id, "type": typ, "family": family, "display": display, "guild": guild_name}
        await ch.edit(topic=f"SC_DATA:{json.dumps(meta, ensure_ascii=False)}")

        # Ембед всередині тікета
        info = discord.Embed(title=f"🎫 Нова заявка: {typ}", color=discord.Color.blue())
        info.add_field(name="Family Name", value=family or "—")
        info.add_field(name="Нік", value=display or itx.user.display_name)
        if guild_name: info.add_field(name="Колишня гільдія", value=guild_name)
        
        await ch.send(f"{g.get_role(ROLE_MODERATOR).mention} Новий запит!", embed=info, view=TicketModeratorView(self))
        
        # DM модераторам та Логи
        await self.dm_mods(itx, ch.id, typ, family, display, guild_name)
        await self.log_action("Створено тікет", f"Канал: {ch.mention}\nКористувач: {itx.user.mention}\nТип: {typ}", discord.Color.blurple())
        
        await itx.followup.send(f"✅ Тікет відкрито: {ch.mention}", ephemeral=True)

    # Прийняття учасника
    async def accept_member(self, itx):
        ch = itx.channel
        data = json.loads(ch.topic.split("SC_DATA:")[1])
        member = await itx.guild.fetch_member(data["user_id"])
        mode = data["type"]

        # Пошук тега
        user_guild = data.get("guild", "").lower().strip()
        tag = self.guild_tags.get(user_guild, "SC") # Якщо немає в списку, ставимо SC

        if mode == "guild":
            clean_fam = re.sub(r"[^A-Za-z0-9]+", "", data["family"])
            new_nick = f"[{tag}] {clean_fam} | {data['display']}"[:32]
            await member.edit(nick=new_nick)
            await member.add_roles(itx.guild.get_role(ROLE_RECRUIT), itx.guild.get_role(ROLE_SVITOCH))
        elif mode == "friend":
            await member.add_roles(itx.guild.get_role(ROLE_FRIEND))
        elif mode == "guest":
            await member.add_roles(itx.guild.get_role(ROLE_GUEST))

        newbie = itx.guild.get_role(ROLE_NEWBIE)
        if newbie in member.roles: await member.remove_roles(newbie)

        await self.log_action("Тікет прийнято", f"Користувач: {member.mention}\nРежим: {mode}\nНік: `{member.display_name}`", discord.Color.green())
        await itx.followup.send("✅ Користувача прийнято. Канал видаляється...")
        await asyncio.sleep(5)
        await ch.delete()

    # Бан
    async def ban_member(self, itx):
        data = json.loads(itx.channel.topic.split("SC_DATA:")[1])
        member = await itx.guild.fetch_member(data["user_id"])
        await itx.guild.ban(member, reason="Відмова в тікеті")
        await self.log_action("Бан з тікета", f"Модератор: {itx.user.mention}\nОб'єкт: {member.mention}", discord.Color.red())
        await itx.channel.delete()

    # Функція розсилки модераторам (DM)
    async def dm_mods(self, itx, ch_id, typ, family, display, guild):
        mod_role = itx.guild.get_role(ROLE_MODERATOR)
        if not mod_role: return
        
        e = discord.Embed(title=f"📨 Нова заявка від {itx.user}", color=discord.Color.dark_teal())
        e.add_field(name="Тип", value=typ, inline=True)
        e.add_field(name="Discord створено", value=f"<t:{int(itx.user.created_at.timestamp())}:R>", inline=True)
        e.add_field(name="Тікет", value=f"[Перейти до каналу](https://discord.com/channels/{itx.guild.id}/{ch_id})", inline=False)
        e.set_thumbnail(url=itx.user.display_avatar.url)

        for mod in mod_role.members:
            try: await mod.send(embed=e)
            except: continue

    # Функція логування
    async def log_action(self, title, desc, color):
        log_ch = self.bot.get_channel(MODLOG_CHAN)
        if log_ch:
            e = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.utcnow())
            await log_ch.send(embed=e)

async def setup(bot: commands.Bot):
    await bot.add_cog(VitalnijCog(bot))
