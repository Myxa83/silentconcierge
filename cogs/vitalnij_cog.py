Python
# -*- coding: utf-8 -*-
import json
import asyncio
import re
from datetime import datetime
from pathlib import Path

import discord
from discord.ext import commands
from discord import app_commands

# ============================ IDs / CONFIG ============================
WELCOME_CHAN = 1420430254375178280
CATEGORY_TICKETS = 1323454227816906803

ROLE_LEADER = 1323454517664157736
ROLE_MODERATOR = 1323454742965389446

ROLE_SILENT_COVE = 1323454377306327051
ROLE_RUMBLING_COVE = 1323454377339889724

ROLE_RECRUIT = 1323455304708522046
ROLE_FRIEND = 1323455304712978503
ROLE_GUEST = 1323455304708522047
ROLE_SVITOCH = 1323455304708522048
ROLE_NEWBIE = 1420436236987924572

GUILD_TAGS_PATH = Path(__file__).resolve().parents[1] / "config" / "guild_tags.json"

GUILD_TAGS = {
    "Silent Cove": "SC",
    "Rumbling Cove": "RC",
}

# ======================= MODERATOR VIEW ==============================
class GuildSelect(discord.ui.Select):
    def __init__(self, cog):
        self.cog = cog
        options = [
            discord.SelectOption(label="Silent Cove", value="SC"),
            discord.SelectOption(label="Rumbling Cove", value="RC"),
        ]
        super().__init__(
            placeholder="Обери гільдію",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="mod_guild_select",
        )

    async def callback(self, itx: discord.Interaction):
        if not await self.cog.is_moderator(itx.user):
            return await itx.response.send_message("🚫 Немає прав.", ephemeral=True)
        
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_ticket(itx, itx.channel_id, "guild", tag=self.values[0])


class ModeratorView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(GuildSelect(cog))

    @discord.ui.button(label="💬 Додати друга", style=discord.ButtonStyle.secondary, custom_id="mod_friend")
    async def f(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user):
            return await itx.response.send_message("🚫 Немає прав.", ephemeral=True)
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_ticket(itx, itx.channel_id, "friend")

    @discord.ui.button(label="🌫️ Додати гостя", style=discord.ButtonStyle.secondary, custom_id="mod_guest")
    async def g(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user):
            return await itx.response.send_message("🚫 Немає прав.", ephemeral=True)
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_ticket(itx, itx.channel_id, "guest")

    @discord.ui.button(label="⛔ Бан", style=discord.ButtonStyle.danger, custom_id="mod_ban")
    async def b(self, itx: discord.Interaction, _):
        if not await self.cog.is_moderator(itx.user):
            return await itx.response.send_message("🚫 Немає прав.", ephemeral=True)
        await itx.response.defer(ephemeral=True)
        await self.cog.ban_ticket(itx, itx.channel_id)

# ======================= USER VIEW ==================================
class RecruitModal(discord.ui.Modal, title="Заявка"):
    guild = discord.ui.TextInput(label="Твоя гільдія (в грі)", placeholder="Наприклад: SaxyCave", required=False, max_length=64)
    family = discord.ui.TextInput(label="Family Name", placeholder="Наприклад: GOODROOT", required=False, max_length=64)
    display = discord.ui.TextInput(label="Як до тебе звертатися", placeholder="Наприклад: Галя", required=False, max_length=64)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, itx: discord.Interaction):
        # Тут defer не можна, бо модалка вже закривається сама
        await self.cog.create_ticket(itx, "guild", self.family.value, self.display.value, self.guild.value)


class WelcomeView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🪪 Хочу в гільдію", style=discord.ButtonStyle.success, custom_id="user_want_guild")
    async def want_guild(self, itx: discord.Interaction, _):
        await itx.response.send_modal(RecruitModal(self.cog))

    @discord.ui.button(label="💬 Хочу бути другом", style=discord.ButtonStyle.secondary, custom_id="user_want_friend")
    async def want_friend(self, itx: discord.Interaction, _):
        await itx.response.defer(ephemeral=True)
        await self.cog.create_ticket(itx, "friend", itx.user.display_name, itx.user.display_name, "")

    @discord.ui.button(label="🌫️ Я ще не визначився", style=discord.ButtonStyle.secondary, custom_id="user_want_guest")
    async def want_guest(self, itx: discord.Interaction, _):
        await itx.response.defer(ephemeral=True)
        await self.cog.create_ticket(itx, "guest", itx.user.display_name, itx.user.display_name, "")

