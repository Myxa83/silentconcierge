# -*- coding: utf-8 -*-
# bbf_cog_eng.py — Multi-server BBF registration system

import asyncio
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from pymongo import MongoClient

# ─── MongoDB ─────────────────────────────────────────────────────────────────

_mongo_client = None
_mongo_db     = None

def _get_db():
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        url = os.environ.get("MONGODB_URL", "")
        _mongo_client = MongoClient(url, serverSelectionTimeoutMS=10000)
        _mongo_db = _mongo_client["bbf_global"]
        print(f"[BBF] MongoDB connected: {_mongo_db.name}")
    return _mongo_db

# ─── Constants ───────────────────────────────────────────────────────────────

MAX_SPOTS  = 20
GALLEY_MIN = 8

# CEST = UTC+2
CEST_OFFSET = timedelta(hours=2)

REMINDER_HOUR_CEST    = 19
REMINDER_MINUTE_CEST  = 30
INVITE_HOUR_CEST      = 19
INVITE_MINUTE_CEST    = 45
BBF_START_HOUR_CEST   = 20
BBF_START_MINUTE_CEST = 0

DAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    6: "Sunday",
}

GALLEY_TEAMS = ["Galley Crew"]
SHIP_TEAMS   = ["Flight", "Balance", "Progress", "Bravery", "Panaxion", "Star of Epheria"]
ALL_TEAMS    = GALLEY_TEAMS + SHIP_TEAMS

BBF_IMAGES = [
    "assets/backgrounds/image-65.webp",
    "assets/backgrounds/2026-03-06_99110141.PNG",
    "assets/backgrounds/PN260416.png",
    "assets/backgrounds/a56dd81618920250304171316184.png",
    "assets/backgrounds/ed682f59d7420260410101500360 (1).jpg",
    "assets/backgrounds/3e703842-4873-41c2-9060-20fd9fdc0109.png",
]

# ─── Per-server data ──────────────────────────────────────────────────────────

def _guild_col(guild_id: int):
    return _get_db()[f"bbf_{guild_id}"]

def _load_config(guild_id: int) -> dict:
    try:
        doc = _get_db()["bbf_config"].find_one({"_id": str(guild_id)})
        if doc:
            doc.pop("_id", None)
            return doc
    except Exception as e:
        print(f"[BBF] Config load error: {e}")
    return {}

def _save_config(guild_id: int, config: dict) -> None:
    try:
        _get_db()["bbf_config"].replace_one(
            {"_id": str(guild_id)},
            {"_id": str(guild_id), **config},
            upsert=True,
        )
    except Exception as e:
        print(f"[BBF] Config save error: {e}")

def _load_data(guild_id: int) -> dict:
    try:
        doc = _guild_col(guild_id).find_one({"_id": "main"})
        if doc:
            doc.pop("_id", None)
            return doc
    except Exception as e:
        print(f"[BBF] Load error: {e}")
    return _empty_data()

def _save_data(guild_id: int, data: dict) -> None:
    try:
        _guild_col(guild_id).replace_one(
            {"_id": "main"}, {"_id": "main", **data}, upsert=True,
        )
    except Exception as e:
        print(f"[BBF] Save error: {e}")

def _empty_data() -> dict:
    return {
        "week": {}, "week_dates": {}, "points": {},
        "channel_id": None, "message_ids": {}, "thread_ids": {},
        "reminder_msg_ids": {}, "confirmed": {},
        "used_images": [], "day_images": {},
        "reminded": {}, "invited": {},
    }

def _empty_day() -> dict:
    return {"main": [], "waitlist": [], "vacation": [], "cant": []}

# ─── Backups ──────────────────────────────────────────────────────────────────

def _save_backup(guild_id: int, data: dict) -> None:
    try:
        db = _get_db()
        backup_id = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M")
        backup = {"_id": backup_id, "timestamp": datetime.now(timezone.utc).isoformat(), **data}
        db[f"bbf_backups_{guild_id}"].replace_one({"_id": backup_id}, backup, upsert=True)
        backups = list(db[f"bbf_backups_{guild_id}"].find({}, {"_id": 1}).sort("_id", -1))
        if len(backups) > 48:
            old_ids = [b["_id"] for b in backups[48:]]
            db[f"bbf_backups_{guild_id}"].delete_many({"_id": {"$in": old_ids}})
    except Exception as e:
        print(f"[BBF] Backup error: {e}")

def _list_backups(guild_id: int) -> list:
    try:
        return list(_get_db()[f"bbf_backups_{guild_id}"].find(
            {}, {"_id": 1, "timestamp": 1}
        ).sort("_id", -1).limit(20))
    except Exception:
        return []

def _restore_backup(guild_id: int, backup_id: str) -> dict | None:
    try:
        doc = _get_db()[f"bbf_backups_{guild_id}"].find_one({"_id": backup_id})
        if doc:
            doc.pop("_id", None)
            doc.pop("timestamp", None)
            return doc
    except Exception:
        return None

# ─── Week dates ───────────────────────────────────────────────────────────────

def _now_cest() -> datetime:
    """Current time in CEST."""
    return datetime.now(timezone.utc) + CEST_OFFSET

def _get_week_dates() -> dict[int, datetime]:
    now    = _now_cest()
    monday = now - timedelta(days=now.weekday())
    return {day_num: monday + timedelta(days=day_num) for day_num in DAY_NAMES}

def _bbf_timestamp(day_date: datetime) -> int:
    """Unix timestamp for BBF start on given date (CEST)."""
    target = day_date.replace(
        hour=BBF_START_HOUR_CEST, minute=BBF_START_MINUTE_CEST,
        second=0, microsecond=0,
    )
    # Convert CEST to UTC for timestamp
    target_utc = target - CEST_OFFSET
    return int(target_utc.replace(tzinfo=timezone.utc).timestamp())

def _get_ts_for_day(data: dict, day_num: int) -> int:
    date_str = data.get("week_dates", {}).get(str(day_num))
    if date_str:
        d = datetime.fromisoformat(date_str)
        return _bbf_timestamp(d)
    return _bbf_timestamp(_now_cest())

# ─── Image picker ─────────────────────────────────────────────────────────────

def _pick_image(data: dict, day_key: str) -> str:
    if day_key in data.get("day_images", {}):
        return data["day_images"][day_key]
    used = data.get("used_images", [])
    available = [img for img in BBF_IMAGES if img not in used]
    if not available:
        available = BBF_IMAGES[:]
        data["used_images"] = []
    chosen = random.choice(available)
    data.setdefault("used_images", []).append(chosen)
    data.setdefault("day_images", {})[day_key] = chosen
    return chosen

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_entry(day_data: dict, uid: str) -> dict | None:
    for e in day_data["main"] + day_data["waitlist"]:
        if e["uid"] == uid:
            return e
    return None

