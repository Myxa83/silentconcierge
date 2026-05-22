# -*- coding: utf-8 -*-
# bbf_cog.py

import asyncio
import json
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from pymongo import MongoClient

# ─── Налаштування ────────────────────────────────────────────────────────────

_mongo_client = None
_mongo_db     = None

def _get_db():
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        url = os.environ.get("MONGODB_URL", "")
        if not url:
            print("[BBF][ERROR] MONGODB_URL не задано!")
        else:
            print(f"[BBF] Підключаємось до MongoDB...")
        _mongo_client = MongoClient(url, serverSelectionTimeoutMS=10000)
        _mongo_db = _mongo_client["silentconcierge"]
        print(f"[BBF] MongoDB підключено: {_mongo_db.name}")
    return _mongo_db

MAX_SPOTS                = 20
GALLEY_MIN               = 8
THREAD_PARENT_CHANNEL_ID = 1486067779177152523
BBF_CATEGORY_ID          = 1486067160555065425
VOICE_CHANNEL_ID         = 1486420425188839495
BBF_ROLE_ID              = 1470790564718055434

REMINDER_HOUR_UTC    = 17
REMINDER_MINUTE_UTC  = 30
INVITE_HOUR_UTC      = 17
INVITE_MINUTE_UTC    = 45
BBF_START_HOUR_UTC   = 18
BBF_START_MINUTE_UTC = 0

DAY_NAMES = {
    0: "Понеділок",
    1: "Вівторок",
    2: "Середа",
    3: "Четвер",
    4: "П'ятниця",
    6: "Неділя",
}

GALLEY_TEAMS = ["Екіпаж Галери"]
SHIP_TEAMS   = ["Політ", "Баланс", "Прогрес", "Хоробрість", "Панаксіон", "Зірка Еферії"]
ALL_TEAMS    = GALLEY_TEAMS + SHIP_TEAMS

BBF_IMAGES = [
    "assets/backgrounds/image-65.webp",
    "assets/backgrounds/2026-03-06_99110141.PNG",
    "assets/backgrounds/PN260416.png",
    "assets/backgrounds/a56dd81618920250304171316184.png",
    "assets/backgrounds/ed682f59d7420260410101500360 (1).jpg",
    "assets/backgrounds/3e703842-4873-41c2-9060-20fd9fdc0109.png",
]

# ─── Дати тижня ──────────────────────────────────────────────────────────────

def _get_week_dates() -> dict[int, datetime]:
    now    = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    dates  = {}
    for day_num in DAY_NAMES.keys():
        dates[day_num] = monday + timedelta(days=day_num)
    return dates


def _bbf_timestamp(day_date: datetime) -> int:
    target = day_date.replace(
        hour=BBF_START_HOUR_UTC,
        minute=BBF_START_MINUTE_UTC,
        second=0, microsecond=0,
    )
    return int(target.timestamp())

# ─── Збереження / завантаження ───────────────────────────────────────────────

def _load_data() -> dict:
    try:
        db  = _get_db()
        doc = db["bbf"].find_one({"_id": "main"})
        if doc:
            doc.pop("_id", None)
            print(f"[BBF] Дані завантажено з MongoDB. Днів: {len(doc.get('week', {}))}")
            return doc
        else:
            print("[BBF] MongoDB: даних немає, повертаємо порожні")
    except Exception as e:
        print(f"[BBF][ERROR] MongoDB load error: {type(e).__name__}: {e}")
    return _empty_data()


def _empty_data() -> dict:
    return {
        "week": {},
        "week_dates": {},
        "points": {},
        "channel_id": None,
        "message_ids": {},
        "thread_ids": {},
        "reminder_msg_ids": {},
        "confirmed": {},
        "guild_id": None,
        "used_images": [],
        "day_images": {},
        "reminded": {},
        "invited": {},
    }


def _save_data(data: dict) -> None:
    try:
        db = _get_db()
        db["bbf"].replace_one({"_id": "main"}, {"_id": "main", **data}, upsert=True)
        print(f"[BBF] Дані збережено в MongoDB")
    except Exception as e:
        print(f"[BBF][ERROR] MongoDB save error: {type(e).__name__}: {e}")


def _empty_day() -> dict:
    return {
        "main":     [],
        "waitlist": [],
        "vacation": [],
        "cant":     [],
    }


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

# ─── Допоміжні функції ───────────────────────────────────────────────────────

def _get_entry(day_data: dict, uid: str) -> dict | None:
    for e in day_data["main"] + day_data["waitlist"]:
        if e["uid"] == uid:
            return e
    return None


def _get_status(day_data: dict, uid: str) -> str | None:
    for e in day_data["main"]:
        if e["uid"] == uid:
            return "main"
    for e in day_data["waitlist"]:
        if e["uid"] == uid:
            return "waitlist"
    if uid in day_data["vacation"]:
        return "vacation"
    if uid in day_data["cant"]:
        return "cant"
    return None


def _remove_uid(day_data: dict, uid: str) -> str | None:
    prev = _get_status(day_data, uid)
    day_data["main"]     = [e for e in day_data["main"]     if e["uid"] != uid]
    day_data["waitlist"] = [e for e in day_data["waitlist"] if e["uid"] != uid]
    if uid in day_data["vacation"]:
        day_data["vacation"].remove(uid)
    if uid in day_data["cant"]:
        day_data["cant"].remove(uid)
    return prev


def _galley_count(day_data: dict) -> int:
    return sum(1 for e in day_data["main"] if e["team"] in GALLEY_TEAMS)


def _promote_from_waitlist(day_data: dict) -> str | None:
    if len(day_data["main"]) < MAX_SPOTS and day_data["waitlist"]:
        entry = day_data["waitlist"].pop(0)

        # Перевіряємо галеру — якщо не повна, людина іде на галеру
        galley_now     = _galley_count(day_data)
        is_real_galley = entry["team"] in GALLEY_TEAMS

        if galley_now < GALLEY_MIN and not is_real_galley:
            # Галера не повна — тимчасово на галеру
            entry["original_team"] = entry["team"]
            entry["team"]          = GALLEY_TEAMS[0]
            entry["auto_galley"]   = True
        else:
            entry["auto_galley"] = False

        day_data["main"].append(entry)
        return entry["uid"]
    return None


def _refill_galley(day_data: dict) -> str | None:
    """Якщо галера не повна — переміщує останнього корабельного назад на галеру."""
    galley_now = _galley_count(day_data)
    if galley_now >= GALLEY_MIN:
        return None
    # Шукаємо останнього (найновішого) хто на кораблі з auto_galley=False
    # тобто того хто був виштовхнутий з галери раніше
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

# ─── Побудова ембедів ────────────────────────────────────────────────────────

def _get_ts_for_day(data: dict, day_num: int) -> int:
    day_key   = str(day_num)
    date_str  = data.get("week_dates", {}).get(day_key)
    if date_str:
        day_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    else:
        week_dates = _get_week_dates()
        day_date   = week_dates.get(day_num, datetime.now(timezone.utc))
    return _bbf_timestamp(day_date)


