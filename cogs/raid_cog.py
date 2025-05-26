import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
import datetime
import pytz
import os
from dotenv import load_dotenv
from cogs.timezone_cog import get_timezone_for_user

# Завантаження токена
load_dotenv()

# Дані про найм
raid_data = {
    'slots': 0,
    'taken': 0,
    'is_closed': False,
    'channel_id': None,
    'message_id': None,
    'date': None,
    'time': None,
    'найм': None,
    'server': None,
    'nick': None
}

def build_embed(bot, user_id):
    print(f"[DEBUG] 🔄 Створення ембеду для {raid_data['date']} {raid_data['time']} — {raid_data['taken']}/{raid_data['slots']}")
    залишилось = max(0, raid_data['slots'] - raid_data['taken'])
    status = (
        "```ansi\n[2;31mЗАКРИТО[0m```"
        if raid_data['is_closed'] else
        "```ansi\n[2;36mВІДКРИТО[0m```"
    )
    embed_color = discord.Color.teal() if not raid_data['is_closed'] else discord.Color.red()

    user_tz = pytz.timezone(get_timezone_for_user(user_id))
    full_date = datetime.datetime.strptime(raid_data['date'], "%d.%m.%Y")
    date_timestamp = int(user_tz.localize(full_date).timestamp())

    embed = Embed(
        title=f"<:00000005_special:1376430317270995024> Гільдійні боси з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
        description=f"📅 <t:{date_timestamp}:D>",
        color=embed_color
    )

    embed.set_image(url="https://i.imgur.com/CNtxvsV.jpeg" if raid_data['is_closed'] else "https://i.imgur.com/5GvjWCd.jpeg")

    hour, minute = map(int, raid_data['time'].split(":"))
    combined = datetime.datetime.combine(full_date.date(), datetime.time(hour, minute))
    start_timestamp = int(user_tz.localize(combined).timestamp())
    embed.add_field(name="**⏰ Старт:**", value=f"**<t:{start_timestamp}:t>**, після босів **LoML**", inline=False)

    embed.add_field(name="**🏝️ Сервер:**", value=f"**{raid_data['server']}** *(уточнити в ПМ)*", inline=False)

    найм_hour, найм_minute = map(int, raid_data['найм'].split(":"))
    найм_combined = datetime.datetime.combine(full_date.date(), datetime.time(найм_hour, найм_minute))
    найм_timestamp = int(user_tz.localize(найм_combined).timestamp())
    embed.add_field(name="**⏰ Найм:**", value=f"**<t:{найм_timestamp}:F>** *(локальний час)*", inline=True)

    embed.add_field(
        name="**📌 Шепотіть:**",
        value=f"```ansi\n[0;31m{raid_data['nick']}\u001b[0m```",
        inline=False)
    embed.add_field(name="**🛤️ Шлях:**", value="**Хан → Бруд → Феррід → CTG на Футурума** *(між босами 3–4 хв)*", inline=False)
    embed.add_field(name="**🐙 Бос:**", value="**3 рівня**", inline=False)
    embed.add_field(name="**📌 Примітка:**", value="**Якщо ви забукіровали місце в альянсі, не протискайте прийняти до відведеного часу.**", inline=False)
    embed.add_field(name="**🧮  Слоти:**", value=f"**{raid_data['taken']} ✅ Залишилось: {залишилось}**", inline=False)
    embed.add_field(name="**🧾 Статус:**", value=status, inline=False)

    embed.set_footer(
        text="Sіlent Cove | Найм активний" if not raid_data['is_closed']
        else "Silent Cove | Ще побачимось наступного найму!",
        icon_url=bot.user.avatar.url if bot.user.avatar else bot.user.default_avatar.url
    )

    return embed

class RaidView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="🗑️ Відмінити найм", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: Interaction, button: discord.ui.Button):
        print(f"[DEBUG] 🗑️ {interaction.user.display_name} тисне 'Відмінити найм'")
        channel = self.bot.get_channel(raid_data['channel_id'])
        message = await channel.fetch_message(raid_data['message_id'])
        await message.delete()
        await interaction.response.send_message("🗑️ Найм скасовано!", ephemeral=True)
        for key in raid_data:
            raid_data[key] = 0 if isinstance(raid_data[key], int) else None
        raid_data['is_closed'] = False

    @discord.ui.button(label="❌ Завершити найм", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: Interaction, button: discord.ui.Button):
        print(f"[DEBUG] ❌ {interaction.user.display_name} тисне 'Завершити найм'")
        raid_data['is_closed'] = True
        await self.update_embed(interaction)

    async def update_embed(self, interaction: Interaction):
        print("[DEBUG] 🔁 Оновлення ембеду...")
        user_tz = pytz.timezone(get_timezone_for_user(self.user_id))
        full_date = datetime.datetime.strptime(raid_data['date'], "%d.%m.%Y")
        hour, minute = map(int, raid_data['time'].split(":"))
        combined = datetime.datetime.combine(full_date.date(), datetime.time(hour, minute))
        start_time = user_tz.localize(combined)
        now = datetime.datetime.now(user_tz)

        if not raid_data['is_closed']:
            print("[DEBUG] Найм відкритий. Перевіряємо умови автозакриття...")
            if raid_data['taken'] >= raid_data['slots'] or now >= start_time:
                raid_data['is_closed'] = True
                print("[DEBUG] 🚫 Найм автоматично закрито!")

        channel = self.bot.get_channel(raid_data['channel_id'])
        message = await channel.fetch_message(raid_data['message_id'])
        new_embed = build_embed(self.bot, self.user_id)
        await message.edit(embed=new_embed, view=self)
        await interaction.response.defer()

class RaidModal(discord.ui.Modal, title="🛠️ Створити найм"):
    day = discord.ui.TextInput(label="День (dd)", max_length=2)
    month = discord.ui.TextInput(label="Місяць (mm)", max_length=2)
    year = discord.ui.TextInput(label="Рік (yyyy)", max_length=4)
    start_hour = discord.ui.TextInput(label="Година старту (hh)", max_length=2)
    start_minute = discord.ui.TextInput(label="Хвилина старту (mm)", max_length=2)
    hire_hour = discord.ui.TextInput(label="Година найму (hh)", max_length=2)
    hire_minute = discord.ui.TextInput(label="Хвилина найму (mm)", max_length=2)
    nick = discord.ui.TextInput(label="Нік", max_length=50)
    server = discord.ui.TextInput(label="Сервер", max_length=50)
    slots = discord.ui.TextInput(label="Кількість слотів", max_length=2)

    async def on_submit(self, interaction: Interaction):
        print(f"[DEBUG] 📥 Надіслано форму створення найму від {interaction.user.display_name}")
        raid_data['date'] = f"{self.day.value.zfill(2)}.{self.month.value.zfill(2)}.{self.year.value}"
        raid_data['time'] = f"{self.start_hour.value.zfill(2)}:{self.start_minute.value.zfill(2)}"
        raid_data['найм'] = f"{self.hire_hour.value.zfill(2)}:{self.hire_minute.value.zfill(2)}"
        raid_data['nick'] = self.nick.value
        raid_data['server'] = self.server.value
        raid_data['slots'] = int(self.slots.value)
        raid_data['taken'] = 0
        raid_data['is_closed'] = False
        raid_data['channel_id'] = interaction.channel.id

        embed = build_embed(interaction.client, interaction.user.id)
        msg = await interaction.channel.send(embed=embed, view=RaidView(interaction.client, interaction.user.id))
        raid_data['message_id'] = msg.id

        print(f"[RAID] ✅ Найм створено: {raid_data['date']} о {raid_data['time']} | Слоти: {raid_data['slots']}")
        await interaction.response.send_message("✅ Найм створено!", ephemeral=True)

class RaidCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="add", description="Додати учасників до найму")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add(self, interaction: Interaction, кількість: int):
        raid_data['taken'] += кількість
        view = RaidView(self.bot, interaction.user.id)
        await view.update_embed(interaction)
        await interaction.response.send_message(f"✅ Додано {кількість} учасників", ephemeral=True)

    @app_commands.command(name="remove", description="Видалити учасників з найму")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: Interaction, кількість: int):
        raid_data['taken'] = max(0, raid_data['taken'] - кількість)
        view = RaidView(self.bot, interaction.user.id)
        await view.update_embed(interaction)
        await interaction.response.send_message(f"✅ Видалено {кількість} учасників", ephemeral=True)

    @app_commands.command(name="raid", description="Створити новий найм")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def raid(self, interaction: Interaction):
        print(f"[DEBUG] 🚀 Команда /raid від {interaction.user.display_name} ({interaction.user.id})")
        try:
            await interaction.response.send_modal(RaidModal())
            print("[DEBUG] ✅ Modal успішно надіслано")
        except Exception as e:
            print(f"[ERROR] ❌ Не вдалося показати Modal: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(RaidView(self.bot, user_id=0))  # Реєстрація View
        print("[DEBUG] ✅ RaidView зареєстровано")

async def setup(bot):
    cog = raid_cog(bot)
    await bot.add_cog(cog)
