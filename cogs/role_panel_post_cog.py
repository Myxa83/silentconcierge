# -*- coding: utf-8 -*-
# cogs/roles_panel_cog.py

from __future__ import annotations
import json
import discord
from pathlib import Path
from discord.ext import commands
from discord import app_commands

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
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Ця дія доступна лише на сервері.", ephemeral=True)

        member = interaction.user
        guild = interaction.guild
        user_id = str(member.id)

        # 1. Перевірка на роль Світоч
        if not any(r.id == ROLE_SVITOCH for r in member.roles):
            return await interaction.response.send_message(f"Доступно лише для ролі <@&{ROLE_SVITOCH}>.", ephemeral=True)

        selected_values = self.values
        
        # 2. ПЕРЕВІРКА ГІРУ ДЛЯ "СТРАЖДУЩІ" (290+ AP)
        if str(ROLE_SUFFERING) in selected_values:
            history_path = Path("data/garmoth_history.json")
            has_gear = False
            current_ap = 0
            
            if history_path.exists():
                try:
                    with open(history_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        user_history = data.get(user_id, [])
                        if user_history and isinstance(user_history, list):
                            last_entry = user_history[-1] # Останній запис
                            current_ap = last_entry.get("ap", 0)
                            if current_ap >= 290:
                                has_gear = True
                except Exception:
                    pass

            if not has_gear:
                msg = (
                    f"❌ **Твій АП ({current_ap}) недостатній для ролі Страждущі (потрібно 290+).**\n\n"
                    "Онови дані на [Garmoth](https://garmoth.com/) та надай скріншот у цьому каналі:\n"
                    "https://discord.com/channels/1323454227816906802/1358443998603120824 \n\n"
                    "Після оновлення даних у системі ти зможеш взяти цю роль."
                )
                return await interaction.response.send_message(msg, ephemeral=True)

        # 3. Оновлення ролей
        selected_ids = {int(v) for v in selected_values}
        manageable = set(DROPDOWN_ROLES.values())
        current_roles = {r.id for r in member.roles if r.id in manageable}

        to_add = selected_ids - current_roles
        to_remove = current_roles - selected_ids
        
        add_list = [guild.get_role(rid) for rid in to_add if guild.get_role(rid)]
        rem_list = [guild.get_role(rid) for rid in to_remove if guild.get_role(rid)]

        try:
            if add_list: await member.add_roles(*add_list)
            if rem_list: await member.remove_roles(*rem_list)
            await interaction.response.send_message("✅ Ролі оновлено.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ У бота недостатньо прав. Перевір пріоритет ролей.", ephemeral=True)

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
            f"{BULLET} <@&{ROLE_SUFFERING}> - **Black Shrine (потрібно 290+ AP)**. Я перевірю твій гір перед видачею!\n"
        )
        
        embed = discord.Embed(description=desc_main, color=0x05B2B4)
        embed.set_image(url=GIF_URL)

        await interaction.response.send_message("Панель опубліковано.", ephemeral=True)
        await interaction.channel.send(embed=embed, view=RoleSelectView())

async def setup(bot: commands.Bot):
    await bot.add_cog(RolesPanelCog(bot))
    bot.add_view(RoleSelectView())