def _build_embed(
    day_num: int,
    day_data: dict,
    points: dict,
    guild: discord.Guild,
    bot_user: discord.ClientUser,
    image_path: str | None,
    data: dict,
) -> discord.Embed:
    day_name = DAY_NAMES[day_num]
    day_key  = str(day_num)
    ts       = _get_ts_for_day(data, day_num)

    date_str = data.get("week_dates", {}).get(day_key, "")
    date_label = ""
    if date_str:
        d = datetime.fromisoformat(date_str)
        date_label = f" {d.day:02}.{d.month:02}"

    embed = discord.Embed(
        title=f"⚓ BBF — {day_name}{date_label}",
        description=f"🕹️ Початок: <t:{ts}:f>",
        color=discord.Color.from_rgb(45, 60, 110),
    )

    galley_main = [e for e in day_data["main"] if e["team"] in GALLEY_TEAMS]
    ship_main   = [e for e in day_data["main"] if e["team"] not in GALLEY_TEAMS]
    total_main  = len(day_data["main"])

    # Галера
    galley_lines = []
    for i, entry in enumerate(galley_main, 1):
        member = guild.get_member(int(entry["uid"]))
        name   = member.mention if member else f"<@{entry['uid']}>"
        pts    = points.get(entry["uid"], 0)
        pts_str   = f" `[{pts}🏅]`" if pts > 0 else ""
        auto_mark = " *(авто)*" if entry.get("auto_galley") else ""
        galley_lines.append(f"`{i:02}.` {name}{pts_str}{auto_mark}")

    galley_need   = max(0, GALLEY_MIN - len(galley_main))
    galley_status = f" ⚠️ ще потрібно {galley_need}" if galley_need > 0 else " ✅"
    embed.add_field(
        name=f"🚢 Галера ({len(galley_main)}/{GALLEY_MIN}){galley_status}",
        value="\n".join(galley_lines) if galley_lines else "*Поки порожньо*",
        inline=False,
    )

    # Всі кораблі
    ship_lines = []
    for i, entry in enumerate(ship_main, 1):
        member = guild.get_member(int(entry["uid"]))
        name   = member.mention if member else f"<@{entry['uid']}>"
        pts    = points.get(entry["uid"], 0)
        pts_str = f" `[{pts}🏅]`" if pts > 0 else ""
        ship_lines.append(f"`{i:02}.` {name} — *{entry['team']}*{pts_str}")

    embed.add_field(
        name=f"⛵ Всі кораблі ({len(ship_main)})",
        value="\n".join(ship_lines) if ship_lines else "*Поки порожньо*",
        inline=False,
    )

    # Лічильник
    remaining = MAX_SPOTS - total_main
    embed.add_field(
        name=f"📊 Загалом: {total_main}/{MAX_SPOTS}",
        value=f"Вільних місць: **{remaining}**" if remaining > 0 else "**Місця заповнені!**",
        inline=False,
    )

    # Вейтинг
    if day_data["waitlist"]:
        wait_lines = []
        for i, entry in enumerate(day_data["waitlist"], 1):
            member = guild.get_member(int(entry["uid"]))
            name   = member.mention if member else f"<@{entry['uid']}>"
            pts    = points.get(entry["uid"], 0)
            pts_str = f" `[{pts}🏅]`" if pts > 0 else ""
            wait_lines.append(f"`{i}.` {name} — *{entry['team']}*{pts_str}")
        embed.add_field(
            name=f"⏳ Вейтинг ліст ({len(day_data['waitlist'])})",
            value="\n".join(wait_lines),
            inline=False,
        )

    # Відпустка
    if day_data["vacation"]:
        vac_names = []
        for uid in day_data["vacation"]:
            member = guild.get_member(int(uid))
            vac_names.append(member.mention if member else f"<@{uid}>")
        embed.add_field(
            name=f"🛟 Відпустка ({len(day_data['vacation'])})",
            value="\n".join(vac_names),
            inline=False,
        )

    if image_path:
        embed.set_image(url=f"attachment://{Path(image_path).name}")

    embed.set_footer(
        text="Silent Concierge by Myxa  |  🍾 Ром, Ром, РОМ!",
        icon_url=bot_user.display_avatar.url if bot_user else None,
    )
    return embed


