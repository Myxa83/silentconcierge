# -*- coding: utf-8 -*-
# bbf_cog.py

import json
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

# ─── Налаштування ────────────────────────────────────────────────────────────

BBF_DATA_FILE            = Path("data/bbf_data.json")
MAX_SPOTS                = 20
GALLEY_MIN               = 8
THREAD_PARENT_CHANNEL_ID = 1486067779177152523
VOICE_CHANNEL_ID         = 1486420425188839495
BBF_ROLE_ID              = 1470790564718055434

# UTC часи (CEST = UTC+2)
REMINDER_HOUR_UTC    = 17   # 19:30 CEST
REMINDER_MINUTE_UTC  = 30
INVITE_HOUR_UTC      = 17   # 19:45 CEST
INVITE_MINUTE_UTC    = 45
BBF_START_HOUR_UTC   = 18   # 20:00 CEST
BBF_START_MINUTE_UTC = 0

# weekday(): 0=пн,1=вт,2=ср,3=чт,4=пт,5=сб,6=нд
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
    """Повертає дати для кожного дня BBF цього тижня (пн-нд)."""
    now = datetime.now(timezone.utc)
    # Початок тижня — понеділок
    monday = now - timedelta(days=now.weekday())
    dates = {}
    for day_num in DAY_NAMES.keys():
        dates[day_num] = monday + timedelta(days=day_num)
    return dates


def _bbf_timestamp(day_date: datetime) -> int:
    """Unix timestamp початку BBF для конкретної дати."""
    target = day_date.replace(
        hour=BBF_START_HOUR_UTC,
        minute=BBF_START_MINUTE_UTC,
        second=0, microsecond=0,
    )
    return int(target.timestamp())

# ─── Збереження / завантаження ───────────────────────────────────────────────