def _get_status(day_data: dict, uid: str) -> str | None:
    for e in day_data["main"]:
        if e["uid"] == uid: return "main"
    for e in day_data["waitlist"]:
        if e["uid"] == uid: return "waitlist"
    if uid in day_data["vacation"]: return "vacation"
    if uid in day_data["cant"]: return "cant"
    return None

def _remove_uid(day_data: dict, uid: str) -> str | None:
    prev = _get_status(day_data, uid)
    day_data["main"]     = [e for e in day_data["main"]     if e["uid"] != uid]
    day_data["waitlist"] = [e for e in day_data["waitlist"] if e["uid"] != uid]
    if uid in day_data["vacation"]: day_data["vacation"].remove(uid)
    if uid in day_data["cant"]:     day_data["cant"].remove(uid)
    return prev

def _galley_count(day_data: dict) -> int:
    return sum(1 for e in day_data["main"] if e["team"] in GALLEY_TEAMS)

def _promote_from_waitlist(day_data: dict) -> str | None:
    if len(day_data["main"]) < MAX_SPOTS and day_data["waitlist"]:
        entry      = day_data["waitlist"].pop(0)
        galley_now = _galley_count(day_data)
        if galley_now < GALLEY_MIN and entry["team"] not in GALLEY_TEAMS:
            entry["original_team"] = entry["team"]
            entry["team"]          = GALLEY_TEAMS[0]
            entry["auto_galley"]   = True
        else:
            entry["auto_galley"] = False
        day_data["main"].append(entry)
        return entry["uid"]
    return None

def _refill_galley(day_data: dict) -> str | None:
    if _galley_count(day_data) >= GALLEY_MIN:
        return None
    for entry in reversed(day_data["main"]):
        if entry["team"] not in GALLEY_TEAMS and not entry.get("auto_galley"):
            entry["original_team"] = entry["team"]
            entry["team"]          = GALLEY_TEAMS[0]
            entry["auto_galley"]   = True
            return entry["uid"]
    return None

async def _try_send_dm(guild: discord.Guild, uid: str, msg: str) -> None:
    try:
        member = guild.get_member(int(uid))
        if member:
            await member.send(msg)
    except Exception:
        pass

# ─── Embeds ───────────────────────────────────────────────────────────────────

def _build_embed(
    day_num: int, day_data: dict, points: dict,
    guild: discord.Guild, bot_user, image_path: str | None, data: dict,
) -> discord.Embed:
    day_name   = DAY_NAMES[day_num]
    day_key    = str(day_num)
    ts         = _get_ts_for_day(data, day_num)
    date_str   = data.get("week_dates", {}).get(day_key, "")
    date_label = ""
    if date_str:
        d = datetime.fromisoformat(date_str)
        date_label = f" {d.day:02}.{d.month:02}"

    embed = discord.Embed(
        title=f"⚓ BBF — {day_name}{date_label}",
        description=f"🕹️ Start: <t:{ts}:f>",
        color=discord.Color.from_rgb(45, 60, 110),
    )

    galley_main = [e for e in day_data["main"] if e["team"] in GALLEY_TEAMS]
    ship_main   = [e for e in day_data["main"] if e["team"] not in GALLEY_TEAMS]
    total_main  = len(day_data["main"])

    galley_lines = []
    for i, entry in enumerate(galley_main, 1):
        member    = guild.get_member(int(entry["uid"]))
        name      = member.mention if member else f"<@{entry['uid']}>"
        pts       = points.get(entry["uid"], 0)
        pts_str   = f" `[{pts}🏅]`" if pts > 0 else ""
        auto_mark = " *(auto)*" if entry.get("auto_galley") else ""
        galley_lines.append(f"`{i:02}.` {name}{pts_str}{auto_mark}")

    galley_need   = max(0, GALLEY_MIN - len(galley_main))
    galley_status = f" ⚠️ need {galley_need} more" if galley_need > 0 else " ✅"
    embed.add_field(
        name=f"🚢 Galley ({len(galley_main)}/{GALLEY_MIN}){galley_status}",
        value="\n".join(galley_lines) if galley_lines else "*Empty*",
        inline=False,
    )

    ship_lines = []
    for i, entry in enumerate(ship_main, 1):
        member  = guild.get_member(int(entry["uid"]))
        name    = member.mention if member else f"<@{entry['uid']}>"
        pts     = points.get(entry["uid"], 0)
        pts_str = f" `[{pts}🏅]`" if pts > 0 else ""
        ship_lines.append(f"`{i:02}.` {name} — *{entry['team']}*{pts_str}")

    embed.add_field(
        name=f"⛵ All Ships ({len(ship_main)})",
        value="\n".join(ship_lines) if ship_lines else "*Empty*",
        inline=False,
    )

    remaining = MAX_SPOTS - total_main
    embed.add_field(
        name=f"📊 Total: {total_main}/{MAX_SPOTS}",
        value=f"Free spots: **{remaining}**" if remaining > 0 else "**All spots filled!**",
        inline=False,
    )

    if day_data["waitlist"]:
        wait_lines = []
        for i, entry in enumerate(day_data["waitlist"], 1):
            member  = guild.get_member(int(entry["uid"]))
            name    = member.mention if member else f"<@{entry['uid']}>"
            pts     = points.get(entry["uid"], 0)
            pts_str = f" `[{pts}🏅]`" if pts > 0 else ""
            wait_lines.append(f"`{i}.` {name} — *{entry['team']}*{pts_str}")
        embed.add_field(
            name=f"⏳ Waitlist ({len(day_data['waitlist'])})",
            value="\n".join(wait_lines),
            inline=False,
        )

    if day_data["vacation"]:
        vac_names = []
        for uid in day_data["vacation"]:
            member = guild.get_member(int(uid))
            vac_names.append(member.mention if member else f"<@{uid}>")
        embed.add_field(
            name=f"🛟 On Leave ({len(day_data['vacation'])})",
            value="\n".join(vac_names),
            inline=False,
        )

    if image_path:
        embed.set_image(url=f"attachment://{Path(image_path).name}")

    embed.set_footer(
        text="Silent Concierge by Myxa  |  🍾 Rom, Rom, ROM!",
        icon_url=bot_user.display_avatar.url if bot_user else None,
    )
    return embed