def _build_reminder_embed(
    day_num: int,
    day_data: dict,
    confirmed_uids: list,
    guild: discord.Guild,
    bot_user: discord.ClientUser,
    data: dict,
) -> discord.Embed:
    ts = _get_ts_for_day(data, day_num)
    embed = discord.Embed(
        title="⚔️ Морська Битва — Перевірка готовності!",
        description=(
            f"BBF починається <t:{ts}:f>!\n\n"
            "**Чи ти вже протиснувся на Морську Битву в грі?**\n"
            "Натисни кнопку нижче щоб підтвердити!"
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
        embed.add_field(
            name=f"✅ Підтвердили ({len(confirmed_lines)})",
            value="\n".join(confirmed_lines),
            inline=True,
        )
    if waiting_lines:
        embed.add_field(
            name=f"⏳ Очікуємо ({len(waiting_lines)})",
            value="\n".join(waiting_lines),
            inline=True,
        )

    embed.set_footer(
        text="Silent Concierge by Myxa  |  🍾 Ром, Ром, РОМ!",
        icon_url=bot_user.display_avatar.url if bot_user else None,
    )
    return embed

# ─── View підтвердження участі ───────────────────────────────────────────────

def _make_confirm_view(day_num: int) -> discord.ui.View:

    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(
            label="Так, я протиснувся!",
            style=discord.ButtonStyle.success,
            emoji="✅",
            custom_id=f"bbf_confirm_{day_num}",
        )
        async def btn_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            data    = _load_data()
            day_key = str(day_num)
            uid     = str(interaction.user.id)

            day_data = data.get("week", {}).get(day_key)
            if not day_data or _get_status(day_data, uid) != "main":
                await interaction.response.send_message(
                    "ℹ️ Ти не в основному списку на цей день.", ephemeral=True
                )
                return

            confirmed = data.setdefault("confirmed", {}).setdefault(day_key, [])
            if uid in confirmed:
                await interaction.response.send_message(
                    "✅ Ти вже підтвердив участь! Вдалого бою, капітане! 🍾",
                    ephemeral=True,
                )
                return

            confirmed.append(uid)
            _save_data(data)

            await interaction.response.send_message(
                "✅ Зафіксовано! Ти протиснувся на Морську Битву! Вдалого бою! ⚔️🍾",
                ephemeral=True,
            )

            guild     = interaction.guild
            msg_id    = data.get("reminder_msg_ids", {}).get(day_key)
            thread_id = data.get("thread_ids", {}).get(day_key)
            if msg_id and thread_id:
                try:
                    thread = guild.get_thread(int(thread_id))
                    if not thread:
                        try:
                            thread = await guild.fetch_channel(int(thread_id))
                        except Exception:
                            thread = None
                    if thread:
                        msg_obj   = await thread.fetch_message(int(msg_id))
                        new_embed = _build_reminder_embed(
                            day_num, day_data, confirmed, guild, guild.me, data
                        )
                        await msg_obj.edit(embed=new_embed)
                except Exception as e:
                    print(f"[BBF] Помилка оновлення reminder embed: {e}")

    return ConfirmView()

# ─── Persistent view реєстрації ──────────────────────────────────────────────

class VacationModal(discord.ui.Modal, title="🛟 Відпустка"):
    start_day = discord.ui.TextInput(
        label="День початку",
        placeholder="наприклад: 20",
        min_length=1, max_length=2, required=True,
    )
    start_month = discord.ui.TextInput(
        label="Місяць початку",
        placeholder="наприклад: 05",
        min_length=1, max_length=2, required=True,
    )
    end_day = discord.ui.TextInput(
        label="День кінця",
        placeholder="наприклад: 25",
        min_length=1, max_length=2, required=True,
    )
    end_month = discord.ui.TextInput(
        label="Місяць кінця",
        placeholder="наприклад: 05",
        min_length=1, max_length=2, required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            year = datetime.now(timezone.utc).year
            start = datetime(year, int(self.start_month.value), int(self.start_day.value), tzinfo=timezone.utc)
            end   = datetime(year, int(self.end_month.value),   int(self.end_day.value),   tzinfo=timezone.utc)

            if end < start:
                end = datetime(year + 1, int(self.end_month.value), int(self.end_day.value), tzinfo=timezone.utc)

            if (end - start).days > 60:
                await interaction.response.send_message(
                    "❌ Відпустка не може бути довшою за 60 днів.", ephemeral=True
                )
                return

        except ValueError:
            await interaction.response.send_message(
                "❌ Невірний формат дати. Введіть числа, наприклад день: 20, місяць: 05.",
                ephemeral=True,
            )
            return

        data = _load_data()
        uid  = str(interaction.user.id)

        vacations = data.setdefault("vacations", {})
        vacations[uid] = {
            "start": start.strftime("%Y-%m-%d"),
            "end":   end.strftime("%Y-%m-%d"),
        }

        week = data.get("week", {})
        week_dates = data.get("week_dates", {})
        marked_days = []

        for day_key, day_data in week.items():
            date_str = week_dates.get(day_key)
            if not date_str:
                continue
            day_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            if start <= day_date <= end:
                _remove_uid(day_data, uid)
                if uid not in day_data["vacation"]:
                    day_data["vacation"].append(uid)
                day_num = int(day_key)
                marked_days.append(DAY_NAMES.get(day_num, day_key))

        _save_data(data)

        start_str = f"{int(self.start_day.value):02}.{int(self.start_month.value):02}"
        end_str   = f"{int(self.end_day.value):02}.{int(self.end_month.value):02}"

        if marked_days:
            days_text = ", ".join(marked_days)
            msg = (
                f"🛟 Відпустку зареєстровано: **{start_str} — {end_str}**\nТебе відмічено як відсутнього: {days_text}"
            )
        else:
            msg = (
                f"🛟 Відпустку зареєстровано: **{start_str} — {end_str}**\nУ цей період немає запланованих BBF."
            )

        await interaction.response.send_message(msg, ephemeral=True)

        guild = interaction.guild
        for day_key in week.keys():
            date_str = week_dates.get(day_key)
            if not date_str:
                continue
            day_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
            if start <= day_date <= end:
                await _refresh_embed(guild, data, int(day_key))


class TeamSelectView(discord.ui.View):
    def __init__(self, day_num: int):
        super().__init__(timeout=60)
        self.day_num = day_num
        options = [discord.SelectOption(label=t, value=t) for t in ALL_TEAMS]
        select  = discord.ui.Select(
            placeholder="Обери свою команду...",
            options=options,
            custom_id=f"bbf_team_select_{day_num}",
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        chosen_team = interaction.data["values"][0]
        await _process_registration(interaction, self.day_num, chosen_team)


def _make_persistent_view(day_num: int) -> discord.ui.View:

    class PersistentView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(
            label="Буду",
            style=discord.ButtonStyle.success,
            emoji="🛶",
            custom_id=f"bbf_can_{day_num}",
        )
        async def btn_can(self, interaction: discord.Interaction, button: discord.ui.Button):
            role = interaction.guild.get_role(BBF_ROLE_ID)
            if role and role not in interaction.user.roles:
                await interaction.response.send_message(
                    "❌ У тебе немає доступу до реєстрації на BBF.", ephemeral=True
                )
                return
            data    = _load_data()
            day_key = str(day_num)

            # Конвертуємо int ключі якщо є
            week = data.get("week", {})
            if week and any(isinstance(k, int) for k in week.keys()):
                data["week"] = {str(k): v for k, v in week.items()}
                week = data["week"]

            if day_key not in week:
                week_keys = list(week.keys())
                await interaction.response.send_message(
                    f"❌ Реєстрація на цей день недоступна.\n"
                    f"*(день: {day_key}, доступні: {week_keys})*",
                    ephemeral=True,
                )
                return
            view = TeamSelectView(day_num)
            await interaction.response.send_message(
                "⛵ Обери свою команду для BBF:",
                view=view,
                ephemeral=True,
            )

        @discord.ui.button(
            label="Не буду",
            style=discord.ButtonStyle.danger,
            emoji="⛵",
            custom_id=f"bbf_cant_{day_num}",
        )
        async def btn_cant(self, interaction: discord.Interaction, button: discord.ui.Button):
            role = interaction.guild.get_role(BBF_ROLE_ID)
            if role and role not in interaction.user.roles:
                await interaction.response.send_message("❌ У тебе немає доступу до BBF.", ephemeral=True)
                return
            await _handle_action(interaction, day_num, "cant")

        @discord.ui.button(
            label="Відпустка",
            style=discord.ButtonStyle.secondary,
            emoji="🛟",
            custom_id=f"bbf_vacation_{day_num}",
        )
        async def btn_vacation(self, interaction: discord.Interaction, button: discord.ui.Button):
            role = interaction.guild.get_role(BBF_ROLE_ID)
            if role and role not in interaction.user.roles:
                await interaction.response.send_message("❌ У тебе немає доступу до BBF.", ephemeral=True)
                return
            await interaction.response.send_modal(VacationModal())

        @discord.ui.button(
            label="Відмінити сьогодні",
            style=discord.ButtonStyle.secondary,
            emoji="⚓",
            custom_id=f"bbf_cancel_{day_num}",
        )
        async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            role = interaction.guild.get_role(BBF_ROLE_ID)
            if role and role not in interaction.user.roles:
                await interaction.response.send_message("❌ У тебе немає доступу до BBF.", ephemeral=True)
                return
            await _handle_action(interaction, day_num, "cancel")

    return PersistentView()

# ─── Логіка реєстрації ───────────────────────────────────────────────────────

async def _process_registration(
    interaction: discord.Interaction,
    day_num: int,
    chosen_team: str,
) -> None:
    await interaction.response.defer(ephemeral=True)

    data    = _load_data()
    day_key = str(day_num)
    points  = data.get("points", {})

    if day_key not in data.get("week", {}):
        await interaction.followup.send("❌ Реєстрація на цей день недоступна.", ephemeral=True)
        return

    day_data    = data["week"][day_key]
    uid         = str(interaction.user.id)
    prev_status = _get_status(day_data, uid)
    print(f"[BBF] Реєстрація: user={interaction.user} day={day_num} team={chosen_team} prev={prev_status}")

    # ── Оновлення команди якщо вже зареєстрований ──────────────────────────
    if prev_status in ("main", "waitlist"):
        target_list = day_data["main"] if prev_status == "main" else day_data["waitlist"]
        for entry in target_list:
            if entry["uid"] == uid:
                entry["original_team"] = chosen_team
                # Якщо зараз на галері через auto — не міняємо поточну команду
                if not entry.get("auto_galley"):
                    entry["team"] = chosen_team
                break
        _save_data(data)
        location = "основному списку" if prev_status == "main" else "вейтинг листі"
        await interaction.followup.send(
            f"✅ Твою команду оновлено на **{chosen_team}** (у {location}).", ephemeral=True
        )
        await _refresh_embed(interaction.guild, data, day_num)
        return

    # ── Прибираємо з vacation/cant якщо були ───────────────────────────────
    _remove_uid(day_data, uid)

    total_main = len(day_data["main"])

    # ── Вейтинг: ТІЛЬКИ якщо всі 20 місць зайняті ──────────────────────────
    if total_main >= MAX_SPOTS:
        entry = {
            "uid": uid,
            "team": chosen_team,
            "original_team": chosen_team,
            "auto_galley": False,
        }
        day_data["waitlist"].append(entry)
        points[uid] = points.get(uid, 0) + 1
        pos = len(day_data["waitlist"])
        pts = points[uid]
        data["points"] = points
        _save_data(data)
        await interaction.followup.send(
            f"⏳ Усі {MAX_SPOTS} місць зайняті. Ти #{pos} у вейтинг листі на **{DAY_NAMES[day_num]}** "
            f"— команда **{chosen_team}**.\n🏅 Твої очки пріоритету: **{pts}**",
            ephemeral=True,
        )
        await _refresh_embed(interaction.guild, data, day_num)
        return

    # ── Є вільне місце (< 20) ───────────────────────────────────────────────
    galley_now     = _galley_count(day_data)
    is_real_galley = chosen_team in GALLEY_TEAMS

    if galley_now < GALLEY_MIN:
        # Галера ще не повна — новий іде на Галеру
        entry = {
            "uid": uid,
            "team": GALLEY_TEAMS[0],
            "original_team": chosen_team,
            "auto_galley": not is_real_galley,
        }
        day_data["main"].append(entry)
        points[uid] = 0
        data["points"] = points
        _save_data(data)

        if is_real_galley:
            reply = (
                f"⚓ Ти в **Екіпажі Галери** на **{DAY_NAMES[day_num]}**! "
                f"Галера: {galley_now + 1}/{GALLEY_MIN}. Очки скинуто до 0."
            )
        else:
            reply = (
                f"⚓ Галера ще не укомплектована ({galley_now + 1}/{GALLEY_MIN})! "
                f"Тебе тимчасово додано до **Галери**.\n"
                f"Як тільки наберемо {GALLEY_MIN} — тебе переведуть до **{chosen_team}**. "
                f"Очки скинуто до 0."
            )

    else:
        # Галера повна (>= GALLEY_MIN)
        # Шукаємо найстаршого "корабельного" на галері (auto_galley=True) — він іде на свій корабель
        evict_index = None
        for i, e in enumerate(day_data["main"]):
            if e.get("auto_galley") and e["team"] in GALLEY_TEAMS:
                evict_index = i
                break

        if evict_index is not None:
            # Виштовхуємо найстаршого корабельного з галери → він іде на свій оригінальний корабель
            evicted          = day_data["main"][evict_index]
            evicted_original = evicted["original_team"]
            evicted["team"]       = evicted_original
            evicted["auto_galley"] = False
            # (залишається в main[], тепер у секції "Всі кораблі")

            # Нова людина займає місце на Галері
            new_entry = {
                "uid": uid,
                "team": GALLEY_TEAMS[0],
                "original_team": chosen_team,
                "auto_galley": not is_real_galley,
            }
            day_data["main"].append(new_entry)
            points[uid] = 0
            data["points"] = points
            _save_data(data)

            await _try_send_dm(
                interaction.guild, evicted["uid"],
                f"⛵ Новий учасник зайшов на Галеру — тебе переведено до **{evicted_original}** "
                f"на BBF ({DAY_NAMES[day_num]}). Вдалого бою!"
            )

            evicted_member = interaction.guild.get_member(int(evicted["uid"]))
            evicted_name   = evicted_member.display_name if evicted_member else f"<@{evicted['uid']}>"

            if is_real_galley:
                reply = (
                    f"⚓ Ти доєднався до **Екіпажу Галери** на **{DAY_NAMES[day_num]}**!\n"
                    f"**{evicted_name}** переведено до **{evicted_original}**. Очки скинуто до 0."
                )
            else:
                reply = (
                    f"⚓ Тебе додано до **Галери** на **{DAY_NAMES[day_num]}** "
                    f"(тимчасово, потім до **{chosen_team}**).\n"
                    f"**{evicted_name}** переведено до **{evicted_original}**. Очки скинуто до 0."
                )

        else:
            # Всі 8 на галері — справжні галерники (нікого виштовхнути не можна)
            # Новий іде до "Всі кораблі" (НЕ вейтинг — місця ще є!)
            new_entry = {
                "uid": uid,
                "team": chosen_team,
                "original_team": chosen_team,
                "auto_galley": False,
            }
            day_data["main"].append(new_entry)
            points[uid] = 0
            data["points"] = points
            _save_data(data)

            if is_real_galley:
                reply = (
                    f"⚓ Галера вже укомплектована справжніми галерниками!\n"
                    f"Тебе додано до **Всі кораблі** → **Екіпаж Галери** на **{DAY_NAMES[day_num]}**. "
                    f"Очки скинуто до 0."
                )
            else:
                reply = (
                    f"⛵ Галера укомплектована! Тебе одразу додано до **{chosen_team}** "
                    f"(«Всі кораблі») на **{DAY_NAMES[day_num]}**. Очки скинуто до 0."
                )

    await interaction.followup.send(reply, ephemeral=True)
    await _refresh_embed(interaction.guild, data, day_num)


async def _handle_action(
    interaction: discord.Interaction,
    day_num: int,
    action: str,
) -> None:
    await interaction.response.defer(ephemeral=True)

    data    = _load_data()
    day_key = str(day_num)

    if day_key not in data.get("week", {}):
        await interaction.followup.send("❌ Реєстрація на цей день недоступна.", ephemeral=True)
        return

    day_data    = data["week"][day_key]
    uid         = str(interaction.user.id)
    prev_status = _get_status(day_data, uid)

    if action == "cancel":
        if prev_status is None:
            await interaction.followup.send(
                "ℹ️ Ти не зареєстрований на цей день.", ephemeral=True
            )
            return
        # Перевіряємо чи людина була на галері
        was_on_galley = any(
            e["uid"] == uid and e["team"] in GALLEY_TEAMS
            for e in day_data["main"]
        )
        _remove_uid(day_data, uid)
        promoted_uid = _promote_from_waitlist(day_data) if prev_status == "main" else None
        # Якщо галера тепер не повна — повертаємо найновішого корабельного на галеру
        galley_back_uid = _refill_galley(day_data) if prev_status == "main" else None
        _save_data(data)
        msg = f"⚓ Твою участь на **{DAY_NAMES[day_num]}** скасовано. Очки збережено."
        if promoted_uid:
            m     = interaction.guild.get_member(int(promoted_uid))
            pname = m.mention if m else f"<@{promoted_uid}>"
            msg  += f"\n🛶 {pname} автоматично переміщено з вейтингу!"
            await _try_send_dm(
                interaction.guild, promoted_uid,
                f"🛶 Місце звільнилось! Тебе переведено в основний список BBF на **{DAY_NAMES[day_num]}**. Вдалого бою!"
            )
        if galley_back_uid:
            m     = interaction.guild.get_member(int(galley_back_uid))
            pname = m.mention if m else f"<@{galley_back_uid}>"
            msg  += f"\n⚓ {pname} повернуто на Галеру!"
            await _try_send_dm(
                interaction.guild, galley_back_uid,
                f"⚓ Місце на Галері звільнилось — тебе повернуто на **Екіпаж Галери** на BBF ({DAY_NAMES[day_num]}). Вдалого бою!"
            )
        await interaction.followup.send(msg, ephemeral=True)

    elif action == "cant":
        was_on_galley = any(
            e["uid"] == uid and e["team"] in GALLEY_TEAMS
            for e in day_data["main"]
        )
        _remove_uid(day_data, uid)
        day_data["cant"].append(uid)
        promoted_uid = _promote_from_waitlist(day_data) if prev_status == "main" else None
        galley_back_uid = _refill_galley(day_data) if prev_status == "main" else None
        _save_data(data)
        msg = f"⛵ Відмічено як «Не буду» на **{DAY_NAMES[day_num]}**."
        if promoted_uid:
            m     = interaction.guild.get_member(int(promoted_uid))
            pname = m.mention if m else f"<@{promoted_uid}>"
            msg  += f"\n🛶 {pname} автоматично переміщено з вейтингу!"
            await _try_send_dm(
                interaction.guild, promoted_uid,
                f"🛶 Місце звільнилось! Тебе переведено в основний список BBF на **{DAY_NAMES[day_num]}**. Вдалого бою!"
            )
        if galley_back_uid:
            m     = interaction.guild.get_member(int(galley_back_uid))
            pname = m.mention if m else f"<@{galley_back_uid}>"
            msg  += f"\n⚓ {pname} повернуто на Галеру!"
            await _try_send_dm(
                interaction.guild, galley_back_uid,
                f"⚓ Місце на Галері звільнилось — тебе повернуто на **Екіпаж Галери** на BBF ({DAY_NAMES[day_num]}). Вдалого бою!"
            )
        await interaction.followup.send(msg, ephemeral=True)

    elif action == "vacation":
        _remove_uid(day_data, uid)
        day_data["vacation"].append(uid)
        promoted_uid = _promote_from_waitlist(day_data) if prev_status == "main" else None
        galley_back_uid = _refill_galley(day_data) if prev_status == "main" else None
        _save_data(data)
        msg = f"🛟 Відмічено як «Відпустка» на **{DAY_NAMES[day_num]}**."
        if promoted_uid:
            m     = interaction.guild.get_member(int(promoted_uid))
            pname = m.mention if m else f"<@{promoted_uid}>"
            msg  += f"\n🛶 {pname} автоматично переміщено з вейтингу!"
            await _try_send_dm(
                interaction.guild, promoted_uid,
                f"🛶 Місце звільнилось! Тебе переведено в основний список BBF на **{DAY_NAMES[day_num]}**. Вдалого бою!"
            )
        if galley_back_uid:
            m     = interaction.guild.get_member(int(galley_back_uid))
            pname = m.mention if m else f"<@{galley_back_uid}>"
            msg  += f"\n⚓ {pname} повернуто на Галеру!"
            await _try_send_dm(
                interaction.guild, galley_back_uid,
                f"⚓ Місце на Галері звільнилось — тебе повернуто на **Екіпаж Галери** на BBF ({DAY_NAMES[day_num]}). Вдалого бою!"
            )
        await interaction.followup.send(msg, ephemeral=True)

    await _refresh_embed(interaction.guild, data, day_num)


async def _refresh_embed(guild: discord.Guild, data: dict, day_num: int) -> None:
    day_key   = str(day_num)
    thread_id = data.get("thread_ids", {}).get(day_key)
    msg_id    = data.get("message_ids", {}).get(day_key)
    if not msg_id:
        print(f"[BBF] _refresh_embed: немає message_id для дня {day_num}")
        return
    try:
        if thread_id:
            channel = guild.get_channel(int(thread_id))
            if not channel:
                try:
                    channel = await guild.fetch_channel(int(thread_id))
                except Exception as e:
                    print(f"[BBF] Не вдалось fetch_channel {thread_id}: {e}")
                    channel = None
        else:
            channel_id = data.get("channel_id")
            channel    = guild.get_channel(int(channel_id)) if channel_id else None
        if not channel:
            print(f"[BBF] _refresh_embed: канал не знайдено для дня {day_num}")
            return

        # Пробуємо знайти повідомлення
        try:
            msg_obj = await channel.fetch_message(int(msg_id))
        except discord.NotFound:
            print(f"[BBF] Повідомлення {msg_id} не знайдено в каналі {channel.id} — пропускаємо")
            return
        except Exception as e:
            print(f"[BBF] Помилка fetch_message {msg_id}: {e}")
            return

        image_path = data.get("day_images", {}).get(day_key)
        embed = _build_embed(
            day_num, data["week"][day_key],
            data.get("points", {}), guild, guild.me, image_path, data,
        )
        view = _make_persistent_view(day_num)

        # Спочатку пробуємо з картинкою, потім без
        if image_path and Path(image_path).exists():
            try:
                file = discord.File(image_path, filename=Path(image_path).name)
                await msg_obj.edit(embed=embed, view=view, attachments=[file])
                print(f"[BBF] Ембед дня {day_num} оновлено з картинкою")
                return
            except Exception as e:
                print(f"[BBF] Картинка не завантажилась ({e}), пробуємо без...")

        await msg_obj.edit(embed=embed, view=view)
        print(f"[BBF] Ембед дня {day_num} оновлено без картинки")

    except Exception as e:
        print(f"[BBF] Помилка оновлення ембеду дня {day_num}: {type(e).__name__}: {e}")

# ─── Cog ─────────────────────────────────────────────────────────────────────

class BBFCog(commands.Cog, name="BBF"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._register_views()
        self.reminder_task.start()
        self.backup_task.start()

    def cog_unload(self):
        self.reminder_task.cancel()
        self.backup_task.cancel()

    def _register_views(self):
        for day_num in DAY_NAMES.keys():
            self.bot.add_view(_make_persistent_view(day_num))
            self.bot.add_view(_make_confirm_view(day_num))

    @tasks.loop(minutes=1)
    async def reminder_task(self):
        now     = datetime.now(timezone.utc)
        weekday = now.weekday()

        if weekday not in DAY_NAMES:
            return

        data    = _load_data()
        day_key = str(weekday)

        if day_key not in data.get("week", {}):
            return

        guild_id = data.get("guild_id")
        if not guild_id:
            return

        guild = self.bot.get_guild(int(guild_id))
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
                thread = None
        if not thread:
            return

        day_data  = data["week"][day_key]
        main_uids = [e["uid"] for e in day_data["main"]]

        def _is_on_vacation(uid: str, data: dict, check_date: datetime) -> bool:
            vac = data.get("vacations", {}).get(uid)
            if not vac:
                return False
            try:
                start = datetime.fromisoformat(vac["start"]).replace(tzinfo=timezone.utc)
                end   = datetime.fromisoformat(vac["end"]).replace(tzinfo=timezone.utc)
                return start <= check_date <= end
            except Exception:
                return False

        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        active_uids = [uid for uid in main_uids if not _is_on_vacation(uid, data, today)]

        if (
            now.hour == REMINDER_HOUR_UTC
            and now.minute == REMINDER_MINUTE_UTC
            and not data.get("reminded", {}).get(day_key)
        ):
            if active_uids:
                mentions  = " ".join(f"<@{uid}>" for uid in active_uids)
                confirmed = data.get("confirmed", {}).get(day_key, [])
                embed = _build_reminder_embed(
                    weekday, day_data, confirmed, guild, guild.me, data
                )
                view = _make_confirm_view(weekday)
                msg  = await thread.send(content=mentions, embed=embed, view=view)
                data.setdefault("reminder_msg_ids", {})[day_key] = msg.id

            data.setdefault("reminded", {})[day_key] = True
            _save_data(data)

        if (
            now.hour == INVITE_HOUR_UTC
            and now.minute == INVITE_MINUTE_UTC
            and not data.get("invited", {}).get(day_key)
        ):
            if active_uids:
                mentions      = " ".join(f"<@{uid}>" for uid in active_uids)
                ts            = _get_ts_for_day(data, weekday)
                voice_channel = guild.get_channel(VOICE_CHANNEL_ID)
                vc_mention    = voice_channel.mention if voice_channel else f"<#{VOICE_CHANNEL_ID}>"
                await thread.send(
                    f"🚢 **Збираємось на борту!**\n"
                    f"{mentions}\n\n"
                    f"BBF о <t:{ts}:t>!\n"
                    f"Заходьте в голосовий канал: {vc_mention} 🍾⚓"
                )

            data.setdefault("invited", {})[day_key] = True
            _save_data(data)

    @reminder_task.before_loop
    async def before_reminder(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="bbf_старт",
        description="[Офіцер] Запустити тижневу реєстрацію на BBF",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_start(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        old_data   = _load_data()
        old_points = old_data.get("points", {})

        category_to_clean = interaction.guild.get_channel(BBF_CATEGORY_ID)
        if category_to_clean:
            for ch in list(category_to_clean.channels):
                if ch.name.startswith("📅-"):
                    try:
                        await ch.delete()
                        print(f"[BBF] Видалено старий канал: {ch.name}")
                        await asyncio.sleep(0.3)
                    except Exception as e:
                        print(f"[BBF] Не вдалось видалити {ch.name}: {e}")
        else:
            print("[BBF] Категорію для очистки не знайдено")

        data = _empty_data()
        data["points"]     = old_points
        data["guild_id"]   = interaction.guild.id
        data["channel_id"] = interaction.channel.id

        week_dates = _get_week_dates()
        for day_num, day_date in week_dates.items():
            data["week_dates"][str(day_num)] = day_date.strftime("%Y-%m-%d")

        role         = interaction.guild.get_role(BBF_ROLE_ID)
        role_mention = role.mention if role else f"<@&{BBF_ROLE_ID}>"

        await interaction.channel.send(
            f"{role_mention} ⚓ **Реєстрація на BBF цього тижня відкрита!** 🍾"
        )

        category = interaction.guild.get_channel(BBF_CATEGORY_ID)
        if not category:
            await interaction.followup.send("❌ Категорію не знайдено.", ephemeral=True)
            return

        today_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        for day_num, day_name in DAY_NAMES.items():
            day_key  = str(day_num)
            day_date = week_dates[day_num].replace(hour=0, minute=0, second=0, microsecond=0)

            if day_date < today_date:
                print(f"[BBF] Пропускаємо {day_name} {day_date.day:02}.{day_date.month:02} — вже минув")
                continue

            date_str = f"{day_date.day:02}.{day_date.month:02}"

            data["week"][day_key] = _empty_day()
            image_path = _pick_image(data, day_key)

            embed = _build_embed(
                day_num, data["week"][day_key],
                data["points"], interaction.guild,
                self.bot.user, image_path, data,
            )
            view = _make_persistent_view(day_num)

            try:
                print(f"[BBF] ── Починаю день {day_name} {date_str} ──")
                channel = await interaction.guild.create_text_channel(
                    name=f"📅-{day_name.lower()}-{date_str}",
                    category=category,
                    topic=f"BBF реєстрація — {day_name} {date_str}",
                )
                data["thread_ids"][day_key] = channel.id
                print(f"[BBF] Канал створено: {channel.id}")

                img_exists = image_path and Path(image_path).exists()
                if img_exists:
                    try:
                        file = discord.File(image_path, filename=Path(image_path).name)
                        msg  = await channel.send(file=file, embed=embed, view=view)
                        print(f"[BBF] Ембед з картинкою: {msg.id}")
                    except Exception as e1:
                        print(f"[BBF] Картинка не відправилась ({e1})")
                        msg = await channel.send(embed=embed, view=view)
                else:
                    print(f"[BBF] Картинка не знайдена: {image_path}")
                    msg = await channel.send(embed=embed, view=view)

                data["message_ids"][day_key] = msg.id

                await channel.send(
                    f"{role_mention} 📋 Реєстрація на **{day_name} {date_str}** відкрита! 🛶"
                )
                print(f"[BBF] День {day_name} готово ✅")
                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"[BBF] ПОМИЛКА створення каналу для {day_name}: {type(e).__name__}: {e}")

        _save_data(data)
        await interaction.followup.send(
            "✅ Реєстрацію на BBF відкрито! Створено 6 каналів з ембедами.",
            ephemeral=True,
        )

    @app_commands.command(
        name="bbf_очки",
        description="Переглянути таблицю очок пріоритету",
    )
    async def bbf_points(self, interaction: discord.Interaction):
        data   = _load_data()
        points = {k: v for k, v in data.get("points", {}).items() if v > 0}

        if not points:
            await interaction.response.send_message(
                "ℹ️ Поки ніхто не має очок пріоритету.", ephemeral=True
            )
            return

        sorted_pts = sorted(points.items(), key=lambda x: x[1], reverse=True)
        lines = []
        for uid, pts in sorted_pts:
            member = interaction.guild.get_member(int(uid))
            name = member.mention if member else f"<@{uid}>"
            lines.append(f"**{name}** — {pts} 🏅")

        embed = discord.Embed(
            title="🏅 Таблиця очок пріоритету BBF",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(
            text="Silent Concierge by Myxa  |  🍾 Ром, Ром, РОМ!",
            icon_url=self.bot.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="bbf_скинути_очки",
        description="[Офіцер] Скинути очки пріоритету гравцю або всім",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(member="Гравець (залиш порожнім щоб скинути всім)")
    async def bbf_reset_points(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ):
        data = _load_data()
        if member:
            data["points"][str(member.id)] = 0
            _save_data(data)
            await interaction.response.send_message(
                f"✅ Очки {member.mention} скинуто до 0.", ephemeral=True
            )
        else:
            data["points"] = {}
            _save_data(data)
            await interaction.response.send_message(
                "✅ Очки всіх гравців скинуто.", ephemeral=True
            )

    @app_commands.command(
        name="bbf_статус",
        description="Переглянути свій статус на поточний тиждень BBF",
    )
    async def bbf_status(self, interaction: discord.Interaction):
        data = _load_data()
        uid  = str(interaction.user.id)
        week = data.get("week", {})

        if not week:
            await interaction.response.send_message(
                "ℹ️ Реєстрація на цей тиждень ще не відкрита.", ephemeral=True
            )
            return

        labels = {
            "main":     "✅ Основний список",
            "waitlist": "⏳ Вейтинг ліст",
            "vacation": "🛟 Відпустка",
            "cant":     "⛵ Не буду",
            None:       "➖ Не зареєстрований",
        }

        lines = []
        for day_num, day_name in DAY_NAMES.items():
            day_key  = str(day_num)
            day_date = data.get("week_dates", {}).get(day_key, "")
            date_label = ""
            if day_date:
                d = datetime.fromisoformat(day_date)
                date_label = f" {d.day:02}.{d.month:02}"

            if day_key not in week:
                continue
            status   = _get_status(week[day_key], uid)
            label    = labels[status]
            entry    = _get_entry(week[day_key], uid)
            team_str = f" — *{entry['team']}*" if entry else ""
            if status == "waitlist":
                pos = next(
                    (i + 1 for i, e in enumerate(week[day_key]["waitlist"]) if e["uid"] == uid),
                    "?"
                )
                label += f" (#{pos})"
            lines.append(f"**{day_name}{date_label}**: {label}{team_str}")

        pts = data.get("points", {}).get(uid, 0)
        embed = discord.Embed(
            title="📋 Твій статус BBF цього тижня",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        embed.set_footer(
            text=f"Silent Concierge by Myxa  |  🍾 Ром, Ром, РОМ!  |  🏅 Твої очки: {pts}",
            icon_url=self.bot.user.display_avatar.url,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="bbf_оновити",
        description="[Офіцер] Вручну оновити всі ембеди BBF",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = _load_data()

        if not data.get("week"):
            await interaction.followup.send("❌ Реєстрація ще не була запущена.", ephemeral=True)
            return

        for day_num in DAY_NAMES.keys():
            await _refresh_embed(interaction.guild, data, day_num)

        await interaction.followup.send("✅ Всі ембеди оновлено.", ephemeral=True)

    @tasks.loop(minutes=15)
    async def backup_task(self):
        data = _load_data()
        if data.get("guild_id"):
            _save_backup(data)

    @backup_task.before_loop
    async def before_backup(self):
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="bbf_бекапи",
        description="[Офіцер] Показати список останніх бекапів",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_backups_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        backups = _list_backups()
        if not backups:
            await interaction.followup.send("ℹ️ Бекапів немає.", ephemeral=True)
            return

        lines = []
        for b in backups:
            ts = b.get("timestamp", b["_id"])
            try:
                dt = datetime.fromisoformat(ts)
                unix = int(dt.timestamp())
                lines.append(f"`{b['_id']}` — <t:{unix}:f>")
            except Exception:
                lines.append(f"`{b['_id']}`")

        embed = discord.Embed(
            title="💾 Останні бекапи BBF",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Використайте /bbf_відновити <id> щоб відновити")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(
        name="bbf_відновити",
        description="[Офіцер] Відновити дані з бекапу",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(backup_id="ID бекапу (наприклад: 2026-05-20_14-30)")
    async def bbf_restore(self, interaction: discord.Interaction, backup_id: str):
        await interaction.response.defer(ephemeral=True)
        data = _restore_backup(backup_id)
        if not data:
            await interaction.followup.send(f"❌ Бекап `{backup_id}` не знайдено.", ephemeral=True)
            return
        _save_data(data)
        await interaction.followup.send(
            f"✅ Дані відновлено з бекапу `{backup_id}`!\nВикористайте `/bbf_оновити` щоб оновити ембеди.",
            ephemeral=True,
        )

    @app_commands.command(
        name="bbf_очистити",
        description="[Офіцер] Видалити всі старі BBF гілки з каналу",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_cleanup(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        thread_parent = interaction.guild.get_channel(THREAD_PARENT_CHANNEL_ID)
        if not thread_parent:
            await interaction.followup.send("❌ Канал не знайдено.", ephemeral=True)
            return

        deleted = 0
        failed  = 0

        all_threads = list(thread_parent.threads)

        try:
            async for thread in thread_parent.archived_threads(limit=100):
                all_threads.append(thread)
        except Exception as e:
            print(f"[BBF] archived_threads помилка: {e}")

        for thread in all_threads:
            if thread.name.startswith("BBF —"):
                try:
                    await thread.delete()
                    deleted += 1
                    print(f"[BBF] Видалено: {thread.name}")
                    await asyncio.sleep(0.5)
                except Exception as e:
                    failed += 1
                    print(f"[BBF] Не вдалось видалити {thread.name}: {e}")

        await interaction.followup.send(
            f"✅ Видалено гілок: **{deleted}**" + (f"\n❌ Не вдалось: **{failed}**" if failed else ""),
            ephemeral=True,
        )

    @app_commands.command(
        name="bbf_оновити_кнопки",
        description="[Офіцер] Оновити кнопки в існуючих каналах без видалення людей",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_refresh_buttons(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = _load_data()

        if not data.get("week"):
            await interaction.followup.send("❌ Реєстрація ще не була запущена.", ephemeral=True)
            return

        updated = 0

        for day_num in DAY_NAMES.keys():
            day_key = str(day_num)
            if day_key not in data.get("week", {}):
                continue

            msg_id    = data.get("message_ids", {}).get(day_key)
            thread_id = data.get("thread_ids", {}).get(day_key)

            if not msg_id or not thread_id:
                continue

            try:
                channel = interaction.guild.get_channel(int(thread_id))
                if not channel:
                    channel = await interaction.guild.fetch_channel(int(thread_id))
                if not channel:
                    continue

                msg_obj    = await channel.fetch_message(int(msg_id))
                image_path = data.get("day_images", {}).get(day_key)
                embed = _build_embed(
                    day_num, data["week"][day_key],
                    data.get("points", {}), interaction.guild,
                    self.bot.user, image_path, data,
                )
                view = _make_persistent_view(day_num)

                if image_path and Path(image_path).exists():
                    try:
                        file = discord.File(image_path, filename=Path(image_path).name)
                        await msg_obj.edit(embed=embed, view=view, attachments=[file])
                    except Exception:
                        await msg_obj.edit(embed=embed, view=view)
                else:
                    await msg_obj.edit(embed=embed, view=view)

                updated += 1
                print(f"[BBF] Кнопки оновлено для дня {DAY_NAMES[day_num]}")
            except Exception as e:
                print(f"[BBF] Помилка оновлення кнопок дня {day_num}: {e}")

        await interaction.followup.send(
            f"✅ Кнопки оновлено в **{updated}** каналах. Люди збережені!",
            ephemeral=True,
        )


    @app_commands.command(
        name="bbf_переслати",
        description="[Офіцер] Надіслати новий ембед в канал (якщо старий видалено)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_resend(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = _load_data()

        if not data.get("week"):
            await interaction.followup.send("❌ Реєстрація ще не була запущена.", ephemeral=True)
            return

        sent = 0
        role         = interaction.guild.get_role(BBF_ROLE_ID)
        role_mention = role.mention if role else f"<@&{BBF_ROLE_ID}>"

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

                # Перевіряємо чи існує старе повідомлення
                msg_id   = data.get("message_ids", {}).get(day_key)
                msg_exists = False
                if msg_id:
                    try:
                        await channel.fetch_message(int(msg_id))
                        msg_exists = True
                    except Exception:
                        msg_exists = False

                if msg_exists:
                    continue  # повідомлення є — не надсилаємо нове

                # Надсилаємо новий ембед
                image_path = data.get("day_images", {}).get(day_key)
                embed = _build_embed(
                    day_num, data["week"][day_key],
                    data.get("points", {}), interaction.guild,
                    self.bot.user, image_path, data,
                )
                view = _make_persistent_view(day_num)

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
                print(f"[BBF] Новий ембед надіслано для {DAY_NAMES[day_num]}")

            except Exception as e:
                print(f"[BBF] Помилка переслання ембеду дня {day_num}: {e}")

        _save_data(data)

        if sent:
            await interaction.followup.send(
                f"✅ Надіслано нових ембедів: **{sent}**. Люди збережені!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "ℹ️ Всі ембеди вже існують — нічого не надсилалось.",
                ephemeral=True,
            )

    @app_commands.command(
        name="bbf_мігрувати",
        description="[Офіцер] Виправити auto_galley для існуючих даних (запустити один раз після оновлення)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_migrate(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = _load_data()

        # Конвертуємо int ключі в str (MongoDB іноді повертає int ключі)
        for field in ("week", "week_dates", "message_ids", "thread_ids",
                      "reminder_msg_ids", "confirmed", "reminded", "invited", "day_images"):
            raw = data.get(field, {})
            if raw and any(isinstance(k, int) for k in raw.keys()):
                data[field] = {str(k): v for k, v in raw.items()}

        week = data.get("week", {})

        if not week:
            all_keys = list(data.keys())
            raw_week = data.get("week")
            await interaction.followup.send(
                f"❌ `week` порожній.\nКлючі в даних: `{all_keys}`\nRaw week: `{raw_week}`",
                ephemeral=True,
            )
            return

        report_lines = []

        for day_key, day_data in week.items():
            main = day_data.get("main", [])
            day_num = int(day_key)
            day_name = DAY_NAMES.get(day_num, day_key)

            # 1. Виставляємо original_team якщо відсутній
            for entry in main:
                if "original_team" not in entry:
                    entry["original_team"] = entry["team"]

            # 2. Виставляємо правильний auto_galley
            for entry in main:
                if entry["team"] in GALLEY_TEAMS:
                    entry["auto_galley"] = entry["original_team"] not in GALLEY_TEAMS
                else:
                    entry["auto_galley"] = False

            # 3. Якщо галера не повна і є корабельні в "Всі кораблі" — переміщуємо їх на галеру
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

            if moved:
                report_lines.append(f"**{day_name}**: переміщено на галеру {len(moved)} чол.")
            else:
                galley_count = sum(1 for e in main if e["team"] in GALLEY_TEAMS)
                report_lines.append(f"**{day_name}**: ок (галера {galley_count}/{GALLEY_MIN})")

        _save_data(data)

        # Оновлюємо всі ембеди
        for day_num in DAY_NAMES.keys():
            await _refresh_embed(interaction.guild, data, day_num)

        report = "\n".join(report_lines) if report_lines else "Змін не було"
        await interaction.followup.send(
            f"✅ Міграцію завершено! Ембеди оновлено.\n\n{report}",
            ephemeral=True,
        )

# ─── Setup ───────────────────────────────────────────────────────────────────

def _save_backup(data: dict) -> None:
    try:
        db = _get_db()
        backup = {
            "_id": datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data
        }
        db["bbf_backups"].replace_one(
            {"_id": backup["_id"]},
            backup,
            upsert=True
        )
        backups = list(db["bbf_backups"].find({}, {"_id": 1}).sort("_id", -1))
        if len(backups) > 48:
            old_ids = [b["_id"] for b in backups[48:]]
            db["bbf_backups"].delete_many({"_id": {"$in": old_ids}})
        print(f"[BBF] Бекап збережено: {backup['_id']}")
    except Exception as e:
        print(f"[BBF][ERROR] Бекап помилка: {e}")


def _list_backups() -> list:
    try:
        db = _get_db()
        result = list(db["bbf_backups"].find({}, {"_id": 1, "timestamp": 1}).sort("_id", -1).limit(20))
        print(f"[BBF] _list_backups: знайдено {len(result)}")
        return result
    except Exception as e:
        print(f"[BBF][ERROR] _list_backups: {e}")
        return []


def _restore_backup(backup_id: str) -> dict | None:
    try:
        db = _get_db()
        doc = db["bbf_backups"].find_one({"_id": backup_id})
        if doc:
            doc.pop("_id", None)
            doc.pop("timestamp", None)
            return doc
        return None
    except Exception:
        return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BBFCog(bot))
    print("[COG] BBFCog завантажено")
    try:
        db = _get_db()
        db.command("ping")
        print("[BBF] MongoDB ping OK ✅")
    except Exception as e:
        print(f"[BBF][ERROR] MongoDB ping FAIL: {e}")
