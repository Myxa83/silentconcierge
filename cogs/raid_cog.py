# -*- coding: utf-8 -*-
# raid_cog.py v6.9 final — SilentCove RaidCog
#
# Команди:
#   /raid_test     — прев’ю рейду без запису
#   /raid_create   — публікація рейду в канал і запис у raids.json
#   /raid_edit     — змінити будь-яке поле вже створеного рейду
#   /raid_slots    — +/- вільні слоти
#
# Автоматично:
#   - підтягує servers / paths / notes / boss_levels / hosts з data/*.json
#   - за 10 хв до старту ставить статус ЗАЧИНЕНО і оновлює ембед
#   - після дати рейду видаляє повідомлення і чистить raids.json
#   - оновлює підказки кожні 30с (без рестарту)
#
# Очікувані JSONи в ./data :
#   servers.json        -> ["Kamasylvia5", "Serendia3", ...]
#   paths.json          -> { "double":{"label": "...", "route": "..."}, "single":{...} }
#   notes.json          -> ["Можу бути AFK...", "Якщо забронювали місце — приходьте вчасно", ...]
#   boss_levels.json    -> ["1 рівня","2 рівня","3 рівня"]
#   hosts.json          -> ["Myxa","Sasoriza","Adrian","Turtle", ...]
#   raids.json          -> { "<message_id>": { raid data ... } }
#
# Важливо:
#  - guild_name: "𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲", "𝗥𝖚𝗆𝖻𝗅𝗂𝗇𝗀 𝗖𝗼𝘃𝗲", "𝗦𝗲𝘅𝘆 𝗖𝗮𝘃𝗲"
#  - status вводимо будь-яким написанням "ВІДКРИТО"/"Відкрито" тощо -> бот трактує як open
#  - часи hire_time / start_time вводяться по локальному часу модератора,
#    але в ембеді всі глядачі бачать `<t:...:t>` у своєму локальному часі.


import discord
from discord import app_commands
from discord.ext import commands, tasks
from pathlib import Path
import json
import datetime
from zoneinfo import ZoneInfo


# ───────────── CONFIG & UTILS ─────────────

COLOR_OPEN = 0x05B2B4        # бірюзовий
COLOR_CLOSED = 0xFF1E1E      # яскраво червоний

IMG_OPEN = "https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/maxresdefault.jpg?raw=true"
IMG_CLOSED = "https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/2025-01-19_5614766.jpg?raw=true"

FOOTER_OPEN = "Silent Concierge by Myxa | Найм активний"
FOOTER_CLOSED = "Silent Concierge by Myxa | Ще побачимось наступного найму!"

DATA_DIR = Path().resolve() / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

RAIDS_FILE        = DATA_DIR / "raids.json"
SERVERS_FILE      = DATA_DIR / "servers.json"
PATHS_FILE        = DATA_DIR / "paths.json"
NOTES_FILE        = DATA_DIR / "notes.json"
BOSS_LEVELS_FILE  = DATA_DIR / "boss_levels.json"
HOSTS_FILE        = DATA_DIR / "hosts.json"

DEFAULT_TZ = "Europe/London"   # тимчасово одна зона для всіх


