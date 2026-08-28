# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands
from data.mongo_store import load_state, save_state

GUILD_ID = 1323454227816906802
CHANNEL_ID = 1534917454977962076
LEAGUE_ROLE_ID = 1450893024379797514
MAX_PACKS, MIN_MEMBERS, MAX_MEMBERS = 3, 8, 10
TZ = ZoneInfo("Europe/Berlin")
COLOR = 0x3F3A78
FOOTER = "Silent Concierge by Myxa | Ліга гільдій"
ROLES = {"tank": ("🛡️", "Tank"), "dps": ("⚔️", "DPS"), "shai": ("🧪", "Shai")}


def fresh():
    return {"channel_id": CHANNEL_ID, "message_id": None, "packs": [], "roles": {}}


def role_text(key):
    x = ROLES.get(key)
    return f"{x[0]} {x[1]}" if x else "❔"


def pack(state, no):
    return next((p for p in state["packs"] if p["number"] == no), None)


def user_pack(state, uid):
    uid = str(uid)
    for p in state["packs"]:
        if p["leader_id"] == uid:
            return p, "leader"
        if any(x["user_id"] == uid for x in p["members"]):
            return p, "member"
        if any(x["user_id"] == uid for x in p["pending"]):
            return p, "pending"
    return None, None


def count(p):
    return 1 + len(p["members"])


def status(p):
    n = count(p)
    return "🟢 Повна" if n >= 10 else "🟢 Готова" if n >= 8 else "🟡 Формується"


def date_options():
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    now = datetime.now(TZ)
    out = []
    for i in range(14):
        d = (now + timedelta(days=i)).date()
        out.append(discord.SelectOption(
            label=f"{days[d.weekday()]}, {d.strftime('%d.%m.%Y')}", value=d.isoformat(),
            description="з 13:00" if d.weekday() >= 5 else "з 17:00"))
    return out


def time_slots(day_iso):
    d = datetime.fromisoformat(day_iso).date()
    start = datetime(d.year, d.month, d.day, 13 if d.weekday() >= 5 else 17, tzinfo=TZ)
    end = datetime(d.year, d.month, d.day, 1, tzinfo=TZ) + timedelta(days=1)
    out = []
    while start <= end:
        out.append((start.strftime("%H:%M") + (" (+1 день)" if start.date() != d else ""), int(start.timestamp())))
        start += timedelta(minutes=20)
    return out


def pack_embed(no, p, bot):
    if not p:
        e = discord.Embed(title=f"Пачка {no}", description="*Ще не створена.*\nНатисніть **Створити пачку**.", color=COLOR)
        e.add_field(name="Учасники", value="0/10", inline=True)
        e.add_field(name="PL", value="-", inline=True)
    else:
        ts = p["start_ts"]
        local = datetime.fromtimestamp(ts, timezone.utc).astimezone(TZ)
        e = discord.Embed(title=f"Пачка {no} | {status(p)}", color=COLOR,
            description=f"**День і час:** <t:{ts}:F>\n**Час Ліги:** {local:%H:%M} {local.tzname()}\n**PL:** <@{p['leader_id']}> | {role_text(p['leader_role'])}")
        lines = [f"`01.` 👑 {role_text(p['leader_role'])} <@{p['leader_id']}>"]
        lines += [f"`{i:02}.` {role_text(x['role'])} <@{x['user_id']}>" for i, x in enumerate(p["members"], 2)]
        e.add_field(name=f"Учасники ({count(p)}/10)", value="\n".join(lines), inline=False)
        pend = "\n".join(f"⏳ {role_text(x['role'])} <@{x['user_id']}>" for x in p["pending"]) or "Немає"
        e.add_field(name=f"Заявки PL ({len(p['pending'])})", value=pend[:1024], inline=False)
    e.set_footer(text=FOOTER, icon_url=bot.display_avatar.url if bot else None)
    return e


class SimpleSelect(discord.ui.Select):
    def __init__(self, cog, kind, options, *, meta=None, placeholder="Оберіть"):
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)
        self.cog, self.kind, self.meta = cog, kind, meta or {}

    async def callback(self, itx):
        v = self.values[0]
        if self.kind == "pack":
            await self.cog.signup_to(itx, int(v), self.meta["move"])
        elif self.kind == "date":
            await itx.response.edit_message(content="Оберіть час:", view=TimeView(self.cog, v, self.meta))
        elif self.kind == "member":
            await self.cog.member_action(itx, self.meta["pack"], self.meta["action"], int(v))


class OneSelectView(discord.ui.View):
    def __init__(self, select):
        super().__init__(timeout=180)
        self.add_item(select)


