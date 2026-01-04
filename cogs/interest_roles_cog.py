# -*- coding: utf-8 -*-
# cogs/interest_roles_cog.py

import discord
from discord.ext import commands
from discord import app_commands

# Реальні ID ролей
ROLE_STRAZHDUSHCHI = 1406569206815658077
ROLE_HLIBCHYKY = 1396485384199733460
ROLE_VERSHNYK = 1375827978180890752
ROLE_SOLONI_VUHA = 1410284666853785752
ROLE_MORIAK = 1338862723844407317
ROLE_ZBERIHACH = 1413564813421838337
ROLE_BDZHILKA = 1396485460611698708
ROLE_MERILIN = 1447368601387663400

# Канал для панелі ролей
ROLES_CHANNEL_ID = 111111111111111199   # підставиш свій канал


def build_roles_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Ролі за інтересами SilentCove",
        description=(
            "Обери ролі, які відповідають твоєму стилю або інтересам. "
            "Можна обрати кілька варіантів одразу.\n\n"
            "Ці ролі допомагають знаходити однодумців і пінгати правильні групи."
        ),
        color=discord.Color.teal()
    )

    embed.add_field(
        name="Страждущі",
        value="Мембери та друзі гільдії, яким потрібна допомога з Атораксіоном або Шрайнами.",
        inline=False
    )
    embed.add_field(
        name="Хлібчики",
        value="Орда неадекватів на нодах.",
        inline=False
    )
    embed.add_field(
        name="Вершник",
        value="Мембери, яким цікаві скачки.",
        inline=False
    )
    embed.add_field(
        name="Солоні Вуха",
        value="Мембери та друзі гільдії, яким цікавий морський контент.",
        inline=False
    )
    embed.add_field(
        name="Моряк",
        value="Любителі морських пригод, які можуть і гайд написати, і на квести звозити.",
        inline=False
    )
    embed.add_field(
        name="Зберігач Мудрощів",
        value="Мембери, які пишуть гайди.",
        inline=False
    )
    embed.add_field(
        name="Шалена Бджілка",
        value="Лайфскілерні мембери і друзі гільдії.",
        inline=False
    )
    embed.add_field(
        name="Мерілін Монро",
        value="Мембери і друзі гільдії, які хочуть брати участь у медійних івентах.",
        inline=False
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

        selected_values = set(self.values)

        roles_to_add = []
        roles_to_remove = []

        for value, role_id in role_map.items():
            role = guild.get_role(role_id)
            if role is None:
                continue

            has_role = role in member.roles
            should_have = value in selected_values

            if should_have and not has_role:
                roles_to_add.append(role)
            if not should_have and has_role:
                roles_to_remove.append(role)

        if roles_to_add:
            await member.add_roles(*roles_to_add, reason="Вибір інтересів")
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="Вибір інтересів")

        text_added = ", ".join([r.name for r in roles_to_add]) if roles_to_add else "немає"
        text_removed = ", ".join([r.name for r in roles_to_remove]) if roles_to_remove else "немає"

        await interaction.response.send_message(
            f"Оновлено ролі.\nДодано: {text_added}\nЗнято: {text_removed}",
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

        embed = build_roles_embed()
        view = InterestRolesView()

        await channel.send(embed=embed, view=view)
        await interaction.response.send_message(
            "Панель вибору ролей відправлена.",
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(InterestRolesView())


async def setup(bot):
    await bot.add_cog(InterestRolesCog(bot))