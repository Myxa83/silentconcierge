# -*- coding: utf-8 -*-
# cogs/interest_roles_cog.py

import discord
from discord.ext import commands
from discord import app_commands

# Ролі
ROLE_STRAZHDUSHCHI = 1406569206815658077
ROLE_HLIBCHYKY = 1396485384199733460
ROLE_VERSHNYK = 1375827978180890752
ROLE_SOLONI_VUHA = 1410284666853785752
ROLE_MORIAK = 1338862723844407317
ROLE_ZBERIHACH = 1413564813421838337
ROLE_BDZHILKA = 1396485460611698708
ROLE_MERILIN = 1447368601387663400

# Тестовий канал
ROLES_CHANNEL_ID = 1370522199873814528

# Кастомний емодзі bullet
B = "<:bullet:1447181813641511025>"


def build_roles_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Ролі за інтересами SilentCove",
        description=(
            f"{B} Страждущі - мембери і друзі гільдії, яким потрібна допомога з Атораксіоном або Шрайнами.\n"
            f"{B} Хлібчики - орда неадекватів на нодах.\n"
            f"{B} Вершник - мембери, яким цікаві скачки.\n"
            f"{B} Солоні Вуха - мембери і друзі гільдії, яким цікавий морський контент.\n"
            f"{B} Моряк - любителі морських пригод, які можуть і гайд написати, і на квести звозити.\n"
            f"{B} Зберігач Мудрощів - мембери, які пишуть гайди.\n"
            f"{B} Шалена Бджілка - лайфскілерні мембери і друзі гільдії.\n"
            f"{B} Мерілін Монро - мембери і друзі гільдії, які хочуть брати участь у медійних івентах.\n"
        ),
        color=0x1F2427   # темний графіт SilentCove
    )
    return embed


class InterestRolesSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Страждущі", value="strazhd"),
            discord.SelectOption(label="Хлібчики", value="hlib"),
            discord.SelectOption(label="Вершник", value="vershnyk"),
            discord.SelectOption(label="Солоні Вуха", value="soloni"),
            discord.SelectOption(label="Моряк", value="moriak"),
            discord.SelectOption(label="Зберігач Мудрощів", value="zberihach"),
            discord.SelectOption(label="Шалена Бджілка", value="bdzhilka"),
            discord.SelectOption(label="Мерілін Монро", value="merilin"),
        ]

        super().__init__(
            placeholder="Обери свої інтереси",
            min_values=0,
            max_values=len(options),
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        role_map = {
            "strazhd": ROLE_STRAZHDUSHCHI,
            "hlib": ROLE_HLIBCHYKY,
            "vershnyk": ROLE_VERSHNYK,
            "soloni": ROLE_SOLONI_VUHA,
            "moriak": ROLE_MORIAK,
            "zberihach": ROLE_ZBERIHACH,
            "bdzhilka": ROLE_BDZHILKA,
            "merilin": ROLE_MERILIN,
        }

        selected = set(self.values)
        roles_to_add = []
        roles_to_remove = []

        for value, role_id in role_map.items():
            role = guild.get_role(role_id)
            if role is None:
                continue

            should_have = value in selected
            has_role = role in member.roles

            if should_have and not has_role:
                roles_to_add.append(role)
            if not should_have and has_role:
                roles_to_remove.append(role)

        if roles_to_add:
            await member.add_roles(*roles_to_add)
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)

        await interaction.response.send_message(
            content="Ролі оновлено.",
            ephemeral=True
        )


class InterestRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(InterestRolesSelect())


class InterestRolesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="roles_panel", description="Показати панель вибору ролей")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def roles_panel(self, interaction: discord.Interaction):
        channel = interaction.guild.get_channel(ROLES_CHANNEL_ID)
        if channel is None:
            channel = interaction.channel

        await channel.send(embed=build_roles_embed(), view=InterestRolesView())

        # тиха відповідь, ніхто не бачить
        await interaction.response.send_message(content=None, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        # забезпечує роботу меню після перезапуску
        self.bot.add_view(InterestRolesView())


async def setup(bot):
    await bot.add_cog(InterestRolesCog(bot))
