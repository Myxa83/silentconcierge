# -*- coding: utf-8 -*-
# cogs/discord_role_select_cog.py
# Discord Role Select Cog
# Відповідає тільки за логіку ролей
# Embed створюється іншим cog-ом

from __future__ import annotations

import discord
from discord.ext import commands

# ================== CONFIG ==================
GUILD_ID = 1323454227816906802
ROLE_SVITOCH = 1383410423704846396
MODLOG_CHAN = 1350571574557675520

SELECTABLE_ROLES = {
    "Мерілін Монро": 1447368601387663400,
    "Вершник": 1375827978180890752,
    "Солоні Вуха": 1410284666853785752,
    "Стрімер": 1395419857016852520,
    "Шалена Бджілка": 1396485460611698708,
    "Фотограф": 1330492212525662281,
}

EMBED_COLOR = 0x05B2B4

# ================== VIEW ==================
class RoleSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        options = [
            discord.SelectOption(label=name, value=str(role_id))
            for name, role_id in SELECTABLE_ROLES.items()
        ]

        self.select = discord.ui.Select(
            placeholder="Обери ролі",
            min_values=0,
            max_values=len(options),
            options=options,
            custom_id="svitoch_role_select",
        )
        self.select.callback = self._callback
        self.add_item(self.select)

    async def _callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Помилка доступу", ephemeral=True)
            return

        guild = interaction.guild
        member = interaction.user

        svitoch = guild.get_role(ROLE_SVITOCH)
        if not svitoch or svitoch not in member.roles:
            await interaction.response.send_message(
                "❌ Ці ролі доступні лише для ролі Світоч",
                ephemeral=True,
            )
            return

        chosen_ids = {int(v) for v in interaction.data.get("values", [])}
        all_ids = set(SELECTABLE_ROLES.values())

        added = []
        removed = []

        # add selected
        for rid in chosen_ids:
            role = guild.get_role(rid)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="Discord role select")
                    added.append(role)
                except Exception:
                    pass

        # remove unselected
        for rid in all_ids - chosen_ids:
            role = guild.get_role(rid)
            if role and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Discord role select")
                    removed.append(role)
                except Exception:
                    pass

        await interaction.response.send_message("✅ Ролі оновлено", ephemeral=True)

        if added or removed:
            await self._log(guild, member, added, removed)

    async def _log(self, guild: discord.Guild, member: discord.Member, added, removed):
        channel = guild.get_channel(MODLOG_CHAN)
        if channel is None:
            try:
                channel = await guild.fetch_channel(MODLOG_CHAN)
            except Exception:
                return

        embed = discord.Embed(title="Role select", color=EMBED_COLOR)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="User", value=f"{member.mention} | {member.id}", inline=False)

        if added:
            embed.add_field(
                name="Added",
                value="\n".join(r.mention for r in added),
                inline=False,
            )
        if removed:
            embed.add_field(
                name="Removed",
                value="\n".join(r.mention for r in removed),
                inline=False,
            )

        try:
            await channel.send(embed=embed)
        except Exception:
            pass

# ================== COG ==================
class DiscordRoleSelectCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._view_added = False

    @commands.Cog.listener()
    async def on_ready(self):
        # persistent view, add once
        if self._view_added:
            return
        self._view_added = True
        self.bot.add_view(RoleSelectView())

async def setup(bot: commands.Bot):
    await bot.add_cog(DiscordRoleSelectCog(bot))