class TimeView(discord.ui.View):
    def __init__(self, cog, day, meta, page=0):
        super().__init__(timeout=180)
        slots = time_slots(day)
        opts = [discord.SelectOption(label=a, value=str(b)) for a, b in slots[page*25:(page+1)*25]]
        s = discord.ui.Select(placeholder="Оберіть час", options=opts)
        async def chosen(itx):
            ts = int(s.values[0])
            await (cog.create_finish(itx, ts) if meta["mode"] == "create" else cog.reschedule_finish(itx, meta["pack"], ts))
        s.callback = chosen
        self.add_item(s)
        if len(slots) > 25:
            prev = discord.ui.Button(label="Раніше", disabled=page == 0)
            nxt = discord.ui.Button(label="Пізніше", disabled=(page+1)*25 >= len(slots))
            async def go_prev(itx): await itx.response.edit_message(view=TimeView(cog, day, meta, max(0, page-1)))
            async def go_next(itx): await itx.response.edit_message(view=TimeView(cog, day, meta, page+1))
            prev.callback, nxt.callback = go_prev, go_next
            self.add_item(prev); self.add_item(nxt)


class PLSelect(discord.ui.Select):
    def __init__(self, cog):
        opts = [
            ("🔄", "Оновити повідомлення", "refresh"), ("📋", "Переглянути заявки", "pending"),
            ("✅", "Підтвердити учасника", "approve"), ("❌", "Відхилити заявку", "reject"),
            ("🗑️", "Видалити учасника", "remove"), ("📅", "Змінити день / час", "reschedule"),
            ("👑", "Передати PL", "leader"), ("⛔", "Скасувати пачку", "cancel")]
        super().__init__(placeholder="Керування PL", custom_id="league_pl", row=3,
            options=[discord.SelectOption(emoji=e, label=l, value=v) for e,l,v in opts])
        self.cog = cog
    async def callback(self, itx): await self.cog.pl_action(itx, self.values[0])


class MainView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        for key, style in (("tank", discord.ButtonStyle.primary), ("dps", discord.ButtonStyle.danger), ("shai", discord.ButtonStyle.success)):
            b = discord.ui.Button(label=ROLES[key][1], emoji=ROLES[key][0], style=style, custom_id=f"league_role_{key}", row=0)
            async def cb(itx, k=key): await cog.set_role(itx, k)
            b.callback = cb; self.add_item(b)
        for label, emoji, style, cid, fn in [
            ("Записатися","✅",discord.ButtonStyle.success,"league_signup",lambda i:cog.begin_signup(i,False)),
            ("Перейти","🔁",discord.ButtonStyle.primary,"league_move",lambda i:cog.begin_signup(i,True)),
            ("Відписатися","✖️",discord.ButtonStyle.danger,"league_leave",cog.leave),
            ("Створити пачку","➕",discord.ButtonStyle.secondary,"league_create",cog.begin_create)]:
            b = discord.ui.Button(label=label, emoji=emoji, style=style, custom_id=cid, row=1 if cid != "league_create" else 2)
            b.callback = fn; self.add_item(b)
        self.add_item(PLSelect(cog))


class CancelView(discord.ui.View):
    def __init__(self, cog, no, uid):
        super().__init__(timeout=60); self.cog, self.no, self.uid = cog, no, uid
    @discord.ui.button(label="Так, скасувати", style=discord.ButtonStyle.danger)
    async def yes(self, itx, _):
        if itx.user.id != self.uid: return await itx.response.send_message("Не ваше підтвердження.", ephemeral=True)
        await self.cog.cancel(itx, self.no)
    @discord.ui.button(label="Ні", style=discord.ButtonStyle.secondary)
    async def no(self, itx, _): await itx.response.edit_message(content="Скасування відмінено.", view=None)


class GuildLeagueCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot; self.state = load_state("guild_league", fresh(), document_id="main") or fresh(); self.lock = asyncio.Lock()
        for k,v in fresh().items(): self.state.setdefault(k,v)

    async def cog_load(self): self.bot.add_view(MainView(self))
    def save(self): save_state("guild_league", self.state, document_id="main")

    async def ok_channel(self, itx):
        if itx.guild_id == GUILD_ID and itx.channel_id == CHANNEL_ID: return True
        await itx.response.send_message(f"Працює тільки в <#{CHANNEL_ID}>.", ephemeral=True); return False

    async def refresh(self):
        mid = self.state.get("message_id")
        if not mid: return
        ch = self.bot.get_channel(CHANNEL_ID) or await self.bot.fetch_channel(CHANNEL_ID)
        try: msg = await ch.fetch_message(int(mid))
        except Exception: return
        await msg.edit(embeds=[pack_embed(i, pack(self.state,i), self.bot.user) for i in range(1,4)], view=MainView(self))

    async def set_role(self, itx, key):
        if not await self.ok_channel(itx): return
        uid = str(itx.user.id); self.state["roles"][uid] = key
        p, s = user_pack(self.state, uid)
        if p:
            if s == "leader": p["leader_role"] = key
            else:
                for x in p["members"] + p["pending"]:
                    if x["user_id"] == uid: x["role"] = key
        self.save(); await self.refresh(); await itx.response.send_message(f"Обрано **{role_text(key)}**.", ephemeral=True)

    async def begin_signup(self, itx, move):
        if not await self.ok_channel(itx): return
        uid = str(itx.user.id); role = self.state["roles"].get(uid); cur, s = user_pack(self.state, uid)
        if not role: return await itx.response.send_message("Спочатку оберіть Tank, DPS або Shai.", ephemeral=True)
        if move and not cur: return await itx.response.send_message("Ви ще ніде не записані.", ephemeral=True)
        if move and s == "leader": return await itx.response.send_message("PL спочатку має передати PL або скасувати пачку.", ephemeral=True)
        if not move and cur: return await itx.response.send_message(f"Ви вже в Пачці {cur['number']}. Використайте Перейти.", ephemeral=True)
        nums = [p["number"] for p in self.state["packs"] if count(p) < 10 and (not cur or p["number"] != cur["number"])]
        if not nums: return await itx.response.send_message("Немає доступної пачки.", ephemeral=True)
        opts = [discord.SelectOption(label=f"Пачка {n} | {count(pack(self.state,n))}/10", value=str(n)) for n in nums]
        await itx.response.send_message("Оберіть пачку. PL має підтвердити заявку:", view=OneSelectView(SimpleSelect(self,"pack",opts,meta={"move":move})), ephemeral=True)

    async def signup_to(self, itx, no, move):
        async with self.lock:
            p = pack(self.state,no); uid = str(itx.user.id); role = self.state["roles"].get(uid); cur,s = user_pack(self.state,uid)
            if not p or count(p) >= 10: return await itx.response.edit_message(content="Пачка недоступна.", view=None)
            if s == "leader": return await itx.response.edit_message(content="PL не може перейти напряму.", view=None)
            if cur:
                cur["members"] = [x for x in cur["members"] if x["user_id"] != uid]
                cur["pending"] = [x for x in cur["pending"] if x["user_id"] != uid]
            p["pending"].append({"user_id":uid,"role":role}); self.save(); await self.refresh()
        await itx.response.edit_message(content=f"Заявку до **Пачки {no}** надіслано PL <@{p['leader_id']}>.", view=None)

    async def leave(self, itx):
        if not await self.ok_channel(itx): return
        p,s = user_pack(self.state,itx.user.id)
        if not p: return await itx.response.send_message("Ви ніде не записані.", ephemeral=True)
        if s == "leader": return await itx.response.send_message("PL має передати PL або скасувати пачку.", ephemeral=True)
        uid = str(itx.user.id); p["members"]=[x for x in p["members"] if x["user_id"]!=uid]; p["pending"]=[x for x in p["pending"] if x["user_id"]!=uid]
        self.save(); await self.refresh(); await itx.response.send_message(f"Ви відписалися від Пачки {p['number']}.", ephemeral=True)

    async def begin_create(self, itx):
        if not await self.ok_channel(itx): return
        if len(self.state["packs"]) >= 3: return await itx.response.send_message("Уже створено всі 3 пачки.", ephemeral=True)
        uid=str(itx.user.id)
        if not self.state["roles"].get(uid): return await itx.response.send_message("Спочатку оберіть Tank, DPS або Shai. PL входить у 10 людей.", ephemeral=True)
        if user_pack(self.state,uid)[0]: return await itx.response.send_message("Щоб стати PL нової пачки, спочатку вийдіть з поточної.", ephemeral=True)
        s=SimpleSelect(self,"date",date_options(),meta={"mode":"create"},placeholder="Оберіть день")
        await itx.response.send_message("Оберіть день:", view=OneSelectView(s), ephemeral=True)

    async def create_finish(self, itx, ts):
        async with self.lock:
            if len(self.state["packs"]) >= 3: return await itx.response.edit_message(content="Уже 3 пачки.", view=None)
            uid=str(itx.user.id)
            if user_pack(self.state,uid)[0]: return await itx.response.edit_message(content="Ви вже в іншій пачці.", view=None)
            no=len(self.state["packs"])+1; p={"number":no,"leader_id":uid,"leader_role":self.state["roles"][uid],"start_ts":ts,"members":[],"pending":[]}
            self.state["packs"].append(p); self.save(); await self.refresh()
            ch=self.bot.get_channel(CHANNEL_ID); await ch.send(f"<@&{LEAGUE_ROLE_ID}> створено **Пачку {no}** на <t:{ts}:F>. PL: <@{uid}>.", allowed_mentions=discord.AllowedMentions(roles=True,users=True))
        await itx.response.edit_message(content=f"**Пачку {no}** створено. Ви PL і перший учасник.", view=None)

    async def pl_action(self, itx, action):
        if not await self.ok_channel(itx): return
        if action == "refresh": await self.refresh(); return await itx.response.send_message("Оновлено.", ephemeral=True)
        p = next((x for x in self.state["packs"] if x["leader_id"]==str(itx.user.id)),None)
        if not p: return await itx.response.send_message("Доступно тільки PL.", ephemeral=True)
        no=p["number"]
        if action=="pending":
            t="\n".join(f"{role_text(x['role'])} <@{x['user_id']}>" for x in p["pending"]) or "Заявок немає."
            return await itx.response.send_message(t, ephemeral=True)
        if action in ("approve","reject"):
            arr=p["pending"]
        elif action in ("remove","leader"):
            arr=p["members"]
        else: arr=[]
        if action in ("approve","reject","remove","leader"):
            if not arr: return await itx.response.send_message("Немає кого обирати.", ephemeral=True)
            opts=[discord.SelectOption(label=f"{role_text(x['role'])} | {x['user_id']}",value=x["user_id"]) for x in arr[:25]]
            return await itx.response.send_message("Оберіть учасника:", view=OneSelectView(SimpleSelect(self,"member",opts,meta={"pack":no,"action":action})), ephemeral=True)
        if action=="reschedule":
            s=SimpleSelect(self,"date",date_options(),meta={"mode":"reschedule","pack":no},placeholder="Оберіть день")
            return await itx.response.send_message("Оберіть новий день:", view=OneSelectView(s), ephemeral=True)
        if action=="cancel": return await itx.response.send_message(f"Скасувати Пачку {no}?", view=CancelView(self,no,itx.user.id), ephemeral=True)

    async def member_action(self,itx,no,action,target):
        async with self.lock:
            p=pack(self.state,no); uid=str(target)
            if not p or p["leader_id"]!=str(itx.user.id): return await itx.response.edit_message(content="Ви вже не PL.",view=None)
            if action=="approve":
                if count(p)>=10: return await itx.response.edit_message(content="Пачка 10/10.",view=None)
                x=next((x for x in p["pending"] if x["user_id"]==uid),None)
                if not x: return await itx.response.edit_message(content="Заявку вже оброблено.",view=None)
                p["pending"].remove(x); p["members"].append(x); msg=f"<@{uid}> підтверджено."
            elif action=="reject": p["pending"]=[x for x in p["pending"] if x["user_id"]!=uid]; msg="Заявку відхилено."
            elif action=="remove": p["members"]=[x for x in p["members"] if x["user_id"]!=uid]; msg=f"<@{uid}> видалено."
            else:
                x=next((x for x in p["members"] if x["user_id"]==uid),None)
                if not x: return await itx.response.edit_message(content="Учасника вже немає.",view=None)
                old={"user_id":p["leader_id"],"role":p["leader_role"]}; p["members"].remove(x); p["members"].insert(0,old); p["leader_id"],p["leader_role"]=uid,x["role"]; msg=f"PL передано <@{uid}>."
            self.save(); await self.refresh()
        await itx.response.edit_message(content=msg,view=None)

    async def reschedule_finish(self,itx,no,ts):
        p=pack(self.state,no)
        if not p or p["leader_id"]!=str(itx.user.id): return await itx.response.edit_message(content="Ви вже не PL.",view=None)
        p["start_ts"]=ts; self.save(); await self.refresh(); await itx.response.edit_message(content=f"Час змінено на <t:{ts}:F>.",view=None)

    async def cancel(self,itx,no):
        p=pack(self.state,no)
        if not p or p["leader_id"]!=str(itx.user.id): return await itx.response.edit_message(content="Ви вже не PL.",view=None)
        self.state["packs"]=[x for x in self.state["packs"] if x["number"]!=no]
        for i,x in enumerate(self.state["packs"],1): x["number"]=i
        self.save(); await self.refresh(); await itx.response.edit_message(content=f"Пачку {no} скасовано. Нумерацію оновлено.",view=None)

    @app_commands.command(name="guild_league_panel", description="Створити панель Ліги гільдій")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def panel(self,itx):
        if not itx.user.guild_permissions.administrator: return await itx.response.send_message("Тільки для адміністратора.",ephemeral=True)
        if itx.channel_id!=CHANNEL_ID: return await itx.response.send_message(f"Запустіть у <#{CHANNEL_ID}>.",ephemeral=True)
        await itx.response.send_message(embeds=[pack_embed(i,pack(self.state,i),self.bot.user) for i in range(1,4)],view=MainView(self))
        msg=await itx.original_response(); self.state["message_id"]=msg.id; self.save()


async def setup(bot):
    await bot.add_cog(GuildLeagueCog(bot))
