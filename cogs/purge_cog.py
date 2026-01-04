# -*- coding: utf-8 -*-
# raid_cog_v7.9_final_no_bs.py — Silent Concierge RaidCog
#
# формат ембеда = як на референсі:
# <:guildboss:1376430317270995024> Гільдійні боси з {guild_name}
# 📅 дата (українською)
# статус (ANSI зелений/червоний)
# "Кому шепотіти" (хости червоним у чорному блоці)
# далі найм/сервер/старт, шлях, боси, примітка, слоти
#
# slash-команди:
#   /raid_test
#   /raid_create
#   /raid_edit
#   /raid_slots
#
# авто:
#   - через 10 хв до старту -> ЗАЧИНЕНО
#   - чистка старих рейдів
#   - підказки (autocomplete) з JSON
#
# JSON у ./data :
#   servers.json      -> ["Kama5","Mediah2",...]
#   paths.json        -> { "double":{"label":"...","route":"..."}, "single":{...}, ... }
#   notes.json        -> ["фраза1","фраза2",...]
#   boss_levels.json  -> ["1 рівня","2 рівня","3 рівня"]
#   hosts.json        -> ["Myxa","Sasoriza","Darkcevian",...]
#   raids.json        -> { "<message_id>": { raid data ... } }

import discord, json, datetime
from discord import app_commands
from discord.ext import commands, tasks
from pathlib import Path
from zoneinfo import ZoneInfo

# ---- КОНСТАНТИ СТИЛЮ ----
COLOR_OPEN   = 0x4FFF4F
COLOR_CLOSED = 0xFF1E1E

IMG_OPEN   = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/maxresdefault.jpg"
IMG_CLOSED = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/2025-01-19_5614766.jpg"

FOOTER_OPEN   = "Silent Concierge by Myxa | Найм активний"
FOOTER_CLOSED = "Silent Concierge by Myxa | Ще побачимось наступного найму!"

EMOJI_GUILD = "<:guildboss:1376430317270995024>"

DEFAULT_TZ = "Europe/London"

# ---- ШЛЯХИ ДО ФАЙЛІВ ----
DATA_DIR = Path().resolve() / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

RAIDS_FILE        = DATA_DIR / "raids.json"
SERVERS_FILE      = DATA_DIR / "servers.json"
PATHS_FILE        = DATA_DIR / "paths.json"
NOTES_FILE        = DATA_DIR / "notes.json"
BOSS_LEVELS_FILE  = DATA_DIR / "boss_levels.json"
HOSTS_FILE        = DATA_DIR / "hosts.json"


# ---- УТИЛІТИ ----
def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _status_to_internal(s: str) -> str:
    # будь-яке "відк..." -> open, інше -> closed
    if not s:
        return "closed"
    return "open" if "відк" in s.lower() else "closed"

def _ts(date_str: str, time_str: str, tz: str = DEFAULT_TZ):
    # date_str: "27.10.2025", time_str: "18:10"
    try:
        d, m, y = map(int, date_str.split("."))
        h, mi = map(int, time_str.split(":"))
        dt = datetime.datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz))
        return int(dt.timestamp())
    except Exception:
        return None

def _ansi_status(is_open: bool) -> str:
    if is_open:
        return "```ansi\n\u001b[1;32mВІДКРИТО\u001b[0m\n```"
    else:
        return "```ansi\n\u001b[1;31mЗАЧИНЕНО\u001b[0m\n```"

def _ansi_hosts(names: list[str]) -> str:
    # червоний текст у чорному блоці
    if not names:
        return ""
    return "".join([f"\u001b[38;5;196m{n}\u001b[0m " for n in names]).strip()

def _ukr_date_long(date_str: str | None) -> str:
    # "27.10.2025" -> "27 жовтня 2025 р."
    months = [
        "січня","лютого","березня","квітня","травня","червня",
        "липня","серпня","вересня","жовтня","листопада","грудня"
    ]
    if date_str:
        try:
            d, m, y = map(int, date_str.split("."))
            return f"{d} {months[m-1]} {y} р."
        except Exception:
            pass
    now = datetime.datetime.now()
    return f"{now.day} {months[now.month-1]} {now.year} р."

async def _edit_embed_message(bot: commands.Bot, msg_id: str, raid: dict):
    # оновлює існуюче повідомлення ембеду
    for cid in raid.get("channels", []):
        ch = bot.get_channel(cid)
        if not ch:
            continue
        try:
            msg = await ch.fetch_message(int(msg_id))
            await msg.edit(embed=_build_embed(bot, raid))
            return
        except Exception:
            continue


# ---- ПОБУДОВА ЕМБЕДУ (ЦЕ НАШ ВІЗУАЛ) ----
def _build_embed(bot: commands.Bot, raid: dict) -> discord.Embed:
    is_open = (raid.get("status") == "open")
    color = COLOR_OPEN if is_open else COLOR_CLOSED
    footer_text = FOOTER_OPEN if is_open else FOOTER_CLOSED
    bg_image = IMG_OPEN if is_open else IMG_CLOSED

    guild_name = raid.get("guild_name", "𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲")

    # заголовок з емодзі гільдії
    embed = discord.Embed(
        title=f"{EMOJI_GUILD} Гільдійні боси з {guild_name}",
        color=color
    )

    # дата (українською словами)
    date_display = _ukr_date_long(raid.get("date"))

    # 1) Дата
    embed.add_field(
        name="📅 Дата:",
        value=date_display,
        inline=False
    )

    # 2) Статус (ANSI блок)
    embed.add_field(
        name="✅ Статус:",
        value=_ansi_status(is_open),
        inline=False
    )

    # 3) Кому шепотіти (хости)
    hosts_block = _ansi_hosts(raid.get("hosts", []))
    if not hosts_block:
        hosts_block = "\u001b[38;5;196m—\u001b[0m"
    embed.add_field(
        name="📣 Кому шепотіти",
        value=f"```ansi\n{hosts_block}\n```",
        inline=False
    )

    # 4) Найм / Сервер / Старт
    hire_time = raid.get("hire_time", "—")
    start_time = raid.get("start_time", "—")
    server = raid.get("server", "—")

    embed.add_field(name="🕒 Найм:", value=hire_time, inline=True)
    embed.add_field(name="🌊 Сервер:", value=server,    inline=True)
    embed.add_field(name="🚀 Старт:", value=start_time, inline=True)

    # 5) Шлях
    embed.add_field(
        name="🗺️ Шлях:",
        value=raid.get("path", "—"),
        inline=False
    )

    # 6) Боси
    embed.add_field(
        name="🐙 Боси:",
        value=raid.get("boss_level", "—"),
        inline=False
    )

    # 7) Примітка
    note_text = raid.get("notes", "—")
    embed.add_field(
        name="📌 Примітка:",
        value=note_text,
        inline=False
    )

    # 8) Слоти
    embed.add_field(
        name="📦 Слотів:",
        value=str(raid.get("slots", 0)),
        inline=True
    )
    embed.add_field(
        name="📥 Залишилось:",
        value=str(raid.get("remaining", 0)),
        inline=True
    )

    # картинка + футер
    embed.set_image(url=bg_image)

    if bot.user:
        embed.set_footer(
            text=footer_text,
            icon_url=bot.user.display_avatar.url
        )
    else:
        embed.set_footer(text=footer_text)

    return embed


