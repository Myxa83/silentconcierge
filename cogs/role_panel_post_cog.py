# -*- coding: utf-8 -*-
# cogs/roles_panel_cog.py
# Silent Concierge - Roles Panel (one cog, one command, two embeds)

from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands

# ========================= IDS =========================
ROLE_SVITOCH = 1383410423704846396

ROLE_MODERATOR = 1375070910138028044
ROLE_LEADER = 1323454517664157736
ALLOWED_POST_ROLES = {ROLE_MODERATOR, ROLE_LEADER}

# Standard (dropdown roles)
ROLE_BEE = 1396485460611698708
ROLE_SALTY_EARS = 1410284666853785752
ROLE_RIDER = 1375827978180890752
ROLE_COOKIE_EATER = 1455029601238515869
ROLE_MARILYN = 1447368601387663400
ROLE_FOREMAN = 1455037068307861636

# Careful
ROLE_BREADS = 1396485384199733460
ROLE_SUFFERING = 1406569206815658077

# Mod-permission
ROLE_STREAMER = 1395419857016852520
ROLE_SAILOR = 1338862723844407317
ROLE_SAGEKEEPER = 1413564813421838337

# ========================= DROPDOWN (ONLY THESE 6) =========================
DROPDOWN_ROLES: dict[str, int] = {
    "Шалена Бджілка": ROLE_BEE,
    "Солоні вуха": ROLE_SALTY_EARS,
    "Вершник": ROLE_RIDER,
    "Плюшкоєд": ROLE_COOKIE_EATER,
    "Мерілін Монро": ROLE_MARILYN,
    "Прораб Іванич": ROLE_FOREMAN,
}

# ========================= STYLE / EMOJIS =========================
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
def has_any_role(member: discord.Member, roles: set[int]) -> bool:
    return any(r.id in roles for r in member.roles)

def is_svitoch(member: discord.Member) -> bool:
    return any(r.id == ROLE_SVITOCH for r in member.roles)