def _load_json(path: Path, default):
    """Безпечно читає json."""
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: Path, data):
    """Пише json красиво."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _status_to_internal(s: str) -> str:
    """
    Будь-який варіант "відкрито" -> "open",
    все інше -> "closed".
    """
    if not s:
        return "closed"
    low = s.lower()
    if "відк" in low:
        return "open"
    return "closed"


def _ts(date_str: str, time_str: str, tz: str = DEFAULT_TZ) -> int | None:
    """
    date_str: "24.10.2025"
    time_str: "15:00"
    -> unix timestamp в заданому TZ
    """
    try:
        d, m, y = map(int, date_str.split("."))
        h, mi = map(int, time_str.split(":"))
        dt = datetime.datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz))
        return int(dt.timestamp())
    except Exception:
        return None


def _ansi_hosts(names: list[str]) -> str:
    """
    Повертає ANSI-блок із хостами червоним жирним.
    Це вставляється в description ембеда, і Discord рендерить.
    """
    if not names:
        return ""
    body = "".join([f"\u001b[1;31m{n}\u001b[0m " for n in names]).strip()
    return f"```ansi\n{body}\n```"


def _build_description(status_is_open: bool, hosts: list[str]) -> str:
    status_block = (
        "\u001b[1;32mВІДКРИТО\u001b[0m"
        if status_is_open else
        "\u001b[1;31mЗАЧИНЕНО\u001b[0m"
    )
    # перша ANSI секція лише зі статусом
    desc = f"```ansi\n{status_block}\n```"
    # друга ANSI секція — хости
    desc += _ansi_hosts(hosts)
    return desc


def _build_embed(bot: commands.Bot, raid: dict) -> discord.Embed:
    """
    Створює Embed з усіма блоками.
    """
    open_status = (raid.get("status") == "open")

    color = COLOR_OPEN if open_status else COLOR_CLOSED
    image = IMG_OPEN if open_status else IMG_CLOSED
    footer_text = FOOTER_OPEN if open_status else FOOTER_CLOSED

    # description = статус ANSI + хости ANSI
    hosts_list = raid.get("hosts", [])
    description = _build_description(open_status, hosts_list)

    # заголовок
    guild_name = raid.get("guild_name", "𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲")
    title = f"📅 Гільдійні боси з {guild_name}"

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
    )

    # якщо відкрите — показуємо деталі
    if open_status:
        hire_ts = raid.get("hire_ts")
        start_ts = raid.get("start_ts")
        hire_line = f"<t:{hire_ts}:t>" if hire_ts else raid.get("hire_time", "?")
        start_line = f"<t:{start_ts}:t>" if start_ts else raid.get("start_time", "?")

        embed.add_field(
            name="⏰ Найм:",
            value=hire_line,
            inline=True
        )
        embed.add_field(
            name="🚀 Старт:",
            value=start_line,
            inline=True
        )

        embed.add_field(
            name="🌴 Сервер:",
            value=f"{raid.get('server','?')} *(уточніть в ПМ)*",
            inline=False
        )

        # нерозривні пробіли, щоб не ламався "CTG Футурум"
        path_text = (raid.get("path","—") or "—").replace(" ", "\u00A0")
        embed.add_field(
            name="🗺️ Шлях:",
            value=path_text,
            inline=False
        )

        embed.add_field(
            name="🐙 Боси:",
            value=raid.get("boss_level","—"),
            inline=True
        )

        embed.add_field(
            name="📦 Слотів | 📥 Залишилось:",
            value=f"{raid.get('slots',0)} | {raid.get('remaining',0)}",
            inline=True
        )

        embed.add_field(
            name="📌 Примітка:",
            value=raid.get("notes") or "—",
            inline=False
        )

    embed.set_image(url=image)

    if bot.user:
        embed.set_footer(
            text=footer_text,
            icon_url=bot.user.display_avatar.url
        )
    else:
        embed.set_footer(text=footer_text)

    return embed


async def _edit_embed_message(bot: commands.Bot, msg_id: str, raid: dict):
    """
    Оновлює вже існуючий ембед у кожному каналі з raid["channels"].
    """
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


def _recalc_ts_if_needed(raid: dict):
    """
    Порахувати hire_ts / start_ts, якщо є date / hire_time / start_time.
    """
    date_val = raid.get("date")
    hire_val = raid.get("hire_time")
    start_val = raid.get("start_time")

    if date_val and hire_val:
        raid["hire_ts"] = _ts(date_val, hire_val, DEFAULT_TZ)
    if date_val and start_val:
        raid["start_ts"] = _ts(date_val, start_val, DEFAULT_TZ)


# ───────────── RAID COG ─────────────

class RaidCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Кешовані дані для автопідказок
        self.servers = _load_json(SERVERS_FILE, [])
        self.paths   = _load_json(PATHS_FILE, {})
        self.notes   = _load_json(NOTES_FILE, [])
        self.boss_lv = _load_json(BOSS_LEVELS_FILE, [])
        self.hosts   = _load_json(HOSTS_FILE, [])

        # Автооновлення цих json
        self._autorefresh.start()

        # Автозакриття/автовидалення
        self._check_raids.start()
        self._cleanup_old_raids.start()

    # ───────── background tasks ─────────

    @tasks.loop(seconds=30)
    async def _autorefresh(self):
        """
        Кожні 30 секунд перечитує servers.json, paths.json, notes.json,
        boss_levels.json, hosts.json — без перезапуску бота.
        """
        self.servers = _load_json(SERVERS_FILE, [])
        self.paths   = _load_json(PATHS_FILE, {})
        self.notes   = _load_json(NOTES_FILE, [])
        self.boss_lv = _load_json(BOSS_LEVELS_FILE, [])
        self.hosts   = _load_json(HOSTS_FILE, [])

    @_autorefresh.before_loop
    async def _before_autorefresh(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def _check_raids(self):
        """
        Кожну хвилину:
        - якщо до старту <10 хв і статус ще open -> закриваємо
        - ембед оновлюється
        - raids.json зберігається
        """
        raids = _load_json(RAIDS_FILE, {})
        if not raids:
            return

        now = datetime.datetime.now(datetime.timezone.utc).timestamp()
        changed = False

        for mid, raid in list(raids.items()):
            start_ts = raid.get("start_ts")
            if (
                start_ts
                and raid.get("status") == "open"
                and (start_ts - now) <= 600
            ):
                raid["status"] = "closed"
                await _edit_embed_message(self.bot, mid, raid)
                changed = True

        if changed:
            _save_json(RAIDS_FILE, raids)

    @_check_raids.before_loop
    async def _before_check_raids(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def _cleanup_old_raids(self):
        """
        Кожні 30 хвилин:
        - Якщо дата рейду вже у минулому дні -> видаляємо повідомлення + чистимо raids.json
        """
        raids = _load_json(RAIDS_FILE, {})
        if not raids:
            return

        now_local = datetime.datetime.now()
        today = now_local.date()
        changed = False

        for mid, raid in list(raids.items()):
            date_str = raid.get("date")
            if not date_str:
                continue
            try:
                d, m, y = map(int, date_str.split("."))
                raid_day = datetime.date(y, m, d)
            except Exception:
                continue

            if raid_day < today:
                # видалити повідомлення з усіх каналів raid["channels"]
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

    @_cleanup_old_raids.before_loop
    async def _before_cleanup_old_raids(self):
        await self.bot.wait_until_ready()

    # ───────── AUTOCOMPLETE SOURCES ─────────

    async def ac_guild(self, _: discord.Interaction, current: str):
        guilds = [
            "𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
            "𝗥𝖚𝗆𝖻𝗅𝗂𝗇𝗀 𝗖𝗼𝘃𝗲",
            "𝗦𝗲𝘅𝘆 𝗖𝗮𝘃𝗲",
        ]
        cur = current.lower()
        return [
            app_commands.Choice(name=g, value=g)
            for g in guilds
            if cur in g.lower()
        ][:25]

    async def ac_server(self, _: discord.Interaction, current: str):
        cur = current.lower()
        return [
            app_commands.Choice(name=s, value=s)
            for s in self.servers
            if cur in s.lower()
        ][:25]

    async def ac_path(self, _: discord.Interaction, current: str):
        # показуємо короткий label, повертаємо повний route
        out = []
        cur = current.lower()
        for node in self.paths.values():
            label = node.get("label", "")
            route = node.get("route", "")
            if cur in label.lower():
                out.append(app_commands.Choice(name=label, value=route))
        return out[:25]

    async def ac_note(self, _: discord.Interaction, current: str):
        cur = current.lower()
        return [
            app_commands.Choice(name=n, value=n)
            for n in self.notes
            if cur in n.lower()
        ][:25]

    async def ac_boss(self, _: discord.Interaction, current: str):
        cur = current.lower()
        return [
            app_commands.Choice(name=b, value=b)
            for b in self.boss_lv
            if cur in b.lower()
        ][:25]

    async def ac_host(self, _: discord.Interaction, current: str):
        # пропонуємо зі списку hosts.json
        cur = current.lower()
        return [
            app_commands.Choice(name=h, value=h)
            for h in self.hosts
            if cur in h.lower()
        ][:25]

    # ───────── /raid_test ─────────
    @app_commands.command(
        name="raid_test",
        description="Попередній перегляд рейду (ніде не записується)"
    )
    @app_commands.autocomplete(
        guild_name=ac_guild,
        server=ac_server,
        path=ac_path,
        notes=ac_note,
        boss_level=ac_boss,
        host=ac_host,
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
        remaining: int = 25,
        notes: str = "",
    ):
        # Збираємо хостів
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
            "hire_ts": _ts(date, hire_time, DEFAULT_TZ),
            "start_ts": _ts(date, start_time, DEFAULT_TZ),
            "server": server,
            "path": path,
            "boss_level": boss_level,
            "hosts": all_hosts,
            "slots": slots,
            "remaining": remaining,
            "notes": notes,
            "channels": [],  # прев'ю ніде не публікуємо
        }

        embed = _build_embed(self.bot, raid)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ───────── /raid_create ─────────
    @app_commands.command(
        name="raid_create",
        description="⚓ Створити реальне оголошення рейду в каналі"
    )
    @app_commands.autocomplete(
        guild_name=ac_guild,
        server=ac_server,
        path=ac_path,
        notes=ac_note,
        boss_level=ac_boss,
        host=ac_host,
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
        remaining: int = 25,
        notes: str = "",
    ):
        raids = _load_json(RAIDS_FILE, {})

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
            "hire_ts": _ts(date, hire_time, DEFAULT_TZ),
            "start_ts": _ts(date, start_time, DEFAULT_TZ),
            "server": server,
            "path": path,
            "boss_level": boss_level,
            "hosts": all_hosts,
            "slots": slots,
            "remaining": remaining,
            "notes": notes,
            "channels": [target_channel.id],
        }

        embed = _build_embed(self.bot, raid)
        msg = await target_channel.send(embed=embed)

        raids[str(msg.id)] = raid
        _save_json(RAIDS_FILE, raids)

        await interaction.response.send_message(
            f"✅ Рейд створено в {target_channel.mention}",
            ephemeral=True
        )

    # ───────── /raid_edit ─────────
    @app_commands.command(
        name="raid_edit",
        description="✏️ Редагувати існуючий рейд за message_id"
    )
    async def raid_edit(
        self,
        interaction: discord.Interaction,
        message_id: str,
        field: str,
        new_value: str,
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

        # якщо редагували часи або дату — перерахуємо hire_ts / start_ts
        if field in ("date", "hire_time", "start_time"):
            _recalc_ts_if_needed(raid)

        raids[message_id] = raid
        _save_json(RAIDS_FILE, raids)

        await _edit_embed_message(self.bot, message_id, raid)

        await interaction.response.send_message(
            f"✅ `{field}` оновлено: `{old_value}` → `{new_value}`",
            ephemeral=True
        )

    # ───────── /raid_slots ─────────
    @app_commands.command(
        name="raid_slots",
        description="📦 Змінити кількість вільних слотів (додати/відняти)"
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
        raid["status"] = "closed" if new_remaining == 0 else "open"

        raids[message_id] = raid
        _save_json(RAIDS_FILE, raids)

        await _edit_embed_message(self.bot, message_id, raid)

        await interaction.response.send_message(
            f"📦 Оновлено слоти: {change:+}\n"
            f"Було: {remaining_before} → Стало: {new_remaining}",
            ephemeral=True
        )


# ───────────── setup ─────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(RaidCog(bot))