def _build_reminder_embed(
    day_num: int, day_data: dict, confirmed_uids: list,
    guild: discord.Guild, bot_user, data: dict,
) -> discord.Embed:
    ts = _get_ts_for_day(data, day_num)
    embed = discord.Embed(
        title="⚔️ Sea Battle — Readiness Check!",
        description=(
            f"BBF starts <t:{ts}:f>!\n\n"
            "**Have you already joined the Sea Battle in game?**\n"
            "Press the button below to confirm!"
        ),
        color=discord.Color.from_rgb(180, 30, 30),
    )
    main_uids       = [e["uid"] for e in day_data["main"]]
    confirmed_lines = []
    waiting_lines   = []
    for uid in main_uids:
        member = guild.get_member(int(uid))
        name   = member.mention if member else f"<@{uid}>"
        if uid in confirmed_uids:
            confirmed_lines.append(f"✅ {name}")
        else:
            waiting_lines.append(f"⏳ {name}")
    if confirmed_lines:
        embed.add_field(name=f"✅ Confirmed ({len(confirmed_lines)})", value="\n".join(confirmed_lines), inline=True)
    if waiting_lines:
        embed.add_field(name=f"⏳ Waiting ({len(waiting_lines)})", value="\n".join(waiting_lines), inline=True)
    embed.set_footer(
        text="Silent Concierge by Myxa  |  🍾 Rom, Rom, ROM!",
        icon_url=bot_user.display_avatar.url if bot_user else None,
    )
    return embed

# ─── Views ───────────────────────────────────────────────────────────────────

def _make_confirm_view(day_num: int, guild_id: int) -> discord.ui.View:
    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(
            label="Yes, I joined!",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"bbf_confirm_{guild_id}_{day_num}",
        )
        async def btn_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            gid      = interaction.guild.id
            data     = _load_data(gid)
            day_key  = str(day_num)
            uid      = str(interaction.user.id)
            day_data = data.get("week", {}).get(day_key)
            if not day_data or _get_status(day_data, uid) != "main":
                await interaction.response.send_message("ℹ️ You are not in the main list for this day.", ephemeral=True)
                return
            confirmed = data.setdefault("confirmed", {}).setdefault(day_key, [])
            if uid in confirmed:
                await interaction.response.send_message("✅ Already confirmed! Good luck! 🍾", ephemeral=True)
                return
            confirmed.append(uid)
            _save_data(gid, data)
            await interaction.response.send_message("✅ Confirmed! You joined the Sea Battle! ⚔️🍾", ephemeral=True)
            msg_id    = data.get("reminder_msg_ids", {}).get(day_key)
            thread_id = data.get("thread_ids", {}).get(day_key)
            if msg_id and thread_id:
                try:
                    thread = interaction.guild.get_channel(int(thread_id)) or await interaction.guild.fetch_channel(int(thread_id))
                    if thread:
                        msg_obj   = await thread.fetch_message(int(msg_id))
                        new_embed = _build_reminder_embed(day_num, day_data, confirmed, interaction.guild, interaction.guild.me, data)
                        await msg_obj.edit(embed=new_embed)
                except Exception:
                    pass
    return ConfirmView()


