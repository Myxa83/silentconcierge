# -*- coding: utf-8 -*-
# cogs/roles_panel_cog.py

from __future__ import annotations
import re
import discord
from discord.ext import commands
from discord import app_commands

from data.gear_store import get_member_gear

# ========================= IDS =========================
ROLE_SVITOCH = 1383410423704846396
ROLE_MODERATOR = 1375070910138028044
ROLE_LEADER = 1323454517664157736
ALLOWED_POST_ROLES = {ROLE_MODERATOR, ROLE_LEADER}

# Role IDs
ROLE_BEE = 1396485460611698708
ROLE_SALTY_EARS = 1410284666853785752
ROLE_RIDER = 1375827978180890752
ROLE_COOKIE_EATER = 1455029601238515869
ROLE_MARILYN = 1448268130097958912
ROLE_FOREMAN = 1455037068307861636
ROLE_SUFFERING = 1406569206815658077 # Страждущі
MIN_SUFFERING_AP = 336
GEAR_CHANNEL_ID = 1358443998603120824
GEAR_CHANNEL_URL = (
    "https://discord.com/channels/"
    "1323454227816906802/1358443998603120824"
)

# ========================= DROPDOWN CONFIG =========================
DROPDOWN_ROLES: dict[str, int] = {
    "Шалена Бджілка": ROLE_BEE,
    "Солоні вуха": ROLE_SALTY_EARS,
    "Вершник": ROLE_RIDER,
    "Плюшкоєд": ROLE_COOKIE_EATER,
    "Мерілін Монро": ROLE_MARILYN,
    "Прораб Іванич": ROLE_FOREMAN,
    "Страждущі": ROLE_SUFFERING,
}


def _parse_stat(value) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else 0


# ========================= STYLE =========================
ASL = "<a:ASL:1447205981133209773>"
RSL = "<a:RSL:1447204908494225529>"
BULLET = "<a:bulletpoint:1447549436137046099>"
DEFF = "<:Deff:1448272177848913951>"
DIVIDER = DEFF * 16
GIF_URL = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/PolosBir.gif"

# ========================= UI =========================
class RoleSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=name, value=str(role_id))
            for name, role_id in DROPDOWN_ROLES.items()
        ]
        super().__init__(
            placeholder="Обери ролі…",
            options=options,
            min_values=0,
            max_values=len(options),
            custom_id="roles_select_persistent_v4",
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(
            interaction.user,
            discord.Member,
        ):
            return await interaction.response.send_message(
                "Ця дія доступна лише на сервері.",
                ephemeral=True,
            )

        member = interaction.user
        guild = interaction.guild

        if not any(r.id == ROLE_SVITOCH for r in member.roles):
            return await interaction.response.send_message(
                f"Доступно лише для ролі <@&{ROLE_SVITOCH}>.",
                ephemeral=True,
            )

        selected_values = self.values
        suffering_selected = str(ROLE_SUFFERING) in selected_values

        if suffering_selected:
            # Парсинг Garmoth може зайняти більше 3 секунд.
            await interaction.response.defer(ephemeral=True)

            gear = get_member_gear(member.id)

            # Якщо Mongo ще не має гіру — шукаємо останнє Garmoth-посилання
            # цього користувача прямо в #Актуальний гір.
            if not gear:
                try:
                    gear_channel = (
                        guild.get_channel(GEAR_CHANNEL_ID)
                        or await guild.fetch_channel(GEAR_CHANNEL_ID)
                    )
                except Exception:
                    gear_channel = None

                latest_link = None
                if gear_channel is not None:
                    async for message in gear_channel.history(limit=None):
                        if message.author.id != member.id:
                            continue

                        match = re.search(
                            (
                                r"https?://(?:www\.)?"
                                r"garmoth\.com/character/"
                                r"[A-Za-z0-9_-]+"
                            ),
                            message.content or "",
                        )
                        if match:
                            latest_link = match.group(0)
                            break

                if latest_link:
                    gear_cog = interaction.client.get_cog("BdoGear")
                    if gear_cog is not None:
                        stats = await gear_cog.update_member_gear(
                            member,
                            latest_link,
                        )
                        if stats:
                            gear = {
                                "ap": stats.get("ap"),
                                "aap": stats.get("aap"),
                                "dp": stats.get("dp"),
                                "gs": stats.get("gs"),
                            }
                        else:
                            detail = getattr(
                                gear_cog,
                                "last_scrape_error",
                                None,
                            )
                            return await interaction.followup.send(
                                (
                                    "❌ **Я знайшов твоє посилання на Garmoth, "
                                    "але не зміг зчитати гір.**\n"
                                    f"Причина: {detail or 'невідома помилка'}"
                                ),
                                ephemeral=True,
                            )

            if not gear:
                dm_embed = discord.Embed(
                    title="Страждущі | потрібен Garmoth",
                    description=(
                        "Я не знайшов твого актуального Garmoth-посилання "
                        "в каналі гіру.\n\n"
                        "Щоб отримати роль **Страждущі**, залиш посилання "
                        "на свій **Garmoth Gear Planner** тут:\n"
                        f"{GEAR_CHANNEL_URL}\n\n"
                        f"Мінімальна вимога: **{MIN_SUFFERING_AP}+ AP**."
                    ),
                    color=0x05B2B4,
                )

                dm_sent = True
                try:
                    await member.send(embed=dm_embed)
                except (discord.Forbidden, discord.HTTPException):
                    dm_sent = False

                if dm_sent:
                    msg = (
                        "❌ **Не знайшов твого Garmoth у каналі, "
                        "тому роль не видана.**\n"
                        "Я надіслав у приватні повідомлення, куди "
                        "залишити посилання."
                    )
                else:
                    msg = (
                        "❌ **Не знайшов твого Garmoth у каналі, "
                        "тому роль не видана.**\n"
                        "Залиш актуальне посилання тут:\n"
                        f"{GEAR_CHANNEL_URL}"
                    )

                return await interaction.followup.send(
                    msg,
                    ephemeral=True,
                )

            current_ap = _parse_stat(gear.get("ap"))

            if current_ap < MIN_SUFFERING_AP:
                return await interaction.followup.send(
                    (
                        f"❌ **Твій AP: {current_ap}. Для ролі Страждущі "
                        f"потрібно {MIN_SUFFERING_AP}+ AP.**\n\n"
                        "Якщо гір змінився, онови Garmoth-посилання в каналі:\n"
                        f"{GEAR_CHANNEL_URL}"
                    ),
                    ephemeral=True,
                )

        # Оновлення ролей
        selected_ids = {int(v) for v in selected_values}
        manageable = set(DROPDOWN_ROLES.values())
        current_roles = {
            r.id
            for r in member.roles
            if r.id in manageable
        }

        to_add = selected_ids - current_roles
        to_remove = current_roles - selected_ids

        add_list = [
            guild.get_role(rid)
            for rid in to_add
            if guild.get_role(rid)
        ]
        rem_list = [
            guild.get_role(rid)
            for rid in to_remove
            if guild.get_role(rid)
        ]

        try:
            if add_list:
                await member.add_roles(*add_list)
            if rem_list:
                await member.remove_roles(*rem_list)

            if suffering_selected:
                await interaction.followup.send(
                    "✅ Ролі оновлено.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "✅ Ролі оновлено.",
                    ephemeral=True,
                )

        except discord.Forbidden:
            if suffering_selected:
                await interaction.followup.send(
                    "❌ У бота недостатньо прав. Перевір пріоритет ролей.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "❌ У бота недостатньо прав. Перевір пріоритет ролей.",
                    ephemeral=True,
                )

class RoleSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RoleSelect())

