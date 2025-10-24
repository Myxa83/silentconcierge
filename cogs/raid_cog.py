# -*- coding: utf-8 -*-
import json, datetime, re
from pathlib import Path
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction

# ---------------- CONFIG ----------------
DATA_PATH = Path("data/raids.json")
TIMEZONE_FILE = Path("config/timezones.json")
MAIN_CHANNEL_ID = 1324986848866599004
TEST_CHANNEL_ID = 1370522199873814528
DEBUG = True

# ---------------- MEDIA ----------------
OPEN_BG = "https://github.com/Myxa83/silentconcierge/blob/main/assets/backgrounds/maxresdefault.jpg?raw=true"
CLOSED_BG = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/2025-01-19_5614766.jpg"
ANCHOR_GIF = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/Ancer.gif"

# ---------------- COLORS ----------------
COLOR_OPEN = discord.Color.from_str("#05B2B4")
COLOR_CLOSED = discord.Color.from_str("#FF0000")

# ---------------- EMOJIS ----------------
EMOJI_GUILD_BOSS = "<:guildboss:1376430317270995024>"

# ---------------- HELPERS ----------------
def load_json(path: Path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_timezone_for_user(user_id: int) -> str:
    """Читає TZ користувача з config/timezones.json; якщо нема — London."""
    data = load_json(TIMEZONE_FILE)
    return data.get(str(user_id), "Europe/London")

def to_unix_timestamp(date_str: str, time_str: str, tz_name: str) -> int | None:
    """date: DD.MM.YYYY  time: HH:MM  -> unix у вказаній TZ"""
    try:
        d, m, y = map(int, date_str.split("."))
        h, mi = map(int, time_str.split(":"))
        dt = datetime.datetime(y, m, d, h, mi, tzinfo=ZoneInfo(tz_name))
        return int(dt.timestamp())
    except Exception:
        return None

# ---------------- BUILD EMBED ----------------
def _center_title(txt: str) -> str:
    pad = " " * 8  # U+2006 figure space для псевдо-центру
    return f"{pad}{txt}{pad}"

def build_embed(raid: dict, bot: commands.Bot | None = None) -> discord.Embed:
    """Рендерить ембед по правилам: ANSI-статус, фони, футер, відступи, теги часу."""
    status = raid.get("status", "open")
    guild_title = "Гільдійні боси з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲"
    title = f"{EMOJI_GUILD_BOSS} **{_center_title(guild_title)}**"

    # timestamps (кожен бачить локально)
    hire_ts = raid.get("hire_ts")
    start_ts = raid.get("start_ts")
    hire_line = f"🕓 **Найм:** <t:{hire_ts}:t>" if hire_ts else f"🕓 **Найм:** {raid.get('hire','?')}"
    start_line = f"🚀 **Старт:** <t:{start_ts}:t>" if start_ts else f"🚀 **Старт:** {raid.get('start','?')}"

    # ---- ВІДКРИТО ----
    if status == "open":
        color = COLOR_OPEN
        image = OPEN_BG
        status_text = "```ansi\n\u001b[1;32mВІДКРИТО\u001b[0m```"
        footer_text = "Silent Concierge by Myxa | Найм активний"

        embed = discord.Embed(title=title, color=color)
        embed.description = f"📅 **Дата:** {raid.get('date', '??.??.????')}\n{status_text}"

        # Хости – окремими полями (щоб копіювались по одному)
        hosts = [h.strip() for h in raid.get("host", "").split(",") if h.strip()]
        if hosts:
            embed.add_field(name="💬 Кому шепотіти:", value="\u200b", inline=False)
            for h in hosts:
                embed.add_field(
                    name=f"```ansi\n\u001b[1;31m{h}\u001b[0m```",
                    value="\u200b",
                    inline=False
                )
        else:
            embed.add_field(name="💬 Кому шепотіти:", value="```ansi\n\u001b[1;31m???\u001b[0m```", inline=False)

        # Основні блоки з «диханням»
        server = raid.get("server", "Serendia 4")
        server_note = raid.get("server_note", "(уточнити в ПМ)")
        embed.add_field(name="\u200b", value=f"{hire_line}\n\n{start_line}", inline=False)
        embed.add_field(name="\u200b", value=f"🏝️ **Сервер:** {server} _{server_note}_", inline=False)
        embed.add_field(name="\u200b", value=f"🗺️ **Шлях:** {raid.get('path','-')}", inline=False)
        embed.add_field(name="\u200b", value=f"🐙 **Боси:** {raid.get('boss_level','3')}", inline=False)
        embed.add_field(
            name="\u200b",
            value=f"📦 **Слотів:** {raid.get('slots',0)}  |  📥 **Залишилось:** {raid.get('remaining',0)}",
            inline=False
        )

        if raid.get("notes"):
            embed.add_field(name="📌 **Примітка**", value=raid["notes"], inline=False)

    # ---- ЗАЧИНЕНО ----
    else:
        color = COLOR_CLOSED
        image = CLOSED_BG
        footer_text = "Silent Concierge by Myxa | Ще побачимось наступного найму!"
        status_text = "```ansi\n\u001b[1;31mЗАЧИНЕНО\u001b[0m```"
        embed = discord.Embed(title=title, color=color, description=status_text)

    embed.set_image(url=image)
    embed.set_thumbnail(url=ANCHOR_GIF)
    if bot and bot.user:
        embed.set_footer(text=footer_text, icon_url=bot.user.display_avatar.url)
    else:
        embed.set_footer(text=footer_text)
    return embed

async def update_embed_message(bot, msg_id: str, raid: dict):
    # шукаємо в основному або в тест-каналі
    for ch_id in (MAIN_CHANNEL_ID, TEST_CHANNEL_ID):
        channel = bot.get_channel(ch_id)
        if not channel:
            continue
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=build_embed(raid, bot))
            return
        except Exception:
            continue