# ======================= COG ========================================
class VitalnijCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ticket_meta: dict[int, dict] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        # ЦЕ РОБИТЬ КНОПКИ ВІЧНИМИ
        self.bot.add_view(WelcomeView(self))
        self.bot.add_view(ModeratorView(self))
        print("🌊 VitalnijCog: Всі View зареєстровано успішно.")

    # ----------------- Хелпери -----------------
    def _cut32(self, s: str) -> str:
        return (s or "").strip()[:32]

    def _norm_guild(self, s: str) -> str:
        s = (s or "").strip().lower()
        return re.sub(r"[^a-z0-9]+", "", s)

    def _load_guild_tags_file(self) -> dict:
        try:
            if not GUILD_TAGS_PATH.exists(): return {}
            return json.loads(GUILD_TAGS_PATH.read_text(encoding="utf-8"))
        except: return {}

    def _save_guild_tags_file(self, data: dict):
        try:
            GUILD_TAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            GUILD_TAGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except: pass

    async def is_moderator(self, user: discord.Member) -> bool:
        return any(r.id in {ROLE_MODERATOR, ROLE_LEADER} for r in user.roles)

    def set_ticket_meta(self, ch: discord.TextChannel, meta: dict):
        self.ticket_meta[ch.id] = meta
        payload = json.dumps(meta, ensure_ascii=False)
        asyncio.create_task(ch.edit(topic=f"SC_TICKET:{payload}"))

    def get_ticket_meta(self, ch: discord.TextChannel) -> dict:
        if ch.topic and ch.topic.startswith("SC_TICKET:"):
            try:
                return json.loads(ch.topic[len("SC_TICKET:"):])
            except: pass
        return self.ticket_meta.get(ch.id, {})

    # ----------------- Команди та логіка -----------------
    @app_commands.command(name="send_welcome", description="Надіслати вітальне повідомлення")
    async def send_welcome(self, itx: discord.Interaction):
        ch = itx.guild.get_channel(WELCOME_CHAN)
        if not ch: return await itx.response.send_message("❌ Канал не знайдено.", ephemeral=True)
        
        e = discord.Embed(title="🌊 Ласкаво просимо до Silent Cove", description="Оберіть вашу роль нижче.", color=discord.Color.dark_teal())
        await ch.send(embed=e, view=WelcomeView(self))
        await itx.response.send_message("✅ Надіслано.", ephemeral=True)

    async def create_ticket(self, itx: discord.Interaction, typ: str, family: str, display: str, guild_name: str):
        g = itx.guild
        m = itx.user
        cat = g.get_channel(CATEGORY_TICKETS)
        if not cat:
            return await itx.followup.send("❌ Помилка: Категорія не знайдена.") if itx.response.is_done() else await itx.response.send_message("❌ Помилка категорі")

        ts = int(datetime.utcnow().timestamp())
        ch = await g.create_text_channel(
            name=f"{typ}-{m.name}",
            category=cat,
            overwrites={
                g.default_role: discord.PermissionOverwrite(view_channel=False),
                m: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
                g.get_role(ROLE_MODERATOR): discord.PermissionOverwrite(view_channel=True, send_messages=True)
            }
        )

        self.set_ticket_meta(ch, {"typ": typ, "user_id": m.id, "family": family, "display": display, "guild": guild_name})
        
        info = discord.Embed(title=f"🎫 Заявка: {typ}", color=discord.Color.teal())
        info.add_field(name="Family Name", value=family or "Не вказано")
        info.add_field(name="Нік", value=display or m.display_name)
        if guild_name: info.add_field(name="Гільдія", value=guild_name)

        await ch.send(f"{g.get_role(ROLE_MODERATOR).mention if g.get_role(ROLE_MODERATOR) else ''}", embed=info, view=ModeratorView(self))
        
        msg = "✅ Тікет створено!"
        if itx.response.is_done(): await itx.followup.send(msg, ephemeral=True)
        else: await itx.response.send_message(msg, ephemeral=True)

    async def accept_ticket(self, itx: discord.Interaction, ch_id: int, mode: str, tag: str = None):
        g = itx.guild
        ch = g.get_channel(ch_id)
        meta = self.get_ticket_meta(ch)
        member = await g.fetch_member(meta.get("user_id"))
        
        if not member: return await itx.followup.send("❌ Користувач пішов із сервера.")

        family = meta.get("family") or member.name
        display = meta.get("display") or member.display_name
        
        # Логіка нікнейму
        if mode == "guild":
            new_nick = self._cut32(f"[{tag or 'SC'}] {family} | {display}")
            roles_add = [ROLE_RECRUIT, ROLE_SVITOCH]
        elif mode == "friend":
            new_nick = self._cut32(f"{family} | {display}")
            roles_add = [ROLE_FRIEND]
        else:
            new_nick = self._cut32(display)
            roles_add = [ROLE_GUEST]

        try:
            await member.edit(nick=new_nick)
            for rid in roles_add:
                role = g.get_role(rid)
                if role: await member.add_roles(role)
            
            # Прибираємо роль новачка
            newbie_role = g.get_role(ROLE_NEWBIE)
            if newbie_role and newbie_role in member.roles:
                await member.remove_roles(newbie_role)

            await itx.followup.send(f"✅ Прийнято як {mode}!")
            await asyncio.sleep(2)
            await ch.delete()
        except Exception as e:
            await itx.followup.send(f"❌ Помилка: {e}")

    async def ban_ticket(self, itx: discord.Interaction, ch_id: int):
        g = itx.guild
        ch = g.get_channel(ch_id)
        meta = self.get_ticket_meta(ch)
        try:
            member = await g.fetch_member(meta.get("user_id"))
            await g.ban(member, reason="Бан через тікет")
            await ch.delete()
        except:
            await itx.followup.send("❌ Не вдалося забанити.")

async def setup(bot: commands.Bot):
    await bot.add_cog(VitalnijCog(bot))