# ---- COG ----
class RaidCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # кеши для автопідказок
        self.servers = _load_json(SERVERS_FILE, [])
        self.paths   = _load_json(PATHS_FILE, {})
        self.notes   = _load_json(NOTES_FILE, [])
        self.boss_lv = _load_json(BOSS_LEVELS_FILE, [])
        self.hosts   = _load_json(HOSTS_FILE, [])

        # фон задач
        self.autorefresh.start()
        self.check_raids.start()
        self.cleanup_old_raids.start()

    # перезчитування data/*.json кожні 30с
    @tasks.loop(seconds=30)
    async def autorefresh(self):
        self.servers = _load_json(SERVERS_FILE, [])
        self.paths   = _load_json(PATHS_FILE, {})
        self.notes   = _load_json(NOTES_FILE, [])
        self.boss_lv = _load_json(BOSS_LEVELS_FILE, [])
        self.hosts   = _load_json(HOSTS_FILE, [])

    @autorefresh.before_loop
    async def before_autorefresh(self):
        await self.bot.wait_until_ready()

    # автозакриття за 10 хв до старту
    @tasks.loop(minutes=1)
    async def check_raids(self):
        raids = _load_json(RAIDS_FILE, {})
        if not raids:
            return

        now_unix = datetime.datetime.now(datetime.timezone.utc).timestamp()
        changed = False

        for mid, raid in list(raids.items()):
            start_ts = raid.get("start_ts")
            if (
                start_ts
                and raid.get("status") == "open"
                and (start_ts - now_unix) <= 600
            ):
                raid["status"] = "closed"
                await _edit_embed_message(self.bot, mid, raid)
                changed = True

        if changed:
            _save_json(RAIDS_FILE, raids)

    @check_raids.before_loop
    async def before_check_raids(self):
        await self.bot.wait_until_ready()

    # видалення старих рейдів
    @tasks.loop(minutes=30)
    async def cleanup_old_raids(self):
        raids = _load_json(RAIDS_FILE, {})
        if not raids:
            return

        today = datetime.datetime.now().date()
        changed = False

        for mid, raid in list(raids.items()):
            raw_date = raid.get("date")
            if not raw_date:
                continue
            try:
                d, m, y = map(int, raw_date.split("."))
                raid_day = datetime.date(y, m, d)
            except Exception:
                continue

            if raid_day < today:
                # видалити повідомлення
                for cid in raid.get("channels", []):
                    ch = self.bot.get_channel(cid)
                    if not ch:
                        continue
                    try:
                        msg = await ch.fetch_message(int(mid))
                        await msg.delete()
                    except Exception:
                        pass
                raids.pop(mid, None)
                changed = True

        if changed:
            _save_json(RAIDS_FILE, raids)

    @cleanup_old_raids.before_loop
    async def before_cleanup_old_raids(self):
        await self.bot.wait_until_ready()

    # ---- AUTOCOMPLETE ----
    async def guild_autocomplete(self, _: discord.Interaction, current: str):
        try:
            guilds = ["𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲", "𝗥𝖚𝗆𝖻𝗅𝗂𝗇𝗀 𝗖𝗼𝘃𝗲", "𝗦𝗲𝘅𝘆 𝗖𝗮𝘃𝗲"]
            cur = (current or "").lower()
            return [
                app_commands.Choice(name=g, value=g)
                for g in guilds
                if cur in g.lower()
            ][:25]
        except Exception:
            return []

    async def status_autocomplete(self, _: discord.Interaction, current: str):
        try:
            options = ["ВІДКРИТО", "ЗАЧИНЕНО"]
            cur = (current or "").lower()
            return [
                app_commands.Choice(name=s, value=s)
                for s in options
                if cur in s.lower()
            ][:25]
        except Exception:
            return []

    async def server_autocomplete(self, _: discord.Interaction, current: str):
        try:
            cur = (current or "").lower()
            servers = self.servers or []
            return [
                app_commands.Choice(name=s, value=s)
                for s in servers
                if cur in s.lower()
            ][:25]
        except Exception:
            return []

    async def path_autocomplete(self, _: discord.Interaction, current: str):
        try:
            cur = (current or "").lower()
            out = []
            paths = self.paths if isinstance(self.paths, dict) else {}
            for node in paths.values():
                if not isinstance(node, dict):
                    continue
                label = node.get("label", "")
                route = node.get("route", "")
                if not label:
                    continue
                if cur in label.lower():
                    out.append(app_commands.Choice(name=label, value=route))

            if not out:
                out = [
                    app_commands.Choice(
                        name="Власний маршрут",
                        value="Власний маршрут"
                    )
                ]
            return out[:25]
        except Exception:
            return [
                app_commands.Choice(
                    name="Власний маршрут",
                    value="Власний маршрут"
                )
            ]

    async def notes_autocomplete(self, _: discord.Interaction, current: str):
        try:
            cur = (current or "").lower()
            notes = self.notes or []
            return [
                app_commands.Choice(name=n, value=n)
                for n in notes
                if cur in n.lower()
            ][:25]
        except Exception:
            return []

    async def boss_autocomplete(self, _: discord.Interaction, current: str):
        try:
            cur = (current or "").lower()
            bosses = self.boss_lv or []
            return [
                app_commands.Choice(name=b, value=b)
                for b in bosses
                if cur in b.lower()
            ][:25]
        except Exception:
            return []

    async def host_autocomplete(self, _: discord.Interaction, current: str):
        try:
            cur = (current or "").lower()
            hosts = self.hosts or []
            return [
                app_commands.Choice(name=h, value=h)
                for h in hosts
                if cur in h.lower()
            ][:25]
        except Exception:
            return []

    # ---- /raid_test ----
    @app_commands.command(
        name="raid_test",
        description="Попередній перегляд рейду (без запису)"
    )
    @app_commands.autocomplete(
        guild_name=guild_autocomplete,
        status=status_autocomplete,
        server=server_autocomplete,
        path=path_autocomplete,
        boss_level=boss_autocomplete,
        notes=notes_autocomplete,
        host=host_autocomplete,
        extra_hosts=host_autocomplete,
    )
    async def raid_test(
        self,
        interaction: discord.Interaction,
        guild_name: str,
        status: str,
        date: str,
        hire_time: str,
        start_time: str,
        server: str,
        path: str,
        boss_level: str,
        host: str,
        extra_hosts: str = "",
        slots: int = 25,
        remaining: int | None = None,
        notes: str = ""
    ):
        if remaining is None:
            remaining = slots

        all_hosts = [
            h.strip()
            for h in (host + "," + extra_hosts).split(",")
            if h.strip()
        ]

        raid = {
            "guild_name": guild_name,
            "status": _status_to_internal(status),
            "date": date,
            "hire_time": hire_time,
            "start_time": start_time,
            "hire_ts": _ts(date, hire_time),
            "start_ts": _ts(date, start_time),
            "server": server,
            "path": path,
            "boss_level": boss_level,
            "hosts": all_hosts,
            "slots": slots,
            "remaining": remaining,
            "notes": notes,
            "channels": [],
        }

        await interaction.response.send_message(
            embed=_build_embed(self.bot, raid)
        )

    # ---- /raid_create ----
    @app_commands.command(
        name="raid_create",
        description="⚓ Створити рейд-оголошення в каналі"
    )
    @app_commands.autocomplete(
        guild_name=guild_autocomplete,
        status=status_autocomplete,
        server=server_autocomplete,
        path=path_autocomplete,
        boss_level=boss_autocomplete,
        notes=notes_autocomplete,
        host=host_autocomplete,
        extra_hosts=host_autocomplete,
    )
    async def raid_create(
        self,
        interaction: discord.Interaction,
        target_channel: discord.TextChannel,
        guild_name: str,
        status: str,
        date: str,
        hire_time: str,
        start_time: str,
        server: str,
        path: str,
        boss_level: str,
        host: str,
        extra_hosts: str = "",
        slots: int = 25,
        remaining: int | None = None,
        notes: str = ""
    ):
        raids = _load_json(RAIDS_FILE, {})

        if remaining is None:
            remaining = slots

        all_hosts = [
            h.strip()
            for h in (host + "," + extra_hosts).split(",")
            if h.strip()
        ]

        raid = {
            "guild_name": guild_name,
            "status": _status_to_internal(status),
            "date": date,
            "hire_time": hire_time,
            "start_time": start_time,
            "hire_ts": _ts(date, hire_time),
            "start_ts": _ts(date, start_time),
            "server": server,
            "path": path,
            "boss_level": boss_level,
            "hosts": all_hosts,
            "slots": slots,
            "remaining": remaining,
            "notes": notes,
            "channels": [target_channel.id],
        }

        # публікуємо ембед
        msg = await target_channel.send(
            embed=_build_embed(self.bot, raid)
        )

        # записуємо в raids.json
        raids[str(msg.id)] = raid
        _save_json(RAIDS_FILE, raids)

        await interaction.response.send_message(
            f"✅ Рейд створено в {target_channel.mention}",
            ephemeral=True
        )

    # ---- /raid_edit ----
    @app_commands.command(
        name="raid_edit",
        description="✏️ Редагувати існуючий рейд"
    )
    async def raid_edit(
        self,
        interaction: discord.Interaction,
        message_id: str,
        field: str,
        new_value: str
    ):
        raids = _load_json(RAIDS_FILE, {})
        raid = raids.get(message_id)

        if not raid:
            await interaction.response.send_message(
                "❌ Рейд не знайдено.",
                ephemeral=True
            )
            return

        old_value = raid.get(field, "—")
        raid[field] = new_value

        # якщо ми редагували час/дату — оновити hire_ts / start_ts
        if field in ("date", "hire_time", "start_time"):
            raid["hire_ts"] = _ts(
                raid.get("date"),
                raid.get("hire_time")
            )
            raid["start_ts"] = _ts(
                raid.get("date"),
                raid.get("start_time")
            )

        raids[message_id] = raid
        _save_json(RAIDS_FILE, raids)

        await _edit_embed_message(self.bot, message_id, raid)

        await interaction.response.send_message(
            f"✅ `{field}` оновлено: `{old_value}` → `{new_value}`",
            ephemeral=True
        )

    # ---- /raid_slots ----
    @app_commands.command(
        name="raid_slots",
        description="📦 Змінити кількість вільних слотів"
    )
    async def raid_slots(
        self,
        interaction: discord.Interaction,
        message_id: str,
        change: int
    ):
        raids = _load_json(RAIDS_FILE, {})
        raid = raids.get(message_id)

        if not raid:
            await interaction.response.send_message(
                "❌ Рейд не знайдено.",
                ephemeral=True
            )
            return

        total = int(raid.get("slots", 0))
        remaining_before = int(raid.get("remaining", total))

        new_remaining = remaining_before + change
        if new_remaining < 0:
            new_remaining = 0
        if new_remaining > total:
            new_remaining = total

        raid["remaining"] = new_remaining

        # якщо місць більше нема — автоматично закриваємо
        raid["status"] = "closed" if new_remaining == 0 else "open"

        raids[message_id] = raid
        _save_json(RAIDS_FILE, raids)

        await _edit_embed_message(self.bot, message_id, raid)

        await interaction.response.send_message(
            f"📦 Оновлено слоти: {change:+}\n"
            f"Було: {remaining_before} → Стало: {new_remaining}",
            ephemeral=True
        )


# ---- setup ----
async def setup(bot: commands.Bot):
    await bot.add_cog(RaidCog(bot))