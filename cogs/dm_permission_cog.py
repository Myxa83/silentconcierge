# -*- coding: utf-8 -*-
# cogs/dm_permission_cog.py
# Silent Concierge - DM Permission Panel (dropdown, persistent)
#
# Команди:
#   /dm_permission_post  - постить панель (тільки для модераторів)
#
# Логіка:
# - Випадаюче меню можуть використовувати тільки 2 ролі: Свiточ, Друг
# - Вибір можна змінювати у будь-який момент
# - Запис у JSON: data/dm_permissions.json

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import app_commands

# ========================= PATHS =========================
DATA_PATH = Path("data/dm_permissions.json")

# ========================= ROLES =========================
# Хто може змінювати налаштування у dropdown
ROLE_SVITOCH = 1383410423704846396
ROLE_FRIEND = 1325124628330446951
ALLOWED_USER_ROLES = {ROLE_SVITOCH, ROLE_FRIEND}

# Хто може постити панель командою
ROLE_MODERATOR = 1375070910138028044
ROLE_LEADER = 1323454517664157736
ALLOWED_POST_ROLES = {ROLE_MODERATOR, ROLE_LEADER}

# ========================= ASSETS =========================
ASL = "<a:ASL:1447205981133209773>"
RSL = "<a:RSL:1447204908494225529>"
BULLET = "<a:bulletpoint:1447549436137046099>"
DEFF = "<:Deff:1448272177848913951>"
DIVIDER = DEFF * 16

BOTTOM_IMAGE_URL = (
    "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/"
    "assets/backgrounds/PolosBir.gif"
)

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
    DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def utc_stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def has_any_role(member: discord.Member, role_ids: set[int]) -> bool:
    return any(r.id in role_ids for r in member.roles)

# ========================= EMBED =========================
def build_permission_embed() -> discord.Embed:
    title_text = f"{ASL}```Дозвіл на особисті повідомлення```{RSL}"

    desc = (
        "Я бот спільноти і хочу бути корисним і не заважати.\n\n"
        f"{DIVIDER}\n\n"
        "Іноді мені потрібно надсилати тобі важливі повідомлення в особисті:\n\n"
        f"{BULLET} нагадування про події\n"
        f"{BULLET} зміни в розкладі\n"
        f"{BULLET} службову інформацію, яку не варто губити в каналах\n\n"
        "Для цього мені потрібен твій дозвіл на відправку особистих повідомлень.\n\n"
        f"{DIVIDER}\n\n"
        f"{BULLET} Я не пишу часто\n"
        f"{BULLET} Я не надсилаю спам\n"
        f"{BULLET} Я пишу тільки по ділу\n\n"
        "Твій комфорт важливіший за будь-які налаштування.\n"
        "Якщо ти не хочеш отримувати особисті повідомлення, просто відмовся. "
        "Я це поважаю і не турбуватиму.\n\n"
        "Рішення повністю за тобою і його завжди можна змінити."
    )

    embed = discord.Embed(
        title=title_text,
        description=desc,
        color=0x05B2B4,
    )
    embed.set_image(url=BOTTOM_IMAGE_URL)
    return embed

# ========================= UI =========================
class DMPermissionSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Так, хочу отримувати особисті повідомлення",
                value="allow"
            ),
            discord.SelectOption(
                label="Ні, не хочу отримувати особисті повідомлення",
                value="deny"
            ),
        ]
        super().__init__(
            placeholder="Обери варіант…",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="dm_permission_select_persistent_v1",
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Ця дія доступна лише на сервері.",
                ephemeral=True,
            )

        if not has_any_role(interaction.user, ALLOWED_USER_ROLES):
            return await interaction.response.send_message(
                f"Доступно лише для ролей <@&{ROLE_SVITOCH}> та <@&{ROLE_FRIEND}>.",
                ephemeral=True,
            )

        cog = interaction.client.get_cog("DMPermissionCog")
        if cog is None:
            return await interaction.response.send_message(
                "Cog не завантажено.",
                ephemeral=True,
            )

        allowed = (self.values[0] == "allow")
        cog.set_permission(interaction.user.id, allowed)

        await interaction.response.send_message(
            "Налаштування збережено.",
            ephemeral=True,
        )

class DMPermissionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DMPermissionSelect())

# ========================= COG =========================
class DMPermissionCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = load_data()

    def set_permission(self, user_id: int, allowed: bool) -> None:
        self.data[str(user_id)] = {
            "allowed": allowed,
            "updated_at_utc": utc_stamp(),
        }
        save_data(self.data)

    def can_dm(self, user_id: int) -> bool:
        entry = self.data.get(str(user_id))
        return bool(entry and entry.get("allowed") is True)

    @app_commands.command(
        name="dm_permission_post",
        description="Панель дозволу на особисті повідомлення"
    )
    async def dm_permission_post(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Нема доступу.", ephemeral=True)

        if not has_any_role(interaction.user, ALLOWED_POST_ROLES):
            return await interaction.response.send_message("Нема доступу.", ephemeral=True)

        if interaction.channel is None:
            return await interaction.response.send_message("Нема каналу для публікації.", ephemeral=True)

        # 1) Тихо підтверджуємо виклик
        await interaction.response.send_message("Панель опубліковано.", ephemeral=True)

        # 2) Публічно постимо без системного рядка "застосував команду"
        await interaction.channel.send(
            embed=build_permission_embed(),
            view=DMPermissionView(),
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(DMPermissionCog(bot))
    bot.add_view(DMPermissionView())