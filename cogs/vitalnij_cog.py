# -*- coding: utf-8 -*-
import json
import asyncio
import re
from pathlib import Path
from datetime import datetime

import discord
from discord.ext import commands
from discord import app_commands

# ============================ CONFIG ============================
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

# ============================== UI ================================

class RecruitModal(discord.ui.Modal, title="Заявка в гільдію"):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.family = discord.ui.TextInput(label="Family Name", required=True)
        self.display = discord.ui.TextInput(label="Як до тебе звертатися?", required=True)
        self.guild = discord.ui.TextInput(label="Твоя гільдія (в грі)", required=False)
        for i in (self.family, self.display, self.guild): self.add_item(i)

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True) # Запобігає помилці "Дія не вдалася"
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
        await self.cog.process_acceptance(itx)

    @discord.ui.button(label="⛔ Бан", style=discord.ButtonStyle.danger, custom_id="mod_ban")
    async def b(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user): return
        await itx.response.defer(ephemeral=True)
        await self.cog.ban_from_ticket(itx)

# ============================ COG ================================

class VitalnijCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.guild_tags = self.load_tags()

    def load_tags(self):
        if GUILD_TAGS_PATH.exists():
            with open(GUILD_TAGS_PATH, 'r', encoding='utf-8') as f:
                return {k.lower(): v for k, v in json.load(f).items()}
        return {}

    async def is_moderator(self, user):
        return any(r.id in {ROLE_MODERATOR, ROLE_LEADER} for r in user.roles)

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(WelcomeView(self))
        self.bot.add_view(TicketModeratorView(self))

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
        
        meta = {"u": itx.user.id, "t": typ, "f": family, "d": display, "g": guild_name}
        await ch.edit(topic=f"SC_DATA:{json.dumps(meta)}")

        e = discord.Embed(title=f"🎫 Заявка: {typ}", color=discord.Color.teal())
        e.add_field(name="Family", value=family)
        e.add_field(name="Нік", value=display)
        if guild_name: e.add_field(name="Гільдія", value=guild_name)

        await ch.send(f"{g.get_role(ROLE_MODERATOR).mention}", embed=e, view=TicketModeratorView(self))
        await itx.followup.send(f"✅ Тікет: {ch.mention}", ephemeral=True)

    async def process_acceptance(self, itx):
        ch = itx.channel
        data = json.loads(ch.topic.split("SC_DATA:")[1])
        member = await itx.guild.fetch_member(data["u"])
        mode = data["t"]

        # Пошук тега в твоїм JSON
        input_guild = data.get("g", "").lower()
        tag = self.guild_tags.get(input_guild, "SC") #

        if mode == "guild":
            clean_fam = re.sub(r"[^A-Za-z0-9]+", "", data["f"])
            new_nick = f"[{tag}] {clean_fam} | {data['d']}"[:32]
            await member.edit(nick=new_nick)
            await member.add_roles(itx.guild.get_role(ROLE_RECRUIT), itx.guild.get_role(ROLE_SVITOCH))
        elif mode == "friend":
            await member.add_roles(itx.guild.get_role(ROLE_FRIEND))
        elif mode == "guest":
            await member.add_roles(itx.guild.get_role(ROLE_GUEST))

        newbie = itx.guild.get_role(ROLE_NEWBIE)
        if newbie in member.roles: await member.remove_roles(newbie)

        await itx.followup.send("✅ Прийнято! Канал видалиться.")
        await asyncio.sleep(5)
        await ch.delete()

    async def ban_from_ticket(self, itx):
        data = json.loads(itx.channel.topic.split("SC_DATA:")[1])
        member = await itx.guild.fetch_member(data["u"])
        await member.ban(reason="Відмова в тікеті")
        await itx.channel.delete()

async def setup(bot: commands.Bot):
    await bot.add_cog(VitalnijCog(bot))
