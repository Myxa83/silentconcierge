# -*- coding: utf-8 -*-
# cogs/vitalnij_cog.py — FINAL SAFE VERSION 🌊
import json, aiohttp, asyncio, re
from pathlib import Path
from datetime import datetime
import discord
from discord.ext import commands
from discord import app_commands

# ============================ IDs / CONFIG ============================
WELCOME_CHAN = 1420430254375178280
CATEGORY_TICKETS = 1323454227816906803
ROLE_LEADER = 1323454517664157736
ROLE_MODERATOR = 1375070910138028044
ROLE_RECRUIT = 1323455304708522046
ROLE_FRIEND = 1325124628330446951
ROLE_GUEST = 1325118787019866253
ROLE_NEWBIE = 1420436236987924572
GUILD_ID = 1323454227816906802
TOKEN_PATH = Path("config/credentials.json")

# ============================ HELPERS ============================
def load_json(p: Path):
    if not p.exists(): return {}
    try: return json.loads(p.read_text(encoding="utf-8"))
    except: return {}

# ============================ TOSHI LOOKUP ============================
class ToshiLookup:
    def __init__(self):
        self.base_user_url = "https://toshi.kikkia.dev/api/lookup/user"
        self.base_profile_url = "https://toshi.kikkia.dev/api/lookup/profile"

    def load_token(self):
        if not TOKEN_PATH.exists(): return None
        try:
            return json.loads(TOKEN_PATH.read_text(encoding="utf-8")).get("toshi_token")
        except: return None

    async def fetch_json(self, url, params=None):
        token = self.load_token()
        if not token: return {"error": "Missing token"}
        headers = {"User-Agent": "SilentConcierge/1.0", "Cookie": f"token={token}"}
        try:
            async with aiohttp.ClientSession(headers=headers) as s:
                async with s.get(url, params=params) as r:
                    if r.status != 200: return {"error": f"HTTP {r.status}"}
                    return await r.json()
        except Exception as e: return {"error": str(e)}

    async def get_profile(self, family: str):
        u = await self.fetch_json(self.base_user_url, {"familyName": family, "region": "EU"})
        if not u or "error" in u: return u
        m = u.get("memberships") or []
        if not m: return {"error": "Family not found"}
        pid = next((i.get("id") or i.get("profileTarget") for i in m if i.get("active")), None) or \
              m[-1].get("id") or m[-1].get("profileTarget")
        if not pid: return {"error": "Profile ID not found"}
        p = await self.fetch_json(self.base_profile_url, {"profileTarget": pid})
        if "error" in p: return p
        return {"memberships": m, "profile": p}

# ============================== MODALS ================================
class RecruitModal(discord.ui.Modal, title="Заявка в гільдію"):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.family = discord.ui.TextInput(label="Family Name", required=True)
        self.display = discord.ui.TextInput(label="Як до тебе звертатися?", required=True)
        for i in (self.family, self.display): self.add_item(i)

    async def on_submit(self, itx: discord.Interaction):
        await self.cog.create_ticket(itx, "guild", self.family.value, self.display.value)

class FriendModal(discord.ui.Modal, title="Дружня анкета"):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.family = discord.ui.TextInput(label="Family Name", required=True)
        self.display = discord.ui.TextInput(label="Як до тебе звертатися?", required=True)
        for i in (self.family, self.display): self.add_item(i)

    async def on_submit(self, itx: discord.Interaction):
        await self.cog.create_ticket(itx, "friend", self.family.value, self.display.value)

# ========================== PUBLIC WELCOME VIEW =======================
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
        await self.cog.create_ticket(itx, "guest", itx.user.display_name, itx.user.display_name)

# ======================= MODERATOR VIEW ==============================
class GuildSelect(discord.ui.Select):
    def __init__(self, cog, ch_id: int):
        self.cog, self.ch_id = cog, ch_id
        opts = [discord.SelectOption(label="Silent Cove", value="SC"),
                discord.SelectOption(label="Rumbling Cove", value="RC")]
        super().__init__(placeholder="Обери гільдію…", options=opts, custom_id=f"guild_sel:{ch_id}")

    async def callback(self, itx: discord.Interaction):
        if not await self.cog.is_moderator(itx.user):
            return await itx.response.send_message("🚫 У тебе немає прав.", ephemeral=True)
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_ticket(itx, self.ch_id, "guild", self.values[0])

