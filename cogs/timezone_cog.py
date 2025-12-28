# -*- coding: utf-8 -*-
# cogs/timezone_cog.py
# Silent Concierge - Timezone Panel (dropdown, persistent)
#
# - /tz_post posts the panel (only roles: Свiточ, Друг)
# - Dropdown can be USED only by roles: Свiточ, Друг
# - Stores timezone in data/timezones.json
# - No footer (per request)
# - Title style like BDO: «« Title »»
# - Divider: Deff x16
# - Big bold title in description with animated trees around phrase "обери свою таймзону!"

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
from discord import app_commands

# ========================= PATHS =========================
DATA_PATH = Path("data/timezones.json")

# ========================= ROLES =========================
ROLE_SVITOCH = 1383410423704846396
ROLE_FRIEND = 1325124628330446951
ALLOWED_TZ_ROLES = {ROLE_SVITOCH, ROLE_FRIEND}

# ========================= EMOJIS / ASSETS =========================
ASL = "<a:ASL:1447205981133209773>"
RSL = "<a:RSL:1447204908494225529>"
BULLET = "<a:bulletpoint:1447549436137046099>"
DEFF = "<:Deff:1448272177848913951>"
DIVIDER = DEFF * 16

BOTTOM_IMAGE_URL = (
    "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/"
    "assets/backgrounds/PolosBir.gif"
)

# ========================= TIMEZONES =========================
# key: (label, flag_emoji, tz)
COUNTRIES: dict[str, tuple[str, str, str]] = {
    "europe": ("Europe (Berlin time)", "🇪🇺", "Europe/Berlin"),
    "united_kingdom": ("United Kingdom", "🇬🇧", "Europe/London"),
    "ukraine": ("Ukraine", "🇺🇦", "Europe/Kyiv"),
    "poland": ("Poland", "🇵🇱", "Europe/Warsaw"),
    "portugal": ("Portugal", "🇵🇹", "Europe/Lisbon"),
    "turkey": ("Turkey", "🇹🇷", "Europe/Istanbul"),
    "estonia": ("Estonia", "🇪🇪", "Europe/Tallinn"),
    "latvia": ("Latvia", "🇱🇻", "Europe/Riga"),
    "lithuania": ("Lithuania", "🇱🇹", "Europe/Vilnius"),
    "kazakhstan": ("Kazakhstan", "🇰🇿", "Asia/Almaty"),
    "china": ("China", "🇨🇳", "Asia/Shanghai"),
    "south_korea": ("South Korea", "🇰🇷", "Asia/Seoul"),
    "philippines": ("Philippines", "🇵🇭", "Asia/Manila"),
    "canada": ("Canada", "🇨🇦", "America/Toronto"),
    "usa": ("United States", "🇺🇸", "America/New_York"),
}

# ========================= HELPERS =========================
def load_data() -> dict:
    if not DATA_PATH.exists():
        return {}
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_data(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def tz_valid(tz_name: str) -> bool:
    try:
        ZoneInfo(tz_name)
        return True
    except Exception:
        return False

def now_hhmm(tz_name: str) -> str:
    return datetime.now(ZoneInfo(tz_name)).strftime("%H:%M")

def can_use(member: discord.Member) -> bool:
    return any(r.id in ALLOWED_TZ_ROLES for r in member.roles)

# ========================= EMBED TEXT =========================
def build_timezone_embed() -> discord.Embed:
    title_text = f"{ASL}```Налаштування діскорду під себе:```{RSL}"

    # Big bold title with animated trees only here (as you asked)
    big_tree_title = f"{ASL}`Обери свою таймзону!`{RSL}"

    desc = (
        "Вітаю, авантюристу! Я **Silent Concierge**.\n"
        "Я буду твоїм провідником на сервері **Silent Cove**.\n"
        "Якщо ти побачиш помилки в моїй роботі або в інформації, що я надаю - сповістіть Модераторів. Дякую.\n\n"
        f"{DIVIDER}\n\n"
        "Щоб рейди, нагадування і події приходили тобі в правильний час\n"
        f"{big_tree_title}\n\n"
        "Як обрати:\n"
        f"{BULLET} Відкрий випадаюче меню під цим повідомленням\n"
        f"{BULLET} Обери країну **англійською мовою**\n\n"
        "Якщо ти не обереш таймзону, я спробую підібрати її автоматично.\n"
        "Але я можу помилитись.\n\n"
        "Хто може обрати таймзону:\n"
        f"{BULLET} Лише ролі <@&{ROLE_SVITOCH}> та <@&{ROLE_FRIEND}>\n"
        f"{BULLET} Ролі надаються після повної реєстрації на сервері.\n"
    )

    embed = discord.Embed(
        title=title_text,
        description=desc,
        color=0x05B2B4,
    )

    # Bottom "strip" image
    embed.set_image(url=BOTTOM_IMAGE_URL)

    # Footer removed completely (per request)
    return embed

# ========================= UI =========================
class TZSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=key, emoji=flag)
            for key, (label, flag, _tz) in COUNTRIES.items()
        ]
        super().__init__(
            placeholder="Обери країну або регіон...",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="tz_select_persistent_v1",  # required for persistent view
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not can_use(interaction.user):
            return await interaction.response.send_message(
                f"Доступно лише для ролей <@&{ROLE_SVITOCH}> та <@&{ROLE_FRIEND}>.",
                ephemeral=True,
            )

        cog = interaction.client.get_cog("TimezoneCog")
        if cog is None:
            return await interaction.response.send_message("Cog не завантажено.", ephemeral=True)

        ok, msg = await cog.apply_country(interaction.user.id, self.values[0])
        await interaction.response.send_message(msg, ephemeral=True)

class TZView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # persistent
        self.add_item(TZSelect())

# ========================= COG =========================
class TimezoneCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = load_data()

    async def apply_country(self, user_id: int, key: str) -> tuple[bool, str]:
        if key not in COUNTRIES:
            return False, "Невірний вибір."

        label, flag, tz = COUNTRIES[key]
        if not tz_valid(tz):
            return False, "Проблема з timezone для цієї країни."

        self.data[str(user_id)] = {
            "country_key": key,
            "country_label": label,
            "timezone": tz,
            "updated_at_utc": utc_stamp(),
        }
        save_data(self.data)

        return True, f"✅ {flag} **{label}**\n🕒 `{tz}` (зараз **{now_hhmm(tz)}**)"

    @app_commands.command(name="tz_post", description="Панель вибору таймзони")
    async def tz_post(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not can_use(interaction.user):
            return await interaction.response.send_message("Нема доступу.", ephemeral=True)

        await interaction.response.send_message(
            embed=build_timezone_embed(),
            view=TZView(),
        )

    @app_commands.command(name="time", description="Показує твій поточний час за збереженою таймзоною")
    async def time_slash(self, interaction: discord.Interaction):
        entry = self.data.get(str(interaction.user.id), {})
        tz = entry.get("timezone")

        if not isinstance(tz, str) or not tz_valid(tz):
            return await interaction.response.send_message(
                "Таймзона не збережена. Обери її у випадаючому меню під панеллю.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            f"🕒 Твій час зараз: **{now_hhmm(tz)}**\nТаймзона: `{tz}`",
            ephemeral=True,
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(TimezoneCog(bot))
    # persistent view registration
    bot.add_view(TZView())