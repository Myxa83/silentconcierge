# cogs/discord_role_select_cog.py
# Discord Role Select Cog
# ВІДПОВІДАЄ ТІЛЬКИ ЗА ЛОГІКУ РОЛЕЙ
# Embed створюється ІНШИМ cog-ом


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


select = discord.ui.Select(
placeholder="Обери ролі",
min_values=0,
max_values=len(options),
options=options,
custom_id="svitoch_role_select",
)


select.callback = self._callback
self.add_item(select)


async def _callback(self, interaction: discord.Interaction):
if not interaction.guild or not isinstance(interaction.user, discord.Member):
await interaction.response.send_message("❌ Помилка доступу", ephemeral=True)
return


member = interaction.user
guild = interaction.guild


svitoch = guild.get_role(ROLE_SVITOCH)
if not svitoch or svitoch not in member.roles:
await interaction.response.send_message(
"❌ Ці ролі доступні лише для ролі Світоч",
ephemeral=True
)
return


chosen = {int(v) for v in interaction.data.get("values", [])}
all_roles = set(SELECTABLE_ROLES.values())


added = []
removed = []


for rid in chosen:
role = guild.get_role(rid)
if role and role not in member.roles:
await member.add_roles(role, reason="Discord role select")
added.append(role)


for rid in all_roles - chosen:
role = guild.get_role(rid)
if role and role in member.roles:
await member.remove_roles(role, reason="Discord role select")
removed.append(role)


await interaction.response.send_message("✅ Ролі оновлено", ephemeral=True)


if added or removed:
await self._log(guild, member, added, removed)


async def _log(self, guild, member, added, removed):
channel = guild.get_channel(MODLOG_CHAN)
if not channel:
return


embed = discord.Embed(title="Role select", color=EMBED_COLOR)
embed.add_field(name="User", value=f"{member.mention} | {member.id}", inline=False)


if added:
embed.add_field(
name="Added",
value="\n".join(r.mention for r in added),
inline=False
await bot.add_cog(DiscordRoleSelectCog(bot))
