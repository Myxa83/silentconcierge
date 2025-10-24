# -*- coding: utf-8 -*-
import json, datetime, os
from pathlib import Path
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction

# ---------------- PATHS / FILES ----------------
DATA_DIR = Path("data")
CONFIG_DIR = Path("config")
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

DATA_PATH = DATA_DIR / "raids.json"
TIMEZONE_FILE = CONFIG_DIR / "timezones.json"
SERVERS_FILE = DATA_DIR / "servers.json"
PATHS_FILE = DATA_DIR / "paths.json"
BOSS_FILE = DATA_DIR / "boss_levels.json"
HOSTS_FILE = DATA_DIR / "hosts.json"

# ---------------- CHANNELS ----------------
TEST_CHANNEL_ID = 1370522199873814528          # попередній перегляд
MAIN_CHANNEL_ID = 1324986848866599004          # дефолт (можна задати свій у /raid_create)

# ---------------- THEME / MEDIA ----------------
OPEN_BG    = "https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/maxresdefault.jpg?raw=true"
CLOSED_BG  = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/2025-01-19_5614766.jpg"
ANCHOR_GIF = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/Ancer.gif"

COLOR_OPEN   = discord.Color.from_str("#05B2B4")  # бірюзовий
COLOR_CLOSED = discord.Color.from_str("#FF1E1E")  # яскраво-алий

EMOJI_GUILD_BOSS = "<:guildboss:1376430317270995024>"

# ---------------- HELPERS ----------------
def load_json(path: Path, default):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_timezone_for_user(user_id: int) -> str:
    tzs = load_json(TIMEZONE_FILE, {})
    return tzs.get(str(user_id), "Europe/London")

def to_unix_timestamp(date_str: str, time_str: str, tz_name: str) -> int | None:
    # date: DD.MM.YYYY, time: HH:MM  -> unix (у вказаній TZ)
    try:
        # нормалізуємо 3:5 -> 03:05
        parts = time_str.strip().split(":")
        if len(parts) == 2:
            hh = f"{int(parts[0]):02d}"
            mm = f"{int(parts[1]):02d}"
            time_str = f"{hh}:{mm}"
        d, m, y = map(int, date_str.split("."))
        h, mi = map(int, time_str.split(":"))
        dt = datetime.datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz_name))
        return int(dt.timestamp())
    except Exception:
        return None

def _center_title(txt: str) -> str:
    pad = " " * 8  # U+2006 figure space
    return f"{pad}{txt}{pad}"

def _ansi_red_bold(txt: str) -> str:
    return f"```ansi\n\u001b[1;31m{txt}\u001b[0m```"

