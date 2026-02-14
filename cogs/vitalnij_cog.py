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
WELCOME_CHAN = 1420430254375178280
CATEGORY_TICKETS = 1323454227816906803
MODLOG_CHAN = 1350571574557675520

# Ролі (Базові)
ROLE_LEADER = 1323454517664157736
ROLE_MODERATOR = 1375070910138028044
ROLE_RECRUIT = 1323455304708522046
ROLE_FRIEND = 1325124628330446951
ROLE_GUEST = 1325118787019866253
ROLE_NEWBIE = 1420436236987924572
ROLE_SVITOCH = 1383410423704846396

# Ролі підрозділів
ROLE_SC = 1468912621737607301  # SilentCove
ROLE_RC = 1468912036745314440  # RumblingCove

GIF_URL = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/%D0%97%D0%B0%D0%BF%D0%B8%D1%81%D1%8C_2025_09_25_02_22_16_748.gif"

# ============================== UI COMPONENTS ================================

class RecruitModal(discord.ui.Modal, title="Анкета в Silent Cove"):
    family = discord.ui.TextInput(label="Family Name", placeholder="Твоє прізвище в грі", required=True)
    display = discord.ui.TextInput(label="Як до тебе звертатися?", placeholder="Твоє ім'я", required=True)

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        await self.cog.create_ticket(itx, "guild", self.family.value, self.display.value, "Applicant")

class FriendModal(discord.ui.Modal, title="Анкета Друга"):
    family = discord.ui.TextInput(label="Family Name", required=True)
    display = discord.ui.TextInput(label="Як до тебе звертатися?", required=True)
    guild = discord.ui.TextInput(label="Твоя гільдія (в грі)", placeholder="Наприклад: Angry Beavers", required=True)

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        await self.cog.create_ticket(itx, "friend", self.family.value, self.display.value, self.guild.value)

class WelcomeView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Хочу в гільдію", style=discord.ButtonStyle.success, custom_id="welcome_guild")
    async def g(self, itx: discord.Interaction, _):
        await itx.response.send_modal(RecruitModal(self.cog))

    @discord.ui.button(label="Друг", style=discord.ButtonStyle.primary, custom_id="welcome_friend")
    async def f(self, itx: discord.Interaction, _):
        await itx.response.send_modal(FriendModal(self.cog))

    @discord.ui.button(label="Ще не визначився", style=discord.ButtonStyle.secondary, custom_id="welcome_guest")
    async def s(self, itx: discord.Interaction, _):
        await itx.response.defer(ephemeral=True)
        await self.cog.create_ticket(itx, "guest", itx.user.display_name, itx.user.display_name, "Guest")

class AcceptChoiceView(discord.ui.View):
    def __init__(self, cog, member, data):
        super().__init__(timeout=60)
        self.cog = cog
        self.member = member
        self.data = data

    @discord.ui.button(label="Прийняти в [SC]", style=discord.ButtonStyle.success)
    async def sc(self, itx: discord.Interaction, _):
        await self.cog.finalize_accept(itx, self.member, self.data, "SC", ROLE_SC)

    @discord.ui.button(label="Прийняти в [RC]", style=discord.ButtonStyle.primary)
    async def rc(self, itx: discord.Interaction, _):
        await self.cog.finalize_accept(itx, self.member, self.data, "RC", ROLE_RC)

class TicketModeratorView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="✅ Прийняти", style=discord.ButtonStyle.success, custom_id="mod_accept")
    async def acc(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user): return
        data = json.loads(itx.channel.topic.split("SC_DATA:")[1])
        member = await itx.guild.fetch_member(data["user_id"])
        
        if data["type"] == "guild":
            await itx.response.send_message("Оберіть підрозділ:", view=AcceptChoiceView(self.cog, member, data), ephemeral=True)
        else:
            await itx.response.defer(ephemeral=True)
            await self.cog.finalize_accept(itx, member, data, None, None)

    @discord.ui.button(label="⛔ Бан", style=discord.ButtonStyle.danger, custom_id="mod_ban")
    async def b(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user): return
        await itx.response.defer(ephemeral=True)
        await self.cog.ban_member(itx)

# ============================== MAIN COG ==============================

class VitalnijCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def is_moderator(self, user: discord.Member) -> bool:
        return any(r.id in {ROLE_MODERATOR, ROLE_LEADER} for r in user.roles)

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(WelcomeView(self))
        self.bot.add_view(TicketModeratorView(self))

    @app_commands.command(name="send_welcome", description="Надіслати вітальний ембед Silent Cove")
    async def send_welcome(self, itx: discord.Interaction):
        if not itx.user.guild_permissions.administrator: return
        
        ch = itx.guild.get_channel(WELCOME_CHAN)
        e = discord.Embed(
            title="<a:SilentCove:1425637670197133444> · Ласкаво просимо до Silent Cove",
            description=(
                "Ми раді тебе бачити у нас на сервері.\n"
                "Це наша Тиха Затока, у якій ми будуємо\n"
                "Дружнє товариство та спільноту, яка оточує допомогою і підтримкою.\n\n"
                "Обери, з якої причини ти завітав до нас.\n\n"
                "Найкращі герої нашої гільдії змагаються,\n"
                "проливаючи кров за можливість поспілкуватися з тобою."
            ),
            color=discord.Color.dark_teal(),
        )
        e.set_image(url=GIF_URL)
        
        # Аватарка БОТА у футері
        bot_avatar = self.bot.user.display_avatar.url if self.bot.user else None
        e.set_footer(text="Silent Concierge by Myxa", icon_url=bot_avatar)

        await ch.send(embed=e, view=WelcomeView(self))
        await itx.response.send_message("✅ Вітальне повідомлення надіслано.", ephemeral=True)

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

        info = discord.Embed(title=f"🎫 Нова заявка: {typ}", color=discord.Color.blue())
        info.add_field(name="Family Name", value=family, inline=True)
        info.add_field(name="Нік", value=display, inline=True)
        info.add_field(name="Гільдія", value=guild_name, inline=False)
        
        await ch.send(f"{g.get_role(ROLE_MODERATOR).mention} Нова заявка!", embed=info, view=TicketModeratorView(self))
        await itx.followup.send(f"✅ Тікет відкрито: {ch.mention}", ephemeral=True)

    async def finalize_accept(self, itx, member, data, tag, division_role_id):
        g = itx.guild
        mode = data["type"]
        roles_to_add = []

        if mode == "guild":
            clean_fam = re.sub(r"[^A-Za-z0-9]+", "", data["family"])
            new_nick = f"[{tag}] {clean_fam} | {data['display']}"[:32]
            try: await member.edit(nick=new_nick)
            except: pass
            roles_to_add = [g.get_role(ROLE_RECRUIT), g.get_role(ROLE_SVITOCH), g.get_role(division_role_id)]
        
        elif mode == "friend":
            guild_tag = data.get("guild", "FR")[:4].upper()
            new_nick = f"[{guild_tag}] {data['display']}"[:32]
            try: await member.edit(nick=new_nick)
            except: pass
            roles_to_add = [g.get_role(ROLE_FRIEND)]
        
        elif mode == "guest":
            roles_to_add = [g.get_role(ROLE_GUEST)]

        await member.add_roles(*[r for r in roles_to_add if r])
        
        newbie = g.get_role(ROLE_NEWBIE)
        if newbie in member.roles: await member.remove_roles(newbie)

        await self.log_action("Тікет прийнято", f"Учасник: {member.mention}\nРежим: {mode}\nТег: {tag or '—'}", discord.Color.green())
        
        await itx.channel.send("✅ Виконано. Канал закриється через 5 секунд.")
        await asyncio.sleep(5)
        await itx.channel.delete()

    async def ban_member(self, itx):
        data = json.loads(itx.channel.topic.split("SC_DATA:")[1])
        member = await itx.guild.fetch_member(data["user_id"])
        await itx.guild.ban(member, reason="Бан через систему тікетів")
        await self.log_action("Бан", f"Модератор: {itx.user.mention}\nЗабанено: {member.mention}", discord.Color.red())
        await itx.channel.delete()

    async def log_action(self, title, desc, color):
        log_ch = self.bot.get_channel(MODLOG_CHAN)
        if log_ch:
            e = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.utcnow())
            await log_ch.send(embed=e)

async def setup(bot: commands.Bot):
    await bot.add_cog(VitalnijCog(bot))
