# -*- coding: utf-8 -*-
# cogs/interest_roles_cog.py

import discord
from discord.ext import commands
from discord import app_commands
import json
from pathlib import Path

ROLES_CHANNEL_ID = 1370522199873814528
B = "<:bullet:1447181813641511025>"
JSON_PATH = Path("data/interest_roles.json")


def load_roles():
    if not JSON_PATH.exists():
        raise FileNotFoundError("Не знайдено data/interest_roles.json")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_roles_embed(roles_data) -> discord.Embed:
    embed = discord.Embed(
        title="Ролі за інтересами SilentCove",
        description="Обери одну або кілька ролей, які підходять тобі.\n",
        color=0x1F2427
    )

    for name in roles_data.keys():
        readable = name.replace("_", " ")
        embed.add_field(name=f"{B} {readable}", value="\u200b", inline=False)

    return embed


class InterestRolesSelect(discord.ui.Select):
    def __init__(self, roles_data: dict):
        self.role_map = {k: int(v) for k, v in roles_data.items()}

        options = [
            discord.SelectOption(label=name, value=name)
            for name in self.role_map.keys()
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

        selected = set(self.values)
        roles_to_add = []
        roles_to_remove = []

        for name, role_id in self.role_map.items():
            role = guild.get_role(role_id)
            if not role:
                continue

            should_have = name in selected
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
    def __init__(self, roles_data):
        super().__init__(timeout=None)
        self.add_item(InterestRolesSelect(roles_data))


class InterestRolesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.roles_data = load_roles()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.send_panel_once()

        # реєструємо view після рестарту
        self.bot.add_view(InterestRolesView(self.roles_data))

    async def send_panel_once(self):
        channel = self.bot.get_channel(ROLES_CHANNEL_ID)
        if not channel:
            return

        embed = build_roles_embed(self.roles_data)
        view = InterestRolesView(self.roles_data)

        # Тихо, без видимих команд
        await channel.send(embed=embed, view=view)
        print("[INFO] Панель вибору ролей автоматично відправлена.")


async def setup(bot):
    await bot.add_cog(InterestRolesCog(bot))