# ---------------- EMBED RENDER ----------------
def build_embed(raid: dict, bot: commands.Bot | None = None) -> discord.Embed:
    status     = raid.get("status", "open")
    guild_name = raid.get("guild_name", "𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲")
    title = f"{EMOJI_GUILD_BOSS} **{_center_title(f'Гільдійні боси з {guild_name}')}**"

    # час (у кожного локально через <t:…:t>)
    hire_ts  = raid.get("hire_ts")
    start_ts = raid.get("start_ts")
    hire_line  = f"🕓 **Найм:** <t:{hire_ts}:t>"  if hire_ts  else f"🕓 **Найм:** {raid.get('hire','?')}"
    start_line = f"🚀 **Старт:** <t:{start_ts}:t>" if start_ts else f"🚀 **Старт:** {raid.get('start','?')}"

    if status == "open":
        color, img, foot = COLOR_OPEN, OPEN_BG, "Silent Concierge by Myxa | Найм активний"
        embed = discord.Embed(title=title, color=color)
        embed.description = f"📅 **Дата:** {raid.get('date', '??.??.????')}\n```ansi\n\u001b[1;32mВІДКРИТО\u001b[0m```"

        # 💬 Кому шепотіти — по двоє inline в ряд, жирні червоні
        hosts = [h.strip() for h in raid.get("host", "").split(",") if h.strip()]
        embed.add_field(name="💬 Кому шепотіти:", value="\u200b", inline=False)
        if not hosts:
            hosts = ["???"]
        # рендеримо попарно
        for i in range(0, len(hosts), 2):
            left  = _ansi_red_bold(hosts[i])
            right = _ansi_red_bold(hosts[i+1]) if i+1 < len(hosts) else "\u200b"
            embed.add_field(name=left,  value="\u200b", inline=True)
            embed.add_field(name=right, value="\u200b", inline=True)

        # основні блоки з «диханням»
        server = raid.get("server", "Kamasylvia4")
        embed.add_field(name="\u200b", value=f"{hire_line}\n\n{start_line}", inline=False)
        embed.add_field(name="\u200b", value=f"🏝️ **Сервер:** {server} _(уточнити в ПМ)_", inline=False)
        embed.add_field(name="\u200b", value=f"🗺️ **Шлях:** {raid.get('path','-')}", inline=False)
        embed.add_field(name="\u200b", value=f"🐙 **Боси:** {raid.get('boss_level','3 рівня')}", inline=False)
        embed.add_field(
            name="\u200b",
            value=f"📦 **Слотів:** {raid.get('slots',0)}  |  📥 **Залишилось:** {raid.get('remaining',0)}",
            inline=False
        )
        if raid.get("notes"):
            embed.add_field(name="📌 **Примітка**", value=raid["notes"], inline=False)
    else:
        color, img, foot = COLOR_CLOSED, CLOSED_BG, "Silent Concierge by Myxa | Ще побачимось наступного найму!"
        embed = discord.Embed(
            title=title,
            color=color,
            description="```ansi\n\u001b[1;31mЗАЧИНЕНО\u001b[0m```"
        )

    embed.set_image(url=img)
    embed.set_thumbnail(url=ANCHOR_GIF)
    if bot and bot.user:
        embed.set_footer(text=foot, icon_url=bot.user.display_avatar.url)
    else:
        embed.set_footer(text=foot)
    return embed

async def update_embed_message(bot, msg_id: str, raid: dict):
    # шукаємо в основному та тестовому
    for cid in (MAIN_CHANNEL_ID, TEST_CHANNEL_ID):
        ch = bot.get_channel(cid)
        if not ch:
            continue
        try:
            msg = await ch.fetch_message(int(msg_id))
            await msg.edit(embed=build_embed(raid, bot))
            return
        except Exception:
            continue