class TicketModeratorView(discord.ui.View):
    def __init__(self, cog, ch_id: int):
        super().__init__(timeout=None)
        self.cog, self.ch_id = cog, ch_id
        self.add_item(GuildSelect(cog, ch_id))

    @discord.ui.button(label="💬 Додати друга", style=discord.ButtonStyle.primary, custom_id="mod_friend")
    async def f(self, itx, _):
        if not await self.cog.is_moderator(itx.user): 
            return await itx.response.send_message("🚫 Немає прав.", ephemeral=True)
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_ticket(itx, self.ch_id, "friend")

    @discord.ui.button(label="🌫️ Додати гостя", style=discord.ButtonStyle.secondary, custom_id="mod_guest")
    async def g(self, itx, _):
        if not await self.cog.is_moderator(itx.user): 
            return await itx.response.send_message("🚫 Немає прав.", ephemeral=True)
        await itx.response.defer(ephemeral=True)
        await self.cog.accept_ticket(itx, self.ch_id, "guest")

# ============================== MAIN COG ===============================
class VitalnijCog(commands.Cog):
    def __init__(self, bot): 
        self.bot, self.toshi = bot, ToshiLookup()

    async def is_moderator(self, user: discord.Member):
        return any(r.id in {ROLE_MODERATOR, ROLE_LEADER} for r in user.roles)

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(WelcomeView(self))
        self.bot.add_view(TicketModeratorView(self, 0))
        print("[VitalnijCog] Persistent views reloaded")

    @app_commands.command(name="send_welcome", description="Надіслати вітальний ембед Silent Cove")
    async def send_welcome(self, itx: discord.Interaction):
        ch = itx.guild.get_channel(WELCOME_CHAN)
        if not ch:
            return await itx.response.send_message("❌ Канал не знайдено.", ephemeral=True)

        e = discord.Embed(
            title="<a:SilentCove:1425637670197133444> · Ласкаво просимо до **Silent Cove!**",
            description=("Ми раді тебе бачити у нас на сервері!\n"
                         "Це наша **Тиха Затока**, у якій ми будуємо\n"
                         "**Дружнє товариство** та спільноту, яка оточує допомогою й підтримкою.\n\n"
                         "Обери, з якої причини ти завітав до нас.\n\n"
                         "Найкращі герої нашої гільдії змагаються,\n"
                         "проливаючи кров за можливість поспілкуватися з тобою!"),
            color=discord.Color.dark_teal())
        e.set_image(url="https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/%D0%97%D0%B0%D0%BF%D0%B8%D1%81%D1%8C_2025_09_25_02_22_16_748.gif")
        e.set_footer(text="Silent Concierge by Myxa", icon_url=self.bot.user.display_avatar.url)
        await ch.send(embed=e, view=WelcomeView(self))
        await itx.response.send_message("✅ Надіслано вітальне повідомлення.", ephemeral=True)

    # ----------------- створення тикета -----------------
    async def create_ticket(self, itx, typ, family, display):
        await itx.response.defer(ephemeral=True, thinking=True)
        g, m = itx.guild, itx.user
        cat = g.get_channel(CATEGORY_TICKETS)
        ch = await g.create_text_channel(
            name=f"ticket-{m.name}", category=cat,
            overwrites={
                g.default_role: discord.PermissionOverwrite(view_channel=False),
                m: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                g.me: discord.PermissionOverwrite(view_channel=True),
                g.get_role(ROLE_MODERATOR): discord.PermissionOverwrite(view_channel=True)
            }, reason="Ticket created")

        e = discord.Embed(title=f"🎫 Заявка від {m.display_name}", description="Тільки модератори бачать це повідомлення.", color=discord.Color.teal())
        await ch.send(embed=e, view=TicketModeratorView(self, ch.id))
        asyncio.create_task(self.dm_ticket_to_mods(itx, ch.id, typ, family))
        return ch.id

    # ----------------- прийняття тикету -----------------
    async def accept_ticket(self, itx, ch_id, mode, tag=None):
        g = itx.guild
        ch = g.get_channel(ch_id)
        if not ch:
            return

        data = {"guild": ROLE_RECRUIT, "friend": ROLE_FRIEND, "guest": ROLE_GUEST}
        m = next((o for o in ch.overwrites if isinstance(o, discord.Member)), None)
        if not m:
            return

        fam = re.sub(r"[^A-Za-z0-9]+", "", m.display_name)
        tag = tag or "SC"
        new_nick = f"[{tag}] {fam} | {m.display_name}" if mode == "guild" else m.display_name

        # -------- зміна ніку --------
        nick_changed = True
        try:
            await m.edit(nick=new_nick)
        except discord.Forbidden:
            nick_changed = False
        except Exception:
            nick_changed = False

        add_role = g.get_role(data[mode])
        nb = g.get_role(ROLE_NEWBIE)

        # -------- видача ролі --------
        role_added = True
        if add_role:
            try:
                await m.add_roles(add_role, reason=f"Ticket accepted as {mode}")
            except discord.Forbidden:
                role_added = False
            except Exception:
                role_added = False

        # -------- видалення ролі Newbie --------
        role_removed = True
        if nb and nb in m.roles:
            try:
                await m.remove_roles(nb, reason="Ticket accepted cleanup")
            except discord.Forbidden:
                role_removed = False
            except Exception:
                role_removed = False

        # -------- якщо щось не вдалось — DM модеру --------
        msg_parts = []
        if not nick_changed:
            msg_parts.append(f"⚠️ Не вдалося змінити нік користувача **{m.display_name}** — бракує прав або роль стоїть вище.")
        if not role_added:
            msg_parts.append(f"⚠️ Не вдалося видати роль для **{m.display_name}** — перевір права або ієрархію ролей.")
        if not role_removed:
            msg_parts.append(f"⚠️ Не вдалося прибрати роль Newbie у **{m.display_name}**.")

        if msg_parts:
            try:
                await itx.user.send("\n".join(msg_parts))
            except:
                pass

        # -------- закриваємо канал --------
        try:
            await ch.delete(reason=f"Ticket accepted as {mode}")
        except:
            pass

    # ----------------- DM до модів -----------------
    async def dm_ticket_to_mods(self, itx, ticket_channel_id, typ, family):
        g, u = itx.guild, itx.user
        prof = await self.toshi.get_profile(family)
        ts = int(datetime.utcnow().timestamp())
        tmap = {"guild": "🪪 Хоче вступити в гільдію", "friend": "💬 Хоче долучитися як друг", "guest": "🌫️ Ще не визначився"}
        e = discord.Embed(title=f"📨 Нова заявка • {u.display_name}", description=tmap.get(typ, typ), color=discord.Color.dark_teal())
        e.add_field(name="Discord створено", value=f"<t:{int(u.created_at.timestamp())}:F>")
        e.add_field(name="Подано", value=f"<t:{ts}:F>")
        e.add_field(name="Посилання на тікет", value=f"[Відкрити](https://discord.com/channels/{g.id}/{ticket_channel_id})", inline=False)
        if prof and "error" not in prof:
            p = prof.get("profile", {})
            if p.get("class"): e.add_field(name="Клас", value=p["class"])
            if p.get("level"): e.add_field(name="Рівень", value=p["level"])
            if p.get("gearscore"): e.add_field(name="GearScore", value=p["gearscore"])
        e.set_footer(text="Silent Concierge • Автоінфа з Toshi")
        mod_role = g.get_role(ROLE_MODERATOR)
        for mod in mod_role.members:
            try: await mod.send(embed=e)
            except: pass

# ============================ SETUP ==================================
async def setup(bot: commands.Bot):
    await bot.add_cog(VitalnijCog(bot))