# ========================= COG =========================
class RolesPanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="post_roles_panel", description="Опублікувати панель ролей")
    async def post_roles_panel(self, interaction: discord.Interaction):
        if not any(r.id in ALLOWED_POST_ROLES for r in interaction.user.roles):
            return await interaction.response.send_message("Нема доступу.", ephemeral=True)

        desc_main = (
            f"{ASL} **Обери ролі та зроби Discord зручним для себе** {RSL}\n\n"
            "У нашому Discord багато каналів, подій і напрямів. Це зроблено не для хаосу, а щоб кожен міг знайти своє місце.\n\n"
            f"{DIVIDER}\n\n"
            "**Обираючи ролі, ти:**\n"
            f"{BULLET} бачиш лише ті канали, які відповідають твоїм інтересам\n"
            f"{BULLET} не губишся в зайвій інформації\n"
            f"{BULLET} швидше знаходиш людей зі схожим стилем гри\n\n"
            "Ролі не зобов'язують і не обмежують. Вони існують лише для зручності.\n\n"
            "**Ти можеш:**\n"
            f"{BULLET} обрати одну або кілька ролей\n"
            f"{BULLET} змінити їх у будь-який момент\n\n"
            "**Хто може обирати ролі:**\n"
            f"{BULLET} Лише роль <@&{ROLE_SVITOCH}>\n\n"
            f"{DIVIDER}\n\n"
            "**Стандартні ролі**\n\n"
            f"{BULLET} <@&{ROLE_BEE}> - лайфскільні професії та алхімія.\n"
            f"{BULLET} <@&{ROLE_SALTY_EARS}> - роль для морячків (Велл, морські квести).\n"
            f"{BULLET} <@&{ROLE_RIDER}> - квести Джейтини на Т10 коней.\n"
            f"{BULLET} <@&{ROLE_COOKIE_EATER}> - відкриває канал з промокодами.\n"
            f"{BULLET} <@&{ROLE_MARILYN}> - для тих, хто любить скріни, відео та костюми.\n"
            f"{BULLET} <@&{ROLE_FOREMAN}> - крафт ітемок у манор чи резиденцію.\n"
            f"{BULLET} <@&{ROLE_SUFFERING}> - **Black Shrine (потрібно {MIN_SUFFERING_AP}+ AP)**. Я перевірю твій гір перед видачею!\n"
        )
        
        embed = discord.Embed(description=desc_main, color=0x05B2B4)
        embed.set_image(url=GIF_URL)

        await interaction.response.send_message("Панель опубліковано.", ephemeral=True)
        await interaction.channel.send(embed=embed, view=RoleSelectView())

async def setup(bot: commands.Bot):
    await bot.add_cog(RolesPanelCog(bot))
    bot.add_view(RoleSelectView())