# ========================= EMBEDS =========================
def build_roles_embeds() -> tuple[discord.Embed, discord.Embed]:
    # Embed 1: intro + standard roles (dropdown is attached to this message)
    title_text = f"{ASL}Обери ролі та зроби Discord зручним для себе{RSL}\n\n"
    desc_main = (
        title_text
        + "У нашому Discord багато каналів, подій і напрямів. Це зроблено не для хаосу, "
          "а щоб кожен міг знайти своє місце.\n\n"
        + "**Обираючи ролі, ти:**\n"
        + f"{BULLET} бачиш лише ті канали, які відповідають твоїм інтересам\n"
        + f"{BULLET} не губишся в зайвій інформації\n"
        + f"{BULLET} швидше знаходиш людей зі схожим стилем гри\n"
        + f"{BULLET} допомагаєш нам підтримувати порядок і комфорт для всіх\n\n"
        + "Ролі не зобовʼязують і не обмежують. Вони існують лише для зручності, навігації та атмосфери.\n\n"
        + "**Ти можеш:**\n"
        + f"{BULLET} обрати одну або кілька ролей\n"
        + f"{BULLET} змінити їх у будь-який момент\n"
        + f"{BULLET} додати ролі пізніше, навіть якщо ти вже давно в гільдії\n\n"
        + f"Хто може обирати ролі:\n{BULLET} Лише роль <@&{ROLE_SVITOCH}>\n\n"
        + f"{DIVIDER}\n\n"
        + "**Стандартні ролі**\n\n"
        + f"{BULLET}<@&{ROLE_BEE}> - ти обожнюєш трудитись, і всі твої активності це шчупання травки після вирощування грибів, щоб ботім використати це в епічній алхімці XD. Загалом ця роль поєднує всі лайфскільні професії, тому якщо тобі потрібні гайди по відповідній тематиці, або хочеш отримати пораду від свого однодумця, обирай цюроль!\n"
        + f"{BULLET}<@&{ROLE_SALTY_EARS}> - роль для морячків, які хочуть побудувати корабель і піти тягати вела за тентаклю. Роль тегється під час морських квестів і рейду на морського боса Велла.\n"
        + f"{BULLET}<@&{ROLE_RIDER}> - якщо ти хочеш зібрати ітемки на апгрейт Т10 конів, треба раз на тиждень рбити квести Джейтини на скачки. Обирайте роль, якщо хочете прискорити отримання Т10 коня.\n"
        + f"{BULLET}<@&{ROLE_COOKIE_EATER}> - щоб для тебе був відкритий канал з кодами, за якіти отримаєш смачності - бери цю роль.\n"
        + f"{BULLET}<@&{ROLE_MARILYN}> - тобі подобається скринитись чи зніматись в відео, ти шукаєш нові емоції, виконуєш квести на них, та крайфтиш спеціальні костюми та їжу з хімкою.\n"
        + f"{BULLET}<@&{ROLE_FOREMAN}> - тобі цікаво крафтити ітемки в манор чи резиденцію, вчитися їх розставляти.\n"
    )

    embed_main = discord.Embed(description=desc_main, color=0x05B2B4)
    embed_main.set_image(url=BOTTOM_IMAGE_URL)

    # Embed 2: all other roles, full text blocks
    desc_other = (
        f"{DIVIDER}\n\n"
        "**Ролі, для яких потрібен відповідний гір. Обирай обережно, взявши деякі вже неможливо буде їх позбутись.**\n\n"
        f"{BULLET}<@&{ROLE_BREADS}>\n"
        "Здебільшого гроки гільдії Rumbling Cove, як ходять на НОД вари.\n\n"
        f"{BULLET}<@&{ROLE_SUFFERING}>\n"
        "Ігроки 290+ АР яким цікавий прохід паті босів Чорного Храму.\n\n"
        f"{DIVIDER}\n\n"
        "**Ролі, для яких потрібні дозволи модераторів.**\n\n"
        f"{BULLET}<@&{ROLE_STREAMER}>\n"
        "Ти стрімиш і бажаєш, щоб твої відео побачилило більше людей.\n\n"
        f"{BULLET}<@&{ROLE_SAILOR}>\n"
        "Ти маєш потужний корабель і бажання возити морячків на щоденні та тижневі морські квести.\n\n"
        f"{BULLET}<@&{ROLE_SAGEKEEPER}>\n"
        "Ти знаєшся на таємних знаннях і у твоїх сувоях можна знайти секретні рецепти чудових речей. "
        "Ти пишеш гайди по який-небудь тематиці.\n\n"
        f"{BULLET}<@&{ROLE_MODERATOR}>\n"
        "В тебе є час і достатньо відповідальності для пільнування за нашим сервером і відповідний досвід.\n"
    )

    embed_other = discord.Embed(description=desc_other, color=0x05B2B4)
    embed_other.set_image(url=BOTTOM_IMAGE_URL)

    return embed_main, embed_other

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
            custom_id="roles_select_persistent_v2",
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "Ця дія доступна лише на сервері.",
                ephemeral=True,
            )

        member: discord.Member = interaction.user
        guild: discord.Guild = interaction.guild

        if not is_svitoch(member):
            return await interaction.response.send_message(
                f"Доступно лише для ролі <@&{ROLE_SVITOCH}>.",
                ephemeral=True,
            )

        manageable = set(DROPDOWN_ROLES.values())
        selected = {int(v) for v in self.values}
        current = {r.id for r in member.roles if r.id in manageable}

        to_add = selected - current
        to_remove = current - selected

        add_roles = [guild.get_role(rid) for rid in to_add]
        add_roles = [r for r in add_roles if r is not None]

        rem_roles = [guild.get_role(rid) for rid in to_remove]
        rem_roles = [r for r in rem_roles if r is not None]

        try:
            if add_roles:
                await member.add_roles(*add_roles, reason="Roles panel dropdown")
            if rem_roles:
                await member.remove_roles(*rem_roles, reason="Roles panel dropdown")
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Нема прав змінювати ролі. Перевір дозволи бота.",
                ephemeral=True,
            )
        except discord.HTTPException:
            return await interaction.response.send_message(
                "Discord не дав змінити ролі. Спробуй ще раз.",
                ephemeral=True,
            )

        await interaction.response.send_message("Ролі оновлено.", ephemeral=True)

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
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Нема доступу.", ephemeral=True)

        if not has_any_role(interaction.user, ALLOWED_POST_ROLES):
            return await interaction.response.send_message("Нема доступу.", ephemeral=True)

        if interaction.channel is None:
            return await interaction.response.send_message("Нема каналу для публікації.", ephemeral=True)

        await interaction.response.send_message("Панель опубліковано.", ephemeral=True)

        embed_main, embed_other = build_roles_embeds()

        # Message 1: embed 1 + dropdown
        await interaction.channel.send(embed=embed_main, view=RoleSelectView())

        # Message 2: embed 2 without dropdown
        await interaction.channel.send(embed=embed_other)

async def setup(bot: commands.Bot):
    await bot.add_cog(RolesPanelCog(bot))
    bot.add_view(RoleSelectView())