# ---------------- COG ----------------
class RaidCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # кеш для autocomplete
        self._ac = {"servers": [], "paths": [], "boss_levels": [], "hosts": []}
        self._mtimes = {}

        # тестові рейди (message_id -> dict)
        self.test_raids: dict[str, dict] = {}

        # старт циклів
        self.refresh_autocomplete_data()
        self.autocomplete_refresher.start()
        self.check_raids.start()

    def cog_unload(self):
        self.autocomplete_refresher.cancel()
        self.check_raids.cancel()

    # ---------- JSON live refresh (кожні 30с) ----------
    @tasks.loop(seconds=30)
    async def autocomplete_refresher(self):
        self.refresh_autocomplete_data()

    def refresh_autocomplete_data(self):
        def _mtime(p: Path): return p.exists() and os.path.getmtime(p) or 0

        # servers.json
        m = _mtime(SERVERS_FILE)
        if self._mtimes.get("servers") != m:
            servers_data = load_json(SERVERS_FILE, {
                "Kamasylvia": [f"Kamasylvia{i}" for i in range(1,7)],
                "Serendia":   [f"Serendia{i}" for i in range(1,7)],
            })
            servers = []
            for _, arr in servers_data.items():
                servers.extend(arr)
            self._ac["servers"] = servers
            self._mtimes["servers"] = m

        # paths.json
        m = _mtime(PATHS_FILE)
        if self._mtimes.get("paths") != m:
            paths_data = load_json(PATHS_FILE, {
                "double": "Хан (Kama 5) → 3 хв → Хан (Кама 3) → 3 хв → Бруд → 3 хв → Феррід → CTG Футурум → 6 хв → Футурум → 4 хв → Феррід → 3 хв → Бруд",
                "single": "Хан → 3 хв → Бруд → 3 хв → Феррід → CTG Футурум",
                "custom": ""
            })
            paths_list = []
            if isinstance(paths_data, dict):
                for k in ("double", "single"):
                    if paths_data.get(k):
                        paths_list.append(paths_data[k])
            elif isinstance(paths_data, list):
                paths_list = paths_data
            self._ac["paths"] = paths_list
            self._mtimes["paths"] = m

        # boss_levels.json
        m = _mtime(BOSS_FILE)
        if self._mtimes.get("boss_levels") != m:
            boss_data = load_json(BOSS_FILE, ["1 рівня", "2 рівня", "3 рівня"])
            self._ac["boss_levels"] = boss_data
            self._mtimes["boss_levels"] = m

        # hosts.json
        m = _mtime(HOSTS_FILE)
        if self._mtimes.get("hosts") != m:
            hosts_data = load_json(HOSTS_FILE, ["Myxa", "Sasoriza", "Knufel", "Adrian", "Turtle"])
            self._ac["hosts"] = hosts_data
            self._mtimes["hosts"] = m

    @autocomplete_refresher.before_loop
    async def before_refresher(self):
        await self.bot.wait_until_ready()

    # ---------- автозакриття перед стартом ----------
    @tasks.loop(minutes=1)
    async def check_raids(self):
        raids = load_json(DATA_PATH, {})
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        changed = False
        for mid, raid in list(raids.items()):
            start_ts = raid.get("start_ts")
            if isinstance(start_ts, int) and raid.get("status") == "open" and start_ts - now <= 600:
                raid["status"] = "closed"; changed = True
                await update_embed_message(self.bot, mid, raid)
        if changed:
            save_json(DATA_PATH, raids)

    @check_raids.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # ---------- AUTOCOMPLETE ----------
    async def _ac_list(self, pool: list[str], current: str):
        cur = (current or "").lower()
        out = []
        for s in pool:
            if cur in s.lower():
                out.append(app_commands.Choice(name=s, value=s))
                if len(out) >= 25:
                    break
        return out

    async def ac_server(self, interaction: Interaction, current: str):
        return await self._ac_list(self._ac["servers"], current)

    async def ac_boss(self, interaction: Interaction, current: str):
        return await self._ac_list(self._ac["boss_levels"], current)

    async def ac_path(self, interaction: Interaction, current: str):
        return await self._ac_list(self._ac["paths"], current)

    async def ac_host(self, interaction: Interaction, current: str):
        # підтримка "через кому": добираємо останній токен
        token = current.split(",")[-1].strip() if current else ""
        pool = [h for h in self._ac["hosts"] if token.lower() in h.lower()]
        # підстановка наступного імені, зберігаючи вже введене
        out = []
        for h in pool[:25]:
            if token:
                prefix = current[:len(current) - len(token)]
                val = prefix + h
            else:
                val = h if not current else (current.rstrip() + (" " if not current.endswith((" ", ",")) else "") + h)
            out.append(app_commands.Choice(name=h, value=val))
        return out

    async def ac_field(self, interaction: Interaction, current: str):
        fields = ["guild_name","status","date","hire","start","server","path","boss_level","host","slots","remaining","notes"]
        return await self._ac_list(fields, current)

    async def ac_guild(self, interaction: Interaction, current: str):
        options = ["𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲", "𝗥𝖚𝗆𝖻𝗅𝗂𝗇𝗀 𝗖𝗼𝘃𝗲", "𝗦𝗲𝘅𝘆 𝗖𝗮𝘃𝗲"]
        return await self._ac_list(options, current)

    # ---------- /raid_test ----------
    @app_commands.command(name="raid_test", description="🧪 Попередній перегляд рейду (єдиний формат, без запису)")
    @app_commands.describe(
        guild_name="Назва гільдії (Silent / Rumbling / Sexy у бренд-шрифті)",
        status="Статус (open/closed)",
        date="Дата (ДД.ММ.РРРР), за замовчуванням — сьогодні",
        hire_time="Час найму (HH:MM), дефолт 15:00",
        start_time="Час старту (HH:MM), дефолт 17:10",
        server="Сервер (почни писати — autocomplete з servers.json)",
        path="Шлях (autocomplete з paths.json або напиши свій)",
        boss_level="Рівень босів (autocomplete)",
        host="Хости через кому (autocomplete з hosts.json)",
        slots="Всього слотів (константа)",
        remaining="Залишилось (динамічно)",
        notes="Примітка (необов'язково)"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="Відкрито", value="open"),
        app_commands.Choice(name="Зачинено", value="closed"),
    ])
    @app_commands.autocomplete(
        guild_name=ac_guild, server=ac_server, path=ac_path, boss_level=ac_boss, host=ac_host
    )
    async def raid_test(
        self,
        interaction: Interaction,
        guild_name: str = "𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
        status: app_commands.Choice[str] = None,
        date: str = None,
        hire_time: str = "15:00",
        start_time: str = "17:10",
        server: str = "Kamasylvia4",
        path: str = "",
        boss_level: str = "3 рівня",
        host: str = "Myxa, Sasoriza",
        slots: int = 25,
        remaining: int = 25,
        notes: str | None = "Краще уточнити, можу бути afk"
    ):
        s_val = status.value if isinstance(status, app_commands.Choice) else "open"
        date = date or datetime.datetime.now().strftime("%d.%m.%Y")
        tz = get_timezone_for_user(interaction.user.id)
        hire_ts  = to_unix_timestamp(date, hire_time, tz)
        start_ts = to_unix_timestamp(date, start_time, tz)

        if not path:
            path = (self._ac["paths"][0] if self._ac["paths"] else "—")

        raid = {
            "guild_name": guild_name,
            "status": s_val,
            "date": date,
            "hire": hire_time, "start": start_time,
            "hire_ts": hire_ts, "start_ts": start_ts,
            "server": server,
            "path": path,
            "boss_level": boss_level,
            "host": host,
            "slots": slots,
            "remaining": remaining,
            "notes": notes or ""
        }

        ch = self.bot.get_channel(TEST_CHANNEL_ID) or interaction.channel
        emb = build_embed(raid, self.bot)
        msg = await ch.send(embed=emb)
        self.test_raids[str(msg.id)] = raid
        await interaction.response.send_message(f"🧪 Тестовий рейд створено: `{msg.id}`", ephemeral=True)

    # ---------- /raid_create ----------
    @app_commands.command(name="raid_create", description="⚓ Створити реальний рейд (єдиний формат, з записом)")
    @app_commands.describe(
        target_channel="Куди публікувати ембед",
        guild_name="Назва гільдії (Silent / Rumbling / Sexy у бренд-шрифті)",
        status="Статус (open/closed)",
        date="Дата (ДД.ММ.РРРР), за замовчуванням — сьогодні",
        hire_time="Час найму (HH:MM), дефолт 15:00",
        start_time="Час старту (HH:MM), дефолт 17:10",
        server="Сервер (autocomplete з servers.json)",
        path="Шлях (autocomplete з paths.json або свій)",
        boss_level="Рівень босів (autocomplete)",
        host="Хости через кому (autocomplete)",
        slots="Всього слотів",
        remaining="Залишилось",
        notes="Примітка (необов'язково)"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="Відкрито", value="open"),
        app_commands.Choice(name="Зачинено", value="closed"),
    ])
    @app_commands.autocomplete(
        guild_name=ac_guild, server=ac_server, path=ac_path, boss_level=ac_boss, host=ac_host
    )
    async def raid_create(
        self,
        interaction: Interaction,
        target_channel: discord.TextChannel,
        guild_name: str = "𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
        status: app_commands.Choice[str] = None,
        date: str = None,
        hire_time: str = "15:00",
        start_time: str = "17:10",
        server: str = "Kamasylvia4",
        path: str = "",
        boss_level: str = "3 рівня",
        host: str = "Myxa, Sasoriza",
        slots: int = 25,
        remaining: int = 25,
        notes: str | None = "Краще уточнити, можу бути afk"
    ):
        s_val = status.value if isinstance(status, app_commands.Choice) else "open"
        date = date or datetime.datetime.now().strftime("%d.%m.%Y")
        tz = get_timezone_for_user(interaction.user.id)
        hire_ts  = to_unix_timestamp(date, hire_time, tz)
        start_ts = to_unix_timestamp(date, start_time, tz)

        if not path:
            path = (self._ac["paths"][0] if self._ac["paths"] else "—")

        raid = {
            "guild_name": guild_name,
            "status": s_val,
            "date": date,
            "hire": hire_time, "start": start_time,
            "hire_ts": hire_ts, "start_ts": start_ts,
            "server": server,
            "path": path,
            "boss_level": boss_level,
            "host": host,
            "slots": slots,
            "remaining": remaining,
            "notes": notes or ""
        }

        emb = build_embed(raid, self.bot)
        msg = await target_channel.send(embed=emb)
        raids = load_json(DATA_PATH, {})
        raids[str(msg.id)] = raid
        save_json(DATA_PATH, raids)
        await interaction.response.send_message(f"✅ Рейд створено в {target_channel.mention}. ID: `{msg.id}`", ephemeral=True)

    # ---------- /raid_edit ----------
    @app_commands.command(name="raid_edit", description="✏️ Виправити поле у вже створеному рейді (тест/реальний)")
    @app_commands.describe(
        message_id="ID повідомлення з ембедом",
        field="Поле для зміни (autocomplete)",
        new_value="Нове значення"
    )
    @app_commands.autocomplete(field=ac_field)
    async def raid_edit(self, interaction: Interaction, message_id: str, field: str, new_value: str):
        raids = load_json(DATA_PATH, {})
        target = raids.get(message_id) or self.test_raids.get(message_id)
        if not target:
            return await interaction.response.send_message("❌ Рейд не знайдено.", ephemeral=True)

        old_value = str(target.get(field, "—"))
        target[field] = new_value

        # оновлюємо timestamps, якщо правили дату/час
        if field in {"date","hire","start"}:
            tz = get_timezone_for_user(interaction.user.id)
            hire_ts  = to_unix_timestamp(target.get("date",""), target.get("hire",""), tz)
            start_ts = to_unix_timestamp(target.get("date",""), target.get("start",""), tz)
            if hire_ts:  target["hire_ts"]  = hire_ts
            if start_ts: target["start_ts"] = start_ts

        if message_id in raids:
            raids[message_id] = target
            save_json(DATA_PATH, raids)
        else:
            self.test_raids[message_id] = target

        await update_embed_message(self.bot, message_id, target)
        await interaction.response.send_message(
            f"✅ **{field}**: `{old_value}` → `{new_value}`",
            ephemeral=True
        )

    # ---------- /raid_slots ----------
    @app_commands.command(name="raid_slots", description="📦 Змінити кількість вільних слотів (додати/відняти)")
    @app_commands.describe(
        message_id="ID повідомлення рейду (тест або реальний)",
        change="Введи + щоб додати або - щоб відняти (напр.: +2 або -3)"
    )
    async def raid_slots(self, interaction: Interaction, message_id: str, change: int):
        raids = load_json(DATA_PATH, {})
        target = raids.get(message_id) or self.test_raids.get(message_id)
        if not target:
            return await interaction.response.send_message("❌ Рейд не знайдено.", ephemeral=True)

        total = int(target.get("slots", 0))
        remaining = int(target.get("remaining", total))
        new_remaining = max(0, min(total, remaining + change))
        target["remaining"] = new_remaining
        target["status"] = "closed" if new_remaining == 0 else "open"

        if message_id in raids:
            raids[message_id] = target
            save_json(DATA_PATH, raids)
        else:
            self.test_raids[message_id] = target

        await update_embed_message(self.bot, message_id, target)
        arrow = "➕" if change > 0 else "➖"
        await interaction.response.send_message(
            f"{arrow} Слоти змінено на {change:+}\n"
            f"📦 Всього: **{total}** | 📥 Залишилось: **{new_remaining}**",
            ephemeral=True
        )

# ---------------- SETUP ----------------
async def setup(bot):
    await bot.add_cog(RaidCog(bot))