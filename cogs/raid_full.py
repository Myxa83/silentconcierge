
import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
import datetime
import pytz
import os
from dotenv import load_dotenv

# Підключення зовнішньої функції для отримання часового поясу
def get_timezone_for_user(user_id):
    return "Europe/London"

load_dotenv()

raid_data = {
    'slots': 0,
    'taken': 0,
    'is_closed': False,
    'channel_id': None,
    'message_id': None,
    'date': None,
    'time': None,
    'найм': None,
    'nick': None
}

def build_embed(bot, user_id):
    залишилось = max(0, raid_data['slots'] - raid_data['taken'])
    status = (
        "```ansi\n\u001b[2;31mЗАКРИТО\u001b[0m```"
        if raid_data['is_closed'] else
        "```ansi\n\u001b[2;36mВІДКРИТО\u001b[0m```"
    )
    embed_color = discord.Color.teal() if not raid_data['is_closed'] else discord.Color.red()

    user_tz = pytz.timezone(get_timezone_for_user(user_id))
    full_date = datetime.datetime.strptime(raid_data['date'], "%d.%m.%Y")
    date_timestamp = int(user_tz.localize(full_date).timestamp())

    embed = Embed(
        title=f"<:00000005_special:1376430317270995024> **Гільдійні боси з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲**",
        description=f"**Дата:** <t:{date_timestamp}:D>\n\n**Статус:** {status}",
        color=embed_color
    )
    embed.set_image(url="https://i.imgur.com/CNtxvsV.jpeg" if raid_data['is_closed'] else "https://i.imgur.com/5GvjWCd.jpeg")

    if raid_data['is_closed']:
        embed.set_footer(
            text="Silent Cove | Ще побачимось наступного найму!",
            icon_url=bot.user.avatar.url if bot.user.avatar else bot.user.default_avatar.url
        )
        return embed

    найм_hour, найм_minute = map(int, raid_data['найм'].split(":"))
    найм_combined = datetime.datetime.combine(full_date.date(), datetime.time(найм_hour, найм_minute))
    найм_timestamp = int(user_tz.localize(найм_combined).timestamp())

    hour, minute = map(int, raid_data['time'].split(":"))
    combined = datetime.datetime.combine(full_date.date(), datetime.time(hour, minute))
    start_timestamp = int(user_tz.localize(combined).timestamp())

    embed.add_field(name="⠀", value=f"**Шепотіть:** {raid_data['nick']}", inline=False)
    embed.add_field(name="⠀", value=f"**Найм:** <t:{найм_timestamp}:t>", inline=False)
    embed.add_field(name="⠀", value=f"**Сервер:** Камасільва 5 *(уточнити в ПМ)*", inline=False)
    embed.add_field(name="⠀", value=f"**Старт:** <t:{start_timestamp}:t>, після босів LoML", inline=False)
    embed.add_field(name="⠀", value="**Шлях:** Хан → Бруд → Феррід → CTG на Футурума *(між босами 3–4 хв)*", inline=False)
    embed.add_field(name="⠀", value="**Боси:** 3 рівня", inline=False)
    embed.add_field(name="⠀", value="**Примітка:** Якщо ви забукіровали місце в альянсі, не протискайте прийняти до відведеного часу.", inline=False)
    embed.add_field(name="⠀", value=f"**Слотів:** {raid_data['taken']} ✅ **Залишилось:** {залишилось}", inline=False)

    embed.set_footer(
        text="Silent Concierge by Myxa | Найм активний",
        icon_url=bot.user.avatar.url if bot.user.avatar else bot.user.default_avatar.url
    )
    return embed

class RaidModal(discord.ui.Modal, title="🛠️ Створити найм"):
    date = discord.ui.TextInput(label="Дата (dd.mm.yyyy)", max_length=10)
    start_time = discord.ui.TextInput(label="Старт (hh:mm)", max_length=5)
    hire_time = discord.ui.TextInput(label="Найм (hh:mm)", max_length=5)
    nick = discord.ui.TextInput(label="Нік", max_length=50)
    slots = discord.ui.TextInput(label="Кількість слотів", max_length=2)

    async def on_submit(self, interaction: Interaction):
        raid_data['date'] = self.date.value
        raid_data['time'] = self.start_time.value
        raid_data['найм'] = self.hire_time.value
        raid_data['nick'] = self.nick.value
        raid_data['slots'] = int(self.slots.value)
        raid_data['taken'] = 0
        raid_data['is_closed'] = False
        raid_data['channel_id'] = interaction.channel.id

        embed = build_embed(interaction.client, interaction.user.id)
        msg = await interaction.channel.send(embed=embed, view=RaidView(interaction.client, interaction.user.id))
        raid_data['message_id'] = msg.id
        await interaction.response.send_message("✅ Найм створено!", ephemeral=True)

class RaidView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="🗑️ Відмінити найм", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: Interaction, button: discord.ui.Button):
        channel = self.bot.get_channel(raid_data['channel_id'])
        message = await channel.fetch_message(raid_data['message_id'])
        await message.delete()
        await interaction.response.send_message("🗑️ Найм скасовано!", ephemeral=True)
        for key in raid_data:
            raid_data[key] = 0 if isinstance(raid_data[key], int) else None
        raid_data['is_closed'] = False

    @discord.ui.button(label="❌ Завершити найм", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: Interaction, button: discord.ui.Button):
        raid_data['is_closed'] = True
        await self.update_embed(interaction)

    async def update_embed(self, interaction: Interaction):
        user_tz = pytz.timezone(get_timezone_for_user(self.user_id))
        full_date = datetime.datetime.strptime(raid_data['date'], "%d.%m.%Y")
        hour, minute = map(int, raid_data['time'].split(":"))
        combined = datetime.datetime.combine(full_date.date(), datetime.time(hour, minute))
        start_time = user_tz.localize(combined)
        now = datetime.datetime.now(user_tz)
        if not raid_data['is_closed'] and (raid_data['taken'] >= raid_data['slots'] or now >= start_time):
            raid_data['is_closed'] = True
        channel = self.bot.get_channel(raid_data['channel_id'])
        message = await channel.fetch_message(raid_data['message_id'])
        await message.edit(embed=build_embed(self.bot, self.user_id), view=self)
        await interaction.response.defer()

class RaidCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="raid", description="Створити новий найм")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def raid(self, interaction: Interaction):
        await interaction.response.send_modal(RaidModal())

async def setup(bot):
    await bot.add_cog(RaidCog(bot))