def _load_data() -> dict:
    if BBF_DATA_FILE.exists():
        try:
            return json.loads(BBF_DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _empty_data()


def _empty_data() -> dict:
    return {
        "week": {},            # {"0": day_data, ...}
        "week_dates": {},      # {"0": "2026-05-20", ...} — дати цього тижня
        "points": {},          # {"uid": int}
        "channel_id": None,
        "message_ids": {},     # {"0": msg_id}
        "thread_ids": {},      # {"0": thread_id}
        "reminder_msg_ids": {},
        "confirmed": {},       # {"0": ["uid"]}
        "guild_id": None,
        "used_images": [],
        "day_images": {},
        "reminded": {},
        "invited": {},
    }


def _save_data(data: dict) -> None:
    BBF_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    BBF_DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
        day_data["main"].append(entry)
        return entry["uid"]
    return None


async def _try_send_dm(guild: discord.Guild, uid: str, msg: str) -> None:
    try:
        member = guild.get_member(int(uid))
        if member:
            await member.send(msg)
    except Exception:
        pass


async def _check_galley_complete(day_data: dict, guild: discord.Guild) -> list[str]:
    if _galley_count(day_data) < GALLEY_MIN:
        return []
    transferred = []
    for entry in day_data["main"]:
        if entry.get("auto_galley") and entry["team"] in GALLEY_TEAMS:
            original = entry.get("original_team", entry["team"])
            if original not in GALLEY_TEAMS:
                entry["team"] = original
                entry["auto_galley"] = False
                transferred.append((entry["uid"], original))
    for uid, original_team in transferred:
        await _try_send_dm(
            guild, uid,
            f"⛵ Галера укомплектована! Тебе переведено до **{original_team}** на BBF. Вдалого бою!"
        )
    return [uid for uid, _ in transferred]

# ─── Побудова ембедів ────────────────────────────────────────────────────────

def _get_ts_for_day(data: dict, day_num: int) -> int:
    """Бере збережену дату з даних і рахує timestamp."""
    day_key   = str(day_num)
    date_str  = data.get("week_dates", {}).get(day_key)
    if date_str:
        day_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    else:
        # Fallback — рахуємо від поточного тижня
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

    # Дата для заголовку
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
    ship_main   = [e for e in day_data["main"] if e["team"] in SHIP_TEAMS]
    total_main  = len(day_data["main"])

    # Галера
    galley_lines = []
    for i, entry in enumerate(galley_main, 1):
        member = guild.get_member(int(entry["uid"]))
        name   = member.display_name if member else f"<@{entry['uid']}>"
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
        name   = member.display_name if member else f"<@{entry['uid']}>"
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
            name   = member.display_name if member else f"<@{entry['uid']}>"
            pts    = points.get(entry["uid"], 0)
            wait_lines.append(f"`{i}.` {name} — *{entry['team']}* `[{pts}🏅]`")
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
            vac_names.append(member.display_name if member else f"<@{uid}>")
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
        name   = member.display_name if member else f"<@{uid}>"
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

            # Оновлюємо ембед нагадування
            guild     = interaction.guild
            msg_id    = data.get("reminder_msg_ids", {}).get(day_key)
            thread_id = data.get("thread_ids", {}).get(day_key)
            if msg_id and thread_id:
                try:
                    thread = guild.get_channel(int(thread_id))
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
            # Перевіряємо чи реєстрація активна для цього дня
            data    = _load_data()
            day_key = str(day_num)
            if day_key not in data.get("week", {}):
                await interaction.response.send_message(
                    "❌ Реєстрація на цей день недоступна.", ephemeral=True
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
            await _handle_action(interaction, day_num, "cant")

        @discord.ui.button(
            label="Відпустка",
            style=discord.ButtonStyle.secondary,
            emoji="🛟",
            custom_id=f"bbf_vacation_{day_num}",
        )
        async def btn_vacation(self, interaction: discord.Interaction, button: discord.ui.Button):
            await _handle_action(interaction, day_num, "vacation")

        @discord.ui.button(
            label="Відмінити сьогодні",
            style=discord.ButtonStyle.secondary,
            emoji="⚓",
            custom_id=f"bbf_cancel_{day_num}",
        )
        async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
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

    # Оновлення команди якщо вже зареєстрований
    if prev_status == "main":
        for entry in day_data["main"]:
            if entry["uid"] == uid:
                entry["original_team"] = chosen_team
                if not entry.get("auto_galley"):
                    entry["team"] = chosen_team
        _save_data(data)
        await interaction.followup.send(
            f"✅ Твою команду оновлено на **{chosen_team}**.", ephemeral=True
        )
        await _refresh_embed(interaction.guild, data, day_num)
        return

    if prev_status == "waitlist":
        for entry in day_data["waitlist"]:
            if entry["uid"] == uid:
                entry["original_team"] = chosen_team
                entry["team"] = chosen_team
        _save_data(data)
        await interaction.followup.send(
            f"✅ Команду у вейтинг листі оновлено на **{chosen_team}**.", ephemeral=True
        )
        await _refresh_embed(interaction.guild, data, day_num)
        return

    _remove_uid(day_data, uid)
    galley_now = _galley_count(day_data)

    if len(day_data["main"]) < MAX_SPOTS:
        if galley_now < GALLEY_MIN and chosen_team not in GALLEY_TEAMS:
            entry = {
                "uid": uid,
                "team": GALLEY_TEAMS[0],
                "original_team": chosen_team,
                "auto_galley": True,
            }
            day_data["main"].append(entry)
            transferred = await _check_galley_complete(day_data, interaction.guild)
            if points.get(uid, 0) > 0:
                points[uid] = 0
            if uid in transferred:
                reply = (
                    f"⛵ Галера щойно укомплектувалась! "
                    f"Тебе одразу додано до **{chosen_team}**. Очки скинуто до 0."
                )
            else:
                reply = (
                    f"⚓ Галера ще не укомплектована ({galley_now + 1}/{GALLEY_MIN})! "
                    f"Тебе тимчасово додано до **Галери**.\n"
                    f"Як тільки наберемо {GALLEY_MIN} — тебе автоматично переведуть до **{chosen_team}**."
                )
        else:
            entry = {
                "uid": uid,
                "team": chosen_team,
                "original_team": chosen_team,
                "auto_galley": False,
            }
            day_data["main"].append(entry)
            await _check_galley_complete(day_data, interaction.guild)
            if points.get(uid, 0) > 0:
                points[uid] = 0
            reply = (
                f"🛶 Ти в основному списку на **{DAY_NAMES[day_num]}** "
                f"— команда **{chosen_team}**! Очки скинуто до 0."
            )
    else:
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
        reply = (
            f"⏳ Місця заповнені. Ти #{pos} у вейтинг листі на **{DAY_NAMES[day_num]}** "
            f"— команда **{chosen_team}**.\n🏅 Твої очки пріоритету: **{pts}**"
        )

    data["points"] = points
    _save_data(data)
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
        _remove_uid(day_data, uid)
        promoted_uid = _promote_from_waitlist(day_data) if prev_status == "main" else None
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
        await interaction.followup.send(msg, ephemeral=True)

    elif action == "cant":
        _remove_uid(day_data, uid)
        day_data["cant"].append(uid)
        promoted_uid = _promote_from_waitlist(day_data) if prev_status == "main" else None
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
        await interaction.followup.send(msg, ephemeral=True)

    elif action == "vacation":
        _remove_uid(day_data, uid)
        day_data["vacation"].append(uid)
        promoted_uid = _promote_from_waitlist(day_data) if prev_status == "main" else None
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
        await interaction.followup.send(msg, ephemeral=True)

    await _refresh_embed(interaction.guild, data, day_num)


async def _refresh_embed(guild: discord.Guild, data: dict, day_num: int) -> None:
    day_key   = str(day_num)
    thread_id = data.get("thread_ids", {}).get(day_key)
    msg_id    = data.get("message_ids", {}).get(day_key)
    if not msg_id:
        return
    try:
        if thread_id:
            channel = guild.get_channel(int(thread_id))
        else:
            channel_id = data.get("channel_id")
            channel    = guild.get_channel(int(channel_id)) if channel_id else None
        if not channel:
            return
        msg_obj    = await channel.fetch_message(int(msg_id))
        image_path = data.get("day_images", {}).get(day_key)
        embed = _build_embed(
            day_num, data["week"][day_key],
            data.get("points", {}), guild, guild.me, image_path, data,
        )
        view = _make_persistent_view(day_num)
        if image_path:
            try:
                file = discord.File(image_path, filename=Path(image_path).name)
                await msg_obj.edit(embed=embed, view=view, attachments=[file])
            except Exception:
                await msg_obj.edit(embed=embed, view=view)
        else:
            await msg_obj.edit(embed=embed, view=view)
    except Exception as e:
        print(f"[BBF] Помилка оновлення ембеду дня {day_num}: {e}")

# ─── Cog ─────────────────────────────────────────────────────────────────────

class BBFCog(commands.Cog, name="BBF"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._register_views()
        self.reminder_task.start()

    def cog_unload(self):
        self.reminder_task.cancel()

    def _register_views(self):
        """Реєструє всі persistent views при запуску бота."""
        for day_num in DAY_NAMES.keys():
            self.bot.add_view(_make_persistent_view(day_num))
            self.bot.add_view(_make_confirm_view(day_num))

    # ── Таск нагадувань ──────────────────────────────────────────────────────

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
            return

        day_data  = data["week"][day_key]
        main_uids = [e["uid"] for e in day_data["main"]]

        # О 19:30 CEST — нагадування з кнопкою підтвердження
        if (
            now.hour == REMINDER_HOUR_UTC
            and now.minute == REMINDER_MINUTE_UTC
            and not data.get("reminded", {}).get(day_key)
        ):
            if main_uids:
                mentions  = " ".join(f"<@{uid}>" for uid in main_uids)
                confirmed = data.get("confirmed", {}).get(day_key, [])
                embed = _build_reminder_embed(
                    weekday, day_data, confirmed, guild, guild.me, data
                )
                view = _make_confirm_view(weekday)
                msg  = await thread.send(content=mentions, embed=embed, view=view)
                data.setdefault("reminder_msg_ids", {})[day_key] = msg.id

            data.setdefault("reminded", {})[day_key] = True
            _save_data(data)

        # О 19:45 CEST — запрошення в голосовий
        if (
            now.hour == INVITE_HOUR_UTC
            and now.minute == INVITE_MINUTE_UTC
            and not data.get("invited", {}).get(day_key)
        ):
            if main_uids:
                mentions      = " ".join(f"<@{uid}>" for uid in main_uids)
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

    # ── /bbf_старт ───────────────────────────────────────────────────────────

    @app_commands.command(
        name="bbf_старт",
        description="[Офіцер] Запустити тижневу реєстрацію на BBF",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def bbf_start(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        # Зберігаємо старі очки, все інше стираємо
        old_data = _load_data()
        old_points = old_data.get("points", {})

        data = _empty_data()
        data["points"]   = old_points
        data["guild_id"] = interaction.guild.id
        data["channel_id"] = interaction.channel.id

        # Рахуємо дати цього тижня
        week_dates = _get_week_dates()
        for day_num, day_date in week_dates.items():
            data["week_dates"][str(day_num)] = day_date.strftime("%Y-%m-%d")

        role         = interaction.guild.get_role(BBF_ROLE_ID)
        role_mention = role.mention if role else f"<@&{BBF_ROLE_ID}>"

        await interaction.channel.send(
            f"{role_mention} ⚓ **Реєстрація на BBF цього тижня відкрита!** 🍾"
        )

        thread_parent = interaction.guild.get_channel(THREAD_PARENT_CHANNEL_ID)
        if not thread_parent:
            thread_parent = interaction.channel

        for day_num, day_name in DAY_NAMES.items():
            day_key  = str(day_num)
            day_date = week_dates[day_num]
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
                thread = await thread_parent.create_thread(
                    name=f"BBF — {day_name} {date_str}",
                    type=discord.ChannelType.public_thread,
                    auto_archive_duration=10080,
                )
                data["thread_ids"][day_key] = thread.id

                try:
                    file = discord.File(image_path, filename=Path(image_path).name)
                    msg  = await thread.send(file=file, embed=embed, view=view)
                except Exception:
                    msg = await thread.send(embed=embed, view=view)

                data["message_ids"][day_key] = msg.id

                await thread.send(
                    f"{role_mention} 📋 Реєстрація на **{day_name} {date_str}** відкрита! 🛶"
                )

            except Exception as e:
                print(f"[BBF] Помилка створення гілки для {day_name}: {e}")
                try:
                    file = discord.File(image_path, filename=Path(image_path).name)
                    msg  = await interaction.channel.send(file=file, embed=embed, view=view)
                except Exception:
                    msg = await interaction.channel.send(embed=embed, view=view)
                data["message_ids"][day_key] = msg.id

        _save_data(data)
        await interaction.followup.send(
            "✅ Реєстрацію на BBF відкрито! Створено 6 гілок з ембедами.",
            ephemeral=True,
        )

    # ── /bbf_очки ────────────────────────────────────────────────────────────

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
            name = member.display_name if member else f"<@{uid}>"
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

    # ── /bbf_скинути_очки ────────────────────────────────────────────────────

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

    # ── /bbf_статус ──────────────────────────────────────────────────────────

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

    # ── /bbf_оновити ─────────────────────────────────────────────────────────

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


# ─── Setup ───────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BBFCog(bot))
    print("[COG] BBFCog завантажено")