# ---------------- COG ----------------
class RaidCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.fix_old_json()
        self.check_raids.start()
        self.cleanup_old_raids.start()
        self.test_raids: dict[str, dict] = {}  # message_id -> raid (для /raid_test)

    def cog_unload(self):
        self.check_raids.cancel()
        self.cleanup_old_raids.cancel()

    # ---- міграція старих json
    def fix_old_json(self):
        raids = load_json(DATA_PATH)
        changed = False
        for _, raid in raids.items():
            if "is_closed" in raid and "status" not in raid:
                raid["status"] = "closed" if raid["is_closed"] else "open"; changed = True
            raid.setdefault("status", "open")
            raid.setdefault("remaining", raid.get("slots", 0))
            raid.setdefault("slots", 0)
            raid.setdefault("date", datetime.datetime.now().strftime("%d.%m.%Y"))
        if changed:
            save_json(DATA_PATH, raids)

    # ----------- AUTO CHECK -----------
    @tasks.loop(minutes=1)
    async def check_raids(self):
        raids = load_json(DATA_PATH)
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        changed_any = False
        for msg_id, raid in list(raids.items()):
            start_ts = raid.get("start_ts")
            status = raid.get("status", "open")
            remaining = raid.get("remaining", raid.get("slots", 0))
            if isinstance(start_ts, int) and status == "open" and start_ts - now <= 600:
                raid["status"] = "closed"; changed_any = True
            if remaining <= 0 and status != "closed":
                raid["status"] = "closed"; changed_any = True
            if changed_any:
                await update_embed_message(self.bot, msg_id, raid)
        if changed_any:
            save_json(DATA_PATH, raids)

    @check_raids.before_loop
    async def before_check_raids(self):
        await self.bot.wait_until_ready()

    # ----------- CLEANUP -----------
    @tasks.loop(minutes=5)
    async def cleanup_old_raids(self):
        now = datetime.datetime.now(tz=ZoneInfo("Europe/London"))
        if now.hour == 0 and now.minute < 5:
            raids = load_json(DATA_PATH)
            for msg_id in list(raids.keys()):
                for ch_id in (MAIN_CHANNEL_ID, TEST_CHANNEL_ID):
                    try:
                        channel = self.bot.get_channel(ch_id)
                        if channel:
                            msg = await channel.fetch_message(int(msg_id))
                            await msg.delete()
                    except Exception:
                        pass
                raids.pop(msg_id, None)
            save_json(DATA_PATH, raids)
            self.test_raids.clear()

    @cleanup_old_raids.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ----------- RAID SLOTS (+ додає / - віднімає) -----------
    @app_commands.command(name="raid_slots", description="📦 Змінити кількість вільних слотів (додати або відняти)")
    @app_commands.describe(
        message_id="🆔 ID повідомлення рейду (тест або реальний)",
        change="🔢 + додає, - віднімає (напр.: +2 або -3)"
    )
    async def raid_slots(self, interaction: Interaction, message_id: str, change: int):
        raids = load_json(DATA_PATH)
        target = raids.get(message_id) or self.test_raids.get(message_id)
        if not target:
            return await interaction.response.send_message("❌ Рейд не знайдено.", ephemeral=True)

        total = int(target.get("slots", 0))
        remaining = int(target.get("remaining", total))
        new_remaining = max(0, min(total, remaining + change))
        target["remaining"] = new_remaining
        target["status"] = "closed" if new_remaining == 0 else "open"

        if message_id in raids:
            raids[message_id] = target; save_json(DATA_PATH, raids)
        else:
            self.test_raids[message_id] = target

        await update_embed_message(self.bot, message_id, target)
        arrow = "➕" if change > 0 else "➖"
        await interaction.response.send_message(
            f"{arrow} Слоти змінено на {change:+}\n"
            f"📦 Всього: **{total}** | 📥 Залишилось: **{new_remaining}**",
            ephemeral=True
        )

    # ----------- RAID EDIT -----------
    @app_commands.command(name="raid_edit", description="✏️ Виправити інформацію у вже створеному рейді (тест/реальний)")
    @app_commands.describe(
        message_id="🆔 ID повідомлення",
        field="🔧 Поле для зміни",
        new_value="🪶 Нове значення"
    )
    @app_commands.choices(field=[
        app_commands.Choice(name="🏝️ Сервер", value="server"),
        app_commands.Choice(name="📅 Дата рейду", value="date"),
        app_commands.Choice(name="🕓 Час найму", value="hire"),
        app_commands.Choice(name="🚀 Час старту", value="start"),
        app_commands.Choice(name="💬 Хост(и)", value="host"),
        app_commands.Choice(name="📌 Примітка", value="notes"),
        app_commands.Choice(name="🗺️ Шлях", value="path"),
        app_commands.Choice(name="🐙 Рівень босів", value="boss_level"),
        app_commands.Choice(name="📦 Кількість слотів", value="slots"),
        app_commands.Choice(name="📝 Примітка для сервера", value="server_note"),
        app_commands.Choice(name="🟢/🔴 Статус", value="status"),
    ])
    async def raid_edit(self, interaction: Interaction, message_id: str, field: app_commands.Choice[str], new_value: str):
        raids = load_json(DATA_PATH)
        target = raids.get(message_id) or self.test_raids.get(message_id)
        if not target:
            return await interaction.response.send_message("❌ Рейд не знайдено.", ephemeral=True)

        old_value = target.get(field.value, "—")
        target[field.value] = new_value

        # якщо правили час/дату – оновити timestamps
        if field.value in {"date", "hire", "start"}:
            tz = get_timezone_for_user(interaction.user.id)
            hire_ts = to_unix_timestamp(target.get("date",""), target.get("hire",""), tz)
            start_ts = to_unix_timestamp(target.get("date",""), target.get("start",""), tz)
            if hire_ts: target["hire_ts"] = hire_ts
            if start_ts: target["start_ts"] = start_ts

        if message_id in raids:
            raids[message_id] = target; save_json(DATA_PATH, raids)
        else:
            self.test_raids[message_id] = target

        await update_embed_message(self.bot, message_id, target)
        await interaction.response.send_message(
            f"✅ **{field.name}**: `{old_value}` → `{new_value}`", ephemeral=True
        )

    # ----------- RAID TEST (slash, з виборами; працює як справжній, але без запису) -----------
    @app_commands.command(name="raid_test", description="🧪 Попередній перегляд рейду (без запису) з виборами + локальний час")
    @app_commands.describe(
        date="📅 Дата (ДД.ММ.РРРР)",
        hire="🕓 Час найму (HH:MM, локальний)",
        start="🚀 Час старту (HH:MM, локальний)",
        host="💬 Хости через кому (Myxa, Sasoriza)",
        slots="📦 Всього слотів",
        remaining="📥 Залишилось (початково)",
        notes="📌 Примітка (необов'язково)"
    )
    @app_commands.choices(
        status=[app_commands.Choice(name="Відкрито", value="open"),
                app_commands.Choice(name="Зачинено", value="closed")],
        server=[app_commands.Choice(name=s, value=s) for s in [
            "EU_Kamasylvia1","EU_Kamasylvia2","EU_Kamasylvia3","EU_Kamasylvia4","EU_Kamasylvia5","EU_Kamasylvia6",
            "EU_Serendia1","EU_Serendia2","EU_Serendia3","EU_Serendia4","EU_Serendia5","EU_Serendia6",
            "EU_Balenos1","EU_Balenos2","EU_Calpheon1","EU_Calpheon5","EU_Valencia2","EU_Mediah1"
        ]],
        path=[app_commands.Choice(name=p, value=p) for p in [
            "Хан→Бруд→CTG","Бруд→Феррід→CTG","CTG→Футурума","LoML→CTG","Хан-Мадстер"
        ]],
        boss_level=[app_commands.Choice(name=b, value=b) for b in ["1","2","3"]]
    )
    async def raid_test(
        self,
        interaction: Interaction,
        status: app_commands.Choice[str],
        date: str,
        hire: str,
        start: str,
        server: app_commands.Choice[str],
        path: app_commands.Choice[str],
        boss_level: app_commands.Choice[str],
        host: str,
        slots: int,
        remaining: int,
        notes: str | None = None
    ):
        """Створює тестовий ембед у TEST_CHANNEL_ID. Все редагується /raid_edit, слоти — /raid_slots."""
        tz = get_timezone_for_user(interaction.user.id)
        hire_ts = to_unix_timestamp(date, hire, tz)
        start_ts = to_unix_timestamp(date, start, tz)

        raid = {
            "status": status.value,
            "date": date,
            "hire": hire, "start": start,
            "hire_ts": hire_ts, "start_ts": start_ts,
            "server": server.value, "server_note": "(уточнити в ПМ)",
            "path": path.value,
            "boss_level": boss_level.value,
            "host": host,
            "slots": slots,
            "remaining": remaining,
            "notes": notes or ""
        }

        channel = self.bot.get_channel(TEST_CHANNEL_ID) or interaction.channel
        embed = build_embed(raid, self.bot)
        msg = await channel.send(embed=embed)
        self.test_raids[str(msg.id)] = raid
        await interaction.response.send_message(f"🧪 Тестовий рейд створено: `{msg.id}`", ephemeral=True)

    # ----------- RAID CREATE (як тест, але обираємо канал і пишемо в JSON) -----------
    @app_commands.command(name="raid_create", description="⚓ Створити реальний рейд та опублікувати у вибраний канал")
    @app_commands.describe(
        target_channel="📣 Куди публікувати ембед",
        date="📅 Дата (ДД.ММ.РРРР)",
        hire="🕓 Найм (HH:MM, локальний)",
        start="🚀 Старт (HH:MM, локальний)",
        host="💬 Хости (через кому)",
        slots="📦 Всього слотів",
        remaining="📥 Залишилось (початково)",
        notes="📌 Примітка (необов'язково)"
    )
    @app_commands.choices(
        status=[app_commands.Choice(name="Відкрито", value="open"),
                app_commands.Choice(name="Зачинено", value="closed")],
        server=[app_commands.Choice(name=s, value=s) for s in [
            "EU_Kamasylvia1","EU_Kamasylvia2","EU_Kamasylvia3","EU_Kamasylvia4","EU_Kamasylvia5","EU_Kamasylvia6",
            "EU_Serendia1","EU_Serendia2","EU_Serendia3","EU_Serendia4","EU_Serendia5","EU_Serendia6"
        ]],
        path=[app_commands.Choice(name=p, value=p) for p in [
            "Хан→Бруд→CTG","Бруд→Феррід→CTG","CTG→Футурума","LoML→CTG","Хан-Мадстер"
        ]],
        boss_level=[app_commands.Choice(name=b, value=b) for b in ["1","2","3"]]
    )
    async def raid_create(
        self,
        interaction: Interaction,
        target_channel: discord.TextChannel,
        status: app_commands.Choice[str],
        date: str,
        hire: str,
        start: str,
        server: app_commands.Choice[str],
        path: app_commands.Choice[str],
        boss_level: app_commands.Choice[str],
        host: str,
        slots: int,
        remaining: int,
        notes: str | None = None
    ):
        tz = get_timezone_for_user(interaction.user.id)
        hire_ts = to_unix_timestamp(date, hire, tz)
        start_ts = to_unix_timestamp(date, start, tz)
        raid = {
            "status": status.value,
            "date": date,
            "hire": hire, "start": start,
            "hire_ts": hire_ts, "start_ts": start_ts,
            "server": server.value, "server_note": "(уточнити в ПМ)",
            "path": path.value,
            "boss_level": boss_level.value,
            "host": host,
            "slots": slots,
            "remaining": remaining,
            "notes": notes or ""
        }

        embed = build_embed(raid, self.bot)
        msg = await target_channel.send(embed=embed)

        raids = load_json(DATA_PATH)
        raids[str(msg.id)] = raid
        save_json(DATA_PATH, raids)

        await interaction.response.send_message(
            f"✅ Рейд опубліковано у {target_channel.mention}. ID: `{msg.id}`", ephemeral=True
        )

# ---------------- SETUP ----------------
async def setup(bot):
    await bot.add_cog(RaidCog(bot))