class VacationModal(discord.ui.Modal, title="🛟 Leave"):
    start_day   = discord.ui.TextInput(label="Start day",   placeholder="e.g. 20", min_length=1, max_length=2)
    start_month = discord.ui.TextInput(label="Start month", placeholder="e.g. 05", min_length=1, max_length=2)
    end_day     = discord.ui.TextInput(label="End day",     placeholder="e.g. 25", min_length=1, max_length=2)
    end_month   = discord.ui.TextInput(label="End month",   placeholder="e.g. 05", min_length=1, max_length=2)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            year  = _now_cest().year
            start = datetime(year, int(self.start_month.value), int(self.start_day.value))
            end   = datetime(year, int(self.end_month.value),   int(self.end_day.value))
            if end < start:
                end = datetime(year + 1, int(self.end_month.value), int(self.end_day.value))
            if (end - start).days > 60:
                await interaction.response.send_message("❌ Leave cannot exceed 60 days.", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("❌ Invalid date format.", ephemeral=True)
            return

        gid  = interaction.guild.id
        data = _load_data(gid)
        uid  = str(interaction.user.id)
        data.setdefault("vacations", {})[uid] = {
            "start": start.strftime("%Y-%m-%d"),
            "end":   end.strftime("%Y-%m-%d"),
        }
        week       = data.get("week", {})
        week_dates = data.get("week_dates", {})
        marked_days = []
        for day_key, day_data in week.items():
            date_str = week_dates.get(day_key)
            if not date_str:
                continue
            day_date = datetime.fromisoformat(date_str)
            if start <= day_date <= end:
                _remove_uid(day_data, uid)
                if uid not in day_data["vacation"]:
                    day_data["vacation"].append(uid)
                marked_days.append(DAY_NAMES.get(int(day_key), day_key))
        _save_data(gid, data)
        start_str = f"{int(self.start_day.value):02}.{int(self.start_month.value):02}"
        end_str   = f"{int(self.end_day.value):02}.{int(self.end_month.value):02}"
        if marked_days:
            msg = f"🛟 Leave registered: **{start_str} — {end_str}**\nMarked absent: {', '.join(marked_days)}"
        else:
            msg = f"🛟 Leave registered: **{start_str} — {end_str}**\nNo BBF scheduled in this period."
        await interaction.response.send_message(msg, ephemeral=True)
        for day_key in week.keys():
            date_str = week_dates.get(day_key)
            if not date_str:
                continue
            day_date = datetime.fromisoformat(date_str)
            if start <= day_date <= end:
                await _refresh_embed(interaction.guild, data, int(day_key))


class TeamSelectView(discord.ui.View):
    def __init__(self, day_num: int, guild_id: int):
        super().__init__(timeout=60)
        self.day_num  = day_num
        self.guild_id = guild_id
        options = [discord.SelectOption(label=t, value=t) for t in ALL_TEAMS]
        select  = discord.ui.Select(
            placeholder="Choose your team...",
            options=options,
            custom_id=f"bbf_team_select_{guild_id}_{day_num}",
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        await _process_registration(interaction, self.day_num, interaction.data["values"][0])


def _make_persistent_view(day_num: int, guild_id: int, bbf_role_id: int | None) -> discord.ui.View:
    class PersistentView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        async def _check_role(self, interaction: discord.Interaction) -> bool:
            if not bbf_role_id:
                return True
            role = interaction.guild.get_role(bbf_role_id)
            if role and role not in interaction.user.roles:
                await interaction.response.send_message("❌ You don't have access to BBF registration.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="Join", style=discord.ButtonStyle.success, emoji="🛶", custom_id=f"bbf_can_{guild_id}_{day_num}")
        async def btn_can(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._check_role(interaction):
                return
            data    = _load_data(interaction.guild.id)
            day_key = str(day_num)
            week    = data.get("week", {})
            if any(isinstance(k, int) for k in week.keys()):
                data["week"] = {str(k): v for k, v in week.items()}
                week = data["week"]
            if day_key not in week:
                await interaction.response.send_message(
                    f"❌ Registration for this day is unavailable.\n*(day: {day_key}, available: {list(week.keys())})*",
                    ephemeral=True,
                )
                return
            await interaction.response.send_message(
                "⛵ Choose your team:", view=TeamSelectView(day_num, interaction.guild.id), ephemeral=True
            )

        @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger, emoji="⛵", custom_id=f"bbf_cant_{guild_id}_{day_num}")
        async def btn_cant(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._check_role(interaction):
                return
            await _handle_action(interaction, day_num, "cant")

        @discord.ui.button(label="On Leave", style=discord.ButtonStyle.secondary, emoji="🛟", custom_id=f"bbf_vacation_{guild_id}_{day_num}")
        async def btn_vacation(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._check_role(interaction):
                return
            await interaction.response.send_modal(VacationModal())

        @discord.ui.button(label="Cancel Today", style=discord.ButtonStyle.secondary, emoji="⚓", custom_id=f"bbf_cancel_{guild_id}_{day_num}")
        async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not await self._check_role(interaction):
                return
            await _handle_action(interaction, day_num, "cancel")

    return PersistentView()

# ─── Registration logic ───────────────────────────────────────────────────────

async def _process_registration(interaction: discord.Interaction, day_num: int, chosen_team: str) -> None:
    await interaction.response.defer(ephemeral=True)
    gid     = interaction.guild.id
    data    = _load_data(gid)
    day_key = str(day_num)
    points  = data.get("points", {})

    if day_key not in data.get("week", {}):
        await interaction.followup.send("❌ Registration for this day is unavailable.", ephemeral=True)
        return

    day_data    = data["week"][day_key]
    uid         = str(interaction.user.id)
    prev_status = _get_status(day_data, uid)

    if prev_status in ("main", "waitlist"):
        target = day_data["main"] if prev_status == "main" else day_data["waitlist"]
        for entry in target:
            if entry["uid"] == uid:
                entry["original_team"] = chosen_team
                if not entry.get("auto_galley"):
                    entry["team"] = chosen_team
                break
        _save_data(gid, data)
        location = "main list" if prev_status == "main" else "waitlist"
        await interaction.followup.send(f"✅ Team updated to **{chosen_team}** (in {location}).", ephemeral=True)
        await _refresh_embed(interaction.guild, data, day_num)
        return

    _remove_uid(day_data, uid)
    total_main = len(day_data["main"])

    if total_main >= MAX_SPOTS:
        entry = {"uid": uid, "team": chosen_team, "original_team": chosen_team, "auto_galley": False}
        day_data["waitlist"].append(entry)
        points[uid] = points.get(uid, 0) + 1
        data["points"] = points
        _save_data(gid, data)
        await interaction.followup.send(
            f"⏳ All {MAX_SPOTS} spots taken. You are #{len(day_data['waitlist'])} in the waitlist for **{DAY_NAMES[day_num]}**"
            f" — team **{chosen_team}**.\n🏅 Priority points: **{points[uid]}**",
            ephemeral=True,
        )
        await _refresh_embed(interaction.guild, data, day_num)
        return

    galley_now     = _galley_count(day_data)
    is_real_galley = chosen_team in GALLEY_TEAMS

    if galley_now < GALLEY_MIN:
        entry = {"uid": uid, "team": GALLEY_TEAMS[0], "original_team": chosen_team, "auto_galley": not is_real_galley}
        day_data["main"].append(entry)
        points[uid] = 0
        data["points"] = points
        _save_data(gid, data)
        if is_real_galley:
            reply = f"⚓ You joined **Galley Crew** on **{DAY_NAMES[day_num]}**! Galley: {galley_now+1}/{GALLEY_MIN}. Points reset."
        else:
            reply = (f"⚓ Galley not full ({galley_now+1}/{GALLEY_MIN})! Added to **Galley** temporarily.\n"
                     f"You'll be moved to **{chosen_team}** when galley is complete. Points reset.")
    else:
        evict_index = next(
            (i for i, e in enumerate(day_data["main"]) if e.get("auto_galley") and e["team"] in GALLEY_TEAMS),
            None
        )
        if evict_index is not None:
            evicted          = day_data["main"][evict_index]
            evicted_original = evicted["original_team"]
            evicted["team"]        = evicted_original
            evicted["auto_galley"] = False
            new_entry = {"uid": uid, "team": GALLEY_TEAMS[0], "original_team": chosen_team, "auto_galley": not is_real_galley}
            day_data["main"].append(new_entry)
            points[uid] = 0
            data["points"] = points
            _save_data(gid, data)
            await _try_send_dm(interaction.guild, evicted["uid"],
                f"⛵ New member joined the Galley — you've been moved to **{evicted_original}** on BBF ({DAY_NAMES[day_num]}). Good luck!")
            evicted_member = interaction.guild.get_member(int(evicted["uid"]))
            evicted_name   = evicted_member.display_name if evicted_member else f"<@{evicted['uid']}>"
            reply = (f"⚓ Added to **Galley** on **{DAY_NAMES[day_num]}** (temporary, then to **{chosen_team}**).\n"
                     f"**{evicted_name}** moved to **{evicted_original}**. Points reset.")
        else:
            new_entry = {"uid": uid, "team": chosen_team, "original_team": chosen_team, "auto_galley": False}
            day_data["main"].append(new_entry)
            points[uid] = 0
            data["points"] = points
            _save_data(gid, data)
            reply = f"⛵ Galley full! Added directly to **{chosen_team}** (All Ships) on **{DAY_NAMES[day_num]}**. Points reset."

    await interaction.followup.send(reply, ephemeral=True)
    await _refresh_embed(interaction.guild, data, day_num)


async def _handle_action(interaction: discord.Interaction, day_num: int, action: str) -> None:
    await interaction.response.defer(ephemeral=True)
    gid     = interaction.guild.id
    data    = _load_data(gid)
    day_key = str(day_num)

    if day_key not in data.get("week", {}):
        await interaction.followup.send("❌ Registration for this day is unavailable.", ephemeral=True)
        return

    day_data    = data["week"][day_key]
    uid         = str(interaction.user.id)
    prev_status = _get_status(day_data, uid)

    async def _notify(promoted_uid, back_uid) -> str:
        msg = ""
        if promoted_uid:
            m = interaction.guild.get_member(int(promoted_uid))
            pname = m.mention if m else f"<@{promoted_uid}>"
            msg += f"\n🛶 {pname} moved from waitlist!"
            await _try_send_dm(interaction.guild, promoted_uid,
                f"🛶 A spot opened! You've been moved to the main BBF list for **{DAY_NAMES[day_num]}**. Good luck!")
        if back_uid:
            m = interaction.guild.get_member(int(back_uid))
            pname = m.mention if m else f"<@{back_uid}>"
            msg += f"\n⚓ {pname} returned to Galley!"
            await _try_send_dm(interaction.guild, back_uid,
                f"⚓ A Galley spot opened — you've been returned to **Galley Crew** on BBF ({DAY_NAMES[day_num]}). Good luck!")
        return msg

    if action == "cancel":
        if prev_status is None:
            await interaction.followup.send("ℹ️ You are not registered for this day.", ephemeral=True)
            return
        _remove_uid(day_data, uid)
        promoted = _promote_from_waitlist(day_data) if prev_status == "main" else None
        back     = _refill_galley(day_data)          if prev_status == "main" else None
        _save_data(gid, data)
        msg = f"⚓ Your registration for **{DAY_NAMES[day_num]}** has been cancelled. Points kept."
        msg += await _notify(promoted, back)
        await interaction.followup.send(msg, ephemeral=True)

    elif action == "cant":
        _remove_uid(day_data, uid)
        day_data["cant"].append(uid)
        promoted = _promote_from_waitlist(day_data) if prev_status == "main" else None
        back     = _refill_galley(day_data)          if prev_status == "main" else None
        _save_data(gid, data)
        msg = f"⛵ Marked as «Won't join» for **{DAY_NAMES[day_num]}**."
        msg += await _notify(promoted, back)
        await interaction.followup.send(msg, ephemeral=True)

    elif action == "vacation":
        _remove_uid(day_data, uid)
        day_data["vacation"].append(uid)
        promoted = _promote_from_waitlist(day_data) if prev_status == "main" else None
        back     = _refill_galley(day_data)          if prev_status == "main" else None
        _save_data(gid, data)
        msg = f"🛟 Marked as «On Leave» for **{DAY_NAMES[day_num]}**."
        msg += await _notify(promoted, back)
        await interaction.followup.send(msg, ephemeral=True)

    await _refresh_embed(interaction.guild, data, day_num)


async def _refresh_embed(guild: discord.Guild, data: dict, day_num: int) -> None:
    day_key   = str(day_num)
    thread_id = data.get("thread_ids", {}).get(day_key)
    msg_id    = data.get("message_ids", {}).get(day_key)
    if not msg_id:
        return
    try:
        channel = guild.get_channel(int(thread_id)) if thread_id else None
        if not channel:
            try:
                channel = await guild.fetch_channel(int(thread_id))
            except Exception:
                return
        if not channel:
            return
        try:
            msg_obj = await channel.fetch_message(int(msg_id))
        except discord.NotFound:
            return
        except Exception:
            return

        config     = _load_config(guild.id)
        role_id    = config.get("bbf_role_id")
        image_path = data.get("day_images", {}).get(day_key)
        embed      = _build_embed(day_num, data["week"][day_key], data.get("points", {}), guild, guild.me, image_path, data)
        view       = _make_persistent_view(day_num, guild.id, role_id)

        if image_path and Path(image_path).exists():
            try:
                file = discord.File(image_path, filename=Path(image_path).name)
                await msg_obj.edit(embed=embed, view=view, attachments=[file])
                return
            except Exception:
                pass
        await msg_obj.edit(embed=embed, view=view)
    except Exception as e:
        print(f"[BBF] Refresh error day {day_num}: {e}")

# ─── Cog ─────────────────────────────────────────────────────────────────────

class BBFGlobalCog(commands.Cog, name="BBFGlobal"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_task.start()
        self.backup_task.start()

    def cog_unload(self):
        self.reminder_task.cancel()
        self.backup_task.cancel()

    def _is_home_guild(self, guild_id: int) -> bool:
        """Перевіряє чи це основний сервер — він обслуговується bbf_cog.py."""
        home = getattr(self.bot, "home_guild_id", None)
        return home is not None and guild_id == home

    # ── Setup ────────────────────────────────────────────────────────────────

    @app_commands.command(name="bbf_setup", description="[Admin] Set up BBF for this server")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        category="Category where BBF channels will be created",
        voice="Voice channel for BBF gatherings",
        role="Role required to register (optional)",
    )
    async def bbf_setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        voice: discord.VoiceChannel,
        role: discord.Role | None = None,
    ):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module. Use `/bbf_старт` instead.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        config = {
            "category_id": category.id,
            "voice_id":    voice.id,
            "bbf_role_id": role.id if role else None,
        }
        _save_config(interaction.guild.id, config)

        for day_num in DAY_NAMES.keys():
            self.bot.add_view(_make_persistent_view(day_num, interaction.guild.id, role.id if role else None))
            self.bot.add_view(_make_confirm_view(day_num, interaction.guild.id))

        role_str = role.mention if role else "none (open for all)"
        await interaction.followup.send(
            f"✅ **BBF configured!**\n"
            f"📁 Category: {category.mention}\n"
            f"🎙️ Voice: {voice.mention}\n"
            f"👥 Role: {role_str}\n\n"
            f"Use `/bbf_start` to open weekly registration!",
            ephemeral=True,
        )

    # ── Start ────────────────────────────────────────────────────────────────

    @app_commands.command(name="bbf_start", description="[Admin] Start weekly BBF registration")
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_start(self, interaction: discord.Interaction):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module. Use `/bbf_старт` instead.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        gid    = interaction.guild.id
        config = _load_config(gid)

        if not config.get("category_id"):
            await interaction.followup.send("❌ BBF not configured. Run `/bbf_setup` first.", ephemeral=True)
            return

        category = interaction.guild.get_channel(config["category_id"])
        if not category:
            await interaction.followup.send("❌ Category not found. Run `/bbf_setup` again.", ephemeral=True)
            return

        for ch in list(category.channels):
            if ch.name.startswith("📅-"):
                try:
                    await ch.delete()
                    await asyncio.sleep(0.3)
                except Exception:
                    pass

        old_data   = _load_data(gid)
        old_points = old_data.get("points", {})

        data = _empty_data()
        data["points"]     = old_points
        data["channel_id"] = interaction.channel.id

        week_dates = _get_week_dates()
        for day_num, day_date in week_dates.items():
            data["week_dates"][str(day_num)] = day_date.strftime("%Y-%m-%d")

        role_id      = config.get("bbf_role_id")
        role         = interaction.guild.get_role(role_id) if role_id else None
        role_mention = role.mention if role else "@everyone"

        await interaction.channel.send(f"{role_mention} ⚓ **BBF registration is open this week!** 🍾")

        today_date = _now_cest().replace(hour=0, minute=0, second=0, microsecond=0)

        for day_num, day_name in DAY_NAMES.items():
            day_key  = str(day_num)
            day_date = week_dates[day_num].replace(hour=0, minute=0, second=0, microsecond=0)
            if day_date < today_date:
                continue

            date_str = f"{day_date.day:02}.{day_date.month:02}"
            data["week"][day_key] = _empty_day()
            image_path = _pick_image(data, day_key)

            embed = _build_embed(day_num, data["week"][day_key], data["points"], interaction.guild, self.bot.user, image_path, data)
            view  = _make_persistent_view(day_num, gid, role_id)

            try:
                channel = await interaction.guild.create_text_channel(
                    name=f"📅-{day_name.lower()}-{date_str}",
                    category=category,
                    topic=f"BBF registration — {day_name} {date_str}",
                )
                data["thread_ids"][day_key] = channel.id

                img_exists = image_path and Path(image_path).exists()
                if img_exists:
                    try:
                        file = discord.File(image_path, filename=Path(image_path).name)
                        msg  = await channel.send(file=file, embed=embed, view=view)
                    except Exception:
                        msg = await channel.send(embed=embed, view=view)
                else:
                    msg = await channel.send(embed=embed, view=view)

                data["message_ids"][day_key] = msg.id
                await channel.send(f"{role_mention} 📋 Registration for **{day_name} {date_str}** is open! 🛶")
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[BBF] Error creating channel for {day_name}: {e}")

        _save_data(gid, data)
        await interaction.followup.send("✅ BBF registration opened!", ephemeral=True)

    # ── Reminder task ────────────────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def reminder_task(self):
        now_cest = _now_cest()
        weekday  = now_cest.weekday()
        if weekday not in DAY_NAMES:
            return

        try:
            configs = list(_get_db()["bbf_config"].find({}))
        except Exception:
            return

        for cfg in configs:
            try:
                gid = int(cfg["_id"])
                # ── Пропускаємо основний сервер — він має свій bbf_cog.py ──
                if self._is_home_guild(gid):
                    continue
                await self._run_reminders(gid, cfg, now_cest, weekday)
            except Exception as e:
                print(f"[BBF] Reminder error guild {cfg.get('_id')}: {e}")

    async def _run_reminders(self, gid: int, config: dict, now_cest: datetime, weekday: int):
        data    = _load_data(gid)
        day_key = str(weekday)
        if day_key not in data.get("week", {}):
            return

        guild = self.bot.get_guild(gid)
        if not guild:
            return

        thread_id = data.get("thread_ids", {}).get(day_key)
        if not thread_id:
            return

        thread = guild.get_channel(int(thread_id))
        if not thread:
            try:
                thread = await guild.fetch_channel(int(thread_id))
            except Exception:
                return

        day_data  = data["week"][day_key]
        main_uids = [e["uid"] for e in day_data["main"]]
        today     = now_cest.replace(hour=0, minute=0, second=0, microsecond=0)

        def _is_on_vacation(uid):
            vac = data.get("vacations", {}).get(uid)
            if not vac:
                return False
            try:
                s = datetime.fromisoformat(vac["start"])
                e = datetime.fromisoformat(vac["end"])
                return s <= today <= e
            except Exception:
                return False

        active_uids = [uid for uid in main_uids if not _is_on_vacation(uid)]

        # 19:30 CEST — readiness check
        if now_cest.hour == REMINDER_HOUR_CEST and now_cest.minute == REMINDER_MINUTE_CEST and not data.get("reminded", {}).get(day_key):
            if active_uids:
                mentions  = " ".join(f"<@{uid}>" for uid in active_uids)
                confirmed = data.get("confirmed", {}).get(day_key, [])
                embed     = _build_reminder_embed(weekday, day_data, confirmed, guild, guild.me, data)
                view      = _make_confirm_view(weekday, gid)
                msg       = await thread.send(content=mentions, embed=embed, view=view)
                data.setdefault("reminder_msg_ids", {})[day_key] = msg.id
            data.setdefault("reminded", {})[day_key] = True
            _save_data(gid, data)

        # 19:45 CEST — gather up
        if now_cest.hour == INVITE_HOUR_CEST and now_cest.minute == INVITE_MINUTE_CEST and not data.get("invited", {}).get(day_key):
            if active_uids:
                ts = _get_ts_for_day(data, weekday)
                voice_id      = config.get("voice_id")
                voice_channel = guild.get_channel(voice_id) if voice_id else None
                if not voice_channel and voice_id:
                    try:
                        voice_channel = await guild.fetch_channel(voice_id)
                    except Exception:
                        pass
                vc_mention = voice_channel.mention if voice_channel else "voice channel"

                day_data_now = data["week"][day_key]
                galley_uids  = [e["uid"] for e in day_data_now["main"] if e["team"] in GALLEY_TEAMS and e["uid"] in active_uids]
                ship_entries = [e for e in day_data_now["main"] if e["team"] not in GALLEY_TEAMS and e["uid"] in active_uids]

                galley_mentions = " ".join(f"<@{uid}>" for uid in galley_uids)
                ship_mentions   = " ".join(f"<@{e['uid']}>" for e in ship_entries)
                galley_lines    = "\n".join(f"`{i:02}.` <@{uid}>" for i, uid in enumerate(galley_uids, 1)) or "*Empty*"
                ship_lines      = "\n".join(f"`{i:02}.` <@{e['uid']}> — *{e['team']}*" for i, e in enumerate(ship_entries, 1)) or "*Empty*"

                msg = (
                    f"🚢 **Gather up!**\n"
                    f"BBF at <t:{ts}:t>! Join: {vc_mention} 🍾⚓\n\n"
                    f"⚓ **Galley Crew** ({len(galley_uids)}/{GALLEY_MIN}):\n{galley_mentions}\n{galley_lines}\n\n"
                    f"⛵ **Fleet** ({len(ship_entries)}):\n{ship_mentions}\n{ship_lines}"
                )
                await thread.send(msg)
            data.setdefault("invited", {})[day_key] = True
            _save_data(gid, data)

    @reminder_task.before_loop
    async def before_reminder(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=15)
    async def backup_task(self):
        try:
            configs = list(_get_db()["bbf_config"].find({}, {"_id": 1}))
        except Exception:
            return
        for cfg in configs:
            gid = int(cfg["_id"])
            # Пропускаємо основний сервер
            if self._is_home_guild(gid):
                continue
            data = _load_data(gid)
            if data.get("week"):
                _save_backup(gid, data)

    @backup_task.before_loop
    async def before_backup(self):
        await self.bot.wait_until_ready()

    # ── Commands ─────────────────────────────────────────────────────────────

    @app_commands.command(name="bbf_status", description="View your BBF status for this week")
    async def bbf_status(self, interaction: discord.Interaction):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module. Use `/bbf_статус` instead.", ephemeral=True
            )
            return

        gid  = interaction.guild.id
        data = _load_data(gid)
        uid  = str(interaction.user.id)
        week = data.get("week", {})
        if not week:
            await interaction.response.send_message("ℹ️ Registration not open yet.", ephemeral=True)
            return
        labels = {
            "main": "✅ Main list", "waitlist": "⏳ Waitlist",
            "vacation": "🛟 On Leave", "cant": "⛵ Won't join", None: "➖ Not registered",
        }
        lines = []
        for day_num, day_name in DAY_NAMES.items():
            day_key = str(day_num)
            if day_key not in week:
                continue
            date_str = data.get("week_dates", {}).get(day_key, "")
            date_label = ""
            if date_str:
                d = datetime.fromisoformat(date_str)
                date_label = f" {d.day:02}.{d.month:02}"
            status   = _get_status(week[day_key], uid)
            label    = labels[status]
            entry    = _get_entry(week[day_key], uid)
            team_str = f" — *{entry['team']}*" if entry else ""
            if status == "waitlist":
                pos = next((i+1 for i, e in enumerate(week[day_key]["waitlist"]) if e["uid"] == uid), "?")
                label += f" (#{pos})"
            lines.append(f"**{day_name}{date_label}**: {label}{team_str}")
        pts = data.get("points", {}).get(uid, 0)
        embed = discord.Embed(title="📋 Your BBF status this week", description="\n".join(lines), color=discord.Color.blue())
        embed.set_footer(
            text=f"Silent Concierge by Myxa  |  🍾 Rom, Rom, ROM!  |  🏅 Your points: {pts}",
            icon_url=self.bot.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="bbf_points", description="View priority points leaderboard")
    async def bbf_points(self, interaction: discord.Interaction):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module. Use `/bbf_очки` instead.", ephemeral=True
            )
            return

        data   = _load_data(interaction.guild.id)
        points = {k: v for k, v in data.get("points", {}).items() if v > 0}
        if not points:
            await interaction.response.send_message("ℹ️ No one has priority points yet.", ephemeral=True)
            return
        lines = []
        for uid, pts in sorted(points.items(), key=lambda x: x[1], reverse=True):
            member = interaction.guild.get_member(int(uid))
            name = member.mention if member else f"<@{uid}>"
            lines.append(f"**{name}** — {pts} 🏅")
        embed = discord.Embed(title="🏅 BBF Priority Points", description="\n".join(lines), color=discord.Color.gold())
        embed.set_footer(
            text="Silent Concierge by Myxa  |  🍾 Rom, Rom, ROM!",
            icon_url=self.bot.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="bbf_reset_points", description="[Admin] Reset priority points")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(member="Member (leave empty to reset all)")
    async def bbf_reset_points(self, interaction: discord.Interaction, member: discord.Member | None = None):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module. Use `/bbf_скинути_очки` instead.", ephemeral=True
            )
            return

        gid  = interaction.guild.id
        data = _load_data(gid)
        if member:
            data["points"][str(member.id)] = 0
            _save_data(gid, data)
            await interaction.response.send_message(f"✅ Points reset for {member.mention}.", ephemeral=True)
        else:
            data["points"] = {}
            _save_data(gid, data)
            await interaction.response.send_message("✅ All points reset.", ephemeral=True)

    @app_commands.command(name="bbf_refresh", description="[Admin] Manually refresh all BBF embeds")
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_refresh(self, interaction: discord.Interaction):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module. Use `/bbf_оновити` instead.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        gid  = interaction.guild.id
        data = _load_data(gid)
        if not data.get("week"):
            await interaction.followup.send("❌ Registration not started yet.", ephemeral=True)
            return
        for day_num in DAY_NAMES.keys():
            await _refresh_embed(interaction.guild, data, day_num)
        await interaction.followup.send("✅ All embeds refreshed.", ephemeral=True)

    @app_commands.command(name="bbf_resend", description="[Admin] Send new embed if old one was deleted")
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_resend(self, interaction: discord.Interaction):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module. Use `/bbf_переслати` instead.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        gid    = interaction.guild.id
        data   = _load_data(gid)
        config = _load_config(gid)
        if not data.get("week"):
            await interaction.followup.send("❌ Registration not started.", ephemeral=True)
            return
        role_id      = config.get("bbf_role_id")
        role         = interaction.guild.get_role(role_id) if role_id else None
        role_mention = role.mention if role else "@everyone"
        sent = 0
        for day_num in DAY_NAMES.keys():
            day_key   = str(day_num)
            if day_key not in data.get("week", {}):
                continue
            thread_id = data.get("thread_ids", {}).get(day_key)
            if not thread_id:
                continue
            try:
                channel = interaction.guild.get_channel(int(thread_id))
                if not channel:
                    channel = await interaction.guild.fetch_channel(int(thread_id))
                if not channel:
                    continue
                msg_id = data.get("message_ids", {}).get(day_key)
                msg_exists = False
                if msg_id:
                    try:
                        await channel.fetch_message(int(msg_id))
                        msg_exists = True
                    except Exception:
                        pass
                if msg_exists:
                    continue
                image_path = data.get("day_images", {}).get(day_key)
                embed = _build_embed(day_num, data["week"][day_key], data.get("points", {}), interaction.guild, self.bot.user, image_path, data)
                view  = _make_persistent_view(day_num, gid, role_id)
                if image_path and Path(image_path).exists():
                    try:
                        file = discord.File(image_path, filename=Path(image_path).name)
                        msg  = await channel.send(file=file, embed=embed, view=view)
                    except Exception:
                        msg = await channel.send(embed=embed, view=view)
                else:
                    msg = await channel.send(embed=embed, view=view)
                data.setdefault("message_ids", {})[day_key] = msg.id
                sent += 1
            except Exception as e:
                print(f"[BBF] Resend error day {day_num}: {e}")
        _save_data(gid, data)
        await interaction.followup.send(
            f"✅ Sent {sent} new embed(s)." if sent else "ℹ️ All embeds already exist.",
            ephemeral=True,
        )

    @app_commands.command(name="bbf_backups", description="[Admin] Show recent backups")
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_backups(self, interaction: discord.Interaction):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module. Use `/bbf_бекапи` instead.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        backups = _list_backups(interaction.guild.id)
        if not backups:
            await interaction.followup.send("ℹ️ No backups found.", ephemeral=True)
            return
        lines = []
        for b in backups:
            ts = b.get("timestamp", b["_id"])
            try:
                unix = int(datetime.fromisoformat(ts).timestamp())
                lines.append(f"`{b['_id']}` — <t:{unix}:f>")
            except Exception:
                lines.append(f"`{b['_id']}`")
        embed = discord.Embed(title="💾 BBF Backups", description="\n".join(lines), color=discord.Color.blue())
        embed.set_footer(text="Use /bbf_restore <id> to restore")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="bbf_restore", description="[Admin] Restore from backup")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(backup_id="Backup ID (e.g. 2026-05-20_14-30)")
    async def bbf_restore(self, interaction: discord.Interaction, backup_id: str):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module. Use `/bbf_відновити` instead.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        gid  = interaction.guild.id
        data = _restore_backup(gid, backup_id)
        if not data:
            await interaction.followup.send(f"❌ Backup `{backup_id}` not found.", ephemeral=True)
            return
        _save_data(gid, data)
        await interaction.followup.send(
            f"✅ Data restored from `{backup_id}`!\nUse `/bbf_refresh` to update embeds.",
            ephemeral=True,
        )

    @app_commands.command(name="bbf_migrate", description="[Admin] Fix auto_galley for existing data")
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_migrate(self, interaction: discord.Interaction):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module. Use `/bbf_мігрувати` instead.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        gid  = interaction.guild.id
        data = _load_data(gid)
        for field in ("week", "week_dates", "message_ids", "thread_ids",
                      "reminder_msg_ids", "confirmed", "reminded", "invited", "day_images"):
            raw = data.get(field, {})
            if raw and any(isinstance(k, int) for k in raw.keys()):
                data[field] = {str(k): v for k, v in raw.items()}
        week = data.get("week", {})
        if not week:
            await interaction.followup.send("❌ No data found.", ephemeral=True)
            return
        report = []
        for day_key, day_data in week.items():
            main     = day_data.get("main", [])
            day_num  = int(day_key)
            day_name = DAY_NAMES.get(day_num, day_key)
            for entry in main:
                if "original_team" not in entry:
                    entry["original_team"] = entry["team"]
            for entry in main:
                if entry["team"] in GALLEY_TEAMS:
                    entry["auto_galley"] = entry["original_team"] not in GALLEY_TEAMS
                else:
                    entry["auto_galley"] = False
            moved = []
            for entry in main:
                galley_now = sum(1 for e in main if e["team"] in GALLEY_TEAMS)
                if galley_now >= GALLEY_MIN:
                    break
                if entry["team"] not in GALLEY_TEAMS:
                    entry["original_team"] = entry["team"]
                    entry["team"]          = GALLEY_TEAMS[0]
                    entry["auto_galley"]   = True
                    moved.append(entry["uid"])
            galley_count = sum(1 for e in main if e["team"] in GALLEY_TEAMS)
            report.append(f"**{day_name}**: {'moved ' + str(len(moved)) + ' to galley' if moved else f'ok (galley {galley_count}/{GALLEY_MIN})'}")
        _save_data(gid, data)
        for day_num in DAY_NAMES.keys():
            await _refresh_embed(interaction.guild, data, day_num)
        await interaction.followup.send(f"✅ Migration done!\n\n" + "\n".join(report), ephemeral=True)

    @app_commands.command(name="bbf_help", description="BBF system guide")
    async def bbf_help(self, interaction: discord.Interaction):
        if self._is_home_guild(interaction.guild.id):
            await interaction.response.send_message(
                "❌ This server uses the Ukrainian BBF module.", ephemeral=True
            )
            return

        config = _load_config(interaction.guild.id)
        is_configured = bool(config.get("category_id"))
        status_str = "✅ BBF is configured!" if is_configured else "❌ Not configured. Run `/bbf_setup` first!"

        embed = discord.Embed(
            title="⚓ BBF Registration System — Help",
            description="Sea Battle Fleet registration for Black Desert Online guilds.",
            color=discord.Color.from_rgb(45, 60, 110),
        )
        embed.add_field(name="🔧 Setup (Admin)", value=(
            "`/bbf_setup category: voice: role:`\n"
            "Configure BBF for your server. Run once.\n\n"
            + status_str
        ), inline=False)
        embed.add_field(name="📋 Weekly flow", value=(
            "1. Admin runs `/bbf_start` at start of week\n"
            "2. Bot creates daily channels (Mon-Fri + Sun)\n"
            "3. Members click **Join** and choose their team\n"
            "4. At **19:30 CEST** — readiness check sent\n"
            "5. At **19:45 CEST** — gather-up with Galley & Fleet"
        ), inline=False)
        embed.add_field(name="🛶 Buttons", value=(
            "**Join** — register and choose team\n"
            "**Leave** — mark as not joining\n"
            "**On Leave** — vacation period\n"
            "**Cancel Today** — remove registration"
        ), inline=False)
        embed.add_field(name="⚓ Galley system", value=(
            f"Galley needs **{GALLEY_MIN} crew**. Everyone goes to Galley first.\n"
            "When Galley is full — earliest ship member moves to their ship.\n"
            "*(auto)* = temporarily in Galley"
        ), inline=False)
        embed.add_field(name="⏳ Waitlist & Points", value=(
            f"Max **{MAX_SPOTS} spots**. When full you join waitlist + get 🏅 point.\n"
            "Points reset to 0 when you register successfully.\n"
            "View: `/bbf_points`"
        ), inline=False)
        embed.add_field(name="📊 Member commands", value=(
            "`/bbf_status` — your week status\n"
            "`/bbf_points` — points leaderboard\n"
            "`/bbf_help` — this message"
        ), inline=False)
        embed.add_field(name="🛠️ Admin commands", value=(
            "`/bbf_setup` `/bbf_start` `/bbf_refresh`\n"
            "`/bbf_resend` `/bbf_reset_points`\n"
            "`/bbf_backups` `/bbf_restore` `/bbf_migrate`"
        ), inline=False)
        embed.add_field(name="⏰ Auto messages (CEST)", value=(
            "19:30 — readiness check\n"
            "19:45 — gather-up with Galley & Fleet\n"
            "20:00 — BBF start"
        ), inline=False)
        embed.set_footer(
            text="Silent Concierge by Myxa  |  🍾 Rom, Rom, ROM!",
            icon_url=self.bot.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BBFGlobalCog(bot))
    print("[COG] BBFGlobalCog loaded")
    try:
        home_gid = getattr(bot, "home_guild_id", None)
        configs  = list(_get_db()["bbf_config"].find({}))
        registered = 0
        for cfg in configs:
            gid = int(cfg["_id"])
            # ── Пропускаємо основний сервер ──────────────────────────────────
            if home_gid and gid == home_gid:
                print(f"[BBF] Skipping home guild {gid} (handled by bbf_cog.py)")
                continue
            role_id = cfg.get("bbf_role_id")
            for day_num in DAY_NAMES.keys():
                bot.add_view(_make_persistent_view(day_num, gid, role_id))
                bot.add_view(_make_confirm_view(day_num, gid))
            registered += 1
        print(f"[BBF] Registered views for {registered} guild(s) (skipped home guild)")
    except Exception as e:
        print(f"[BBF] Startup view registration error: {e}")
