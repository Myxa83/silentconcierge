# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands
from discord import app_commands

from data.mongo_store import load_state, save_state

# ========================= STORAGE =========================
STATE_COLLECTION = "timezones"

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
BOTTOM_IMAGE_URL = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/PolosBir.gif"

COUNTRIES = {
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
    data = load_state(
        STATE_COLLECTION,
        {},
        legacy_path="data/timezones.json",
    )
    return data if isinstance(data, dict) else {}

def save_data(data: dict) -> None:
    save_state(STATE_COLLECTION, data)

# ========================= UI =========================
class TZSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=key, emoji=flag)
            for key, (label, flag, _tz) in COUNTRIES.items()
        ]
        super().__init__(
            placeholder="Оберіть країну або регіон...",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="tz_select_persistent_v1",
        )

    async def callback(self, interaction: discord.Interaction):
        if not any(r.id in ALLOWED_TZ_ROLES for r in interaction.user.roles):
            return await interaction.response.send_message(
                f"Це доступно лише для <@&{ROLE_SVITOCH}> та <@&{ROLE_FRIEND}>.", ephemeral=True
            )

        cog = interaction.client.get_cog("TimezoneCog")
        if cog:
            ok, msg = await cog.apply_country(interaction.user, self.values[0])
            await interaction.response.send_message(msg, ephemeral=True)

class TZView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TZSelect())

# ========================= COG =========================
class TimezoneCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def apply_country(self, user: discord.Member, key: str) -> tuple[bool, str]:
        if key not in COUNTRIES:
            return False, "Невірний вибір."

        label, flag, tz = COUNTRIES[key]
        current_data = load_data()
        
        current_data[str(user.id)] = {
            "name": user.display_name,
            "country_key": key,
            "country_label": label,
            "timezone": tz,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        save_data(current_data)
        now_time = datetime.now(ZoneInfo(tz)).strftime("%H:%M")
        return True, f"✅ {flag} **{label}** збережено!\n🕒 Ваш поточний час: **{now_time}**"

    @app_commands.command(name="tz_post", description="Надіслати панель таймзон")
    @app_commands.checks.has_permissions(administrator=True)
    async def tz_post(self, interaction: discord.Interaction):
        title_text = f"{ASL}```Налаштування діскорду під себе:```{RSL}"
        big_tree_title = f"{ASL}**Обери свою таймзону!**{RSL}"

        desc = (
            "Вітаю, авантюристу! Я **Silent Concierge**.\n"
            "Я буду твоїм провідником на сервері **Silent Cove**.\n"
            "Якщо ти побачиш помилки в роботі - сповістіть Модераторів.\n\n"
            f"{DIVIDER}\n\n"
            "Щоб рейди та події приходили тобі в правильний час\n"
            f"{big_tree_title}\n\n"
            "Як обрати:\n"
            f"{BULLET} Відкрий меню під цим повідомленням\n"
            f"{BULLET} Обери країну **англійською мовою**\n\n"
            "Хто може обрати таймзону:\n"
            f"{BULLET} Лише ролі <@&{ROLE_SVITOCH}> та <@&{ROLE_FRIEND}>"
        )

        embed = discord.Embed(title=title_text, description=desc, color=0x05B2B4)
        embed.set_image(url=BOTTOM_IMAGE_URL)
        await interaction.response.send_message(embed=embed, view=TZView())

    @app_commands.command(name="tz_check_db", description="Адмін: Скільки людей у базі?")
    @app_commands.checks.has_permissions(administrator=True)
    async def tz_check_db(self, interaction: discord.Interaction):
        db = load_data()
        await interaction.response.send_message(
            f"📊 У базі таймзон зараз записів: **{len(db)}**", ephemeral=True
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(TimezoneCog(bot))
    bot.add_view(TZView())
