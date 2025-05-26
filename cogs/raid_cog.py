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
    'nick': None
}

def build_embed(bot, user_id):
    print(f"[DEBUG] 🔄 Створення ембеду для {raid_data['date']} {raid_data['time']} — {raid_data['taken']}/{raid_data['slots']}")
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
        title=f"<:00000005_special:1376430317270995024> Гільдійні боси з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
        description=f"📅 <t:{date_timestamp}:D>",
        color=embed_color
    )

    embed.set_image(url="https://i.imgur.com/CNtxvsV.jpeg" if raid_data['is_closed'] else "https://i.imgur.com/5GvjWCd.jpeg")

    hour, minute = map(int, raid_data['time'].split(":"))
    combined = datetime.datetime.combine(full_date.date(), datetime.time(hour, minute))
    start_timestamp = int(user_tz.localize(combined).timestamp())
    embed.add_field(name="**⏰ Старт:**", value=f"**<t:{start_timestamp}:t>**, після босів **LoML**", inline=False)

    найм_hour, найм_minute = map(int, raid_data['найм'].split(":"))
    найм_combined = datetime.datetime.combine(full_date.date(), datetime.time(найм_hour, найм_minute))
    найм_timestamp = int(user_tz.localize(найм_combined).timestamp())
    embed.add_field(name="**⏰ Найм:**", value=f"**<t:{найм_timestamp}:F>** *(можу бути afk)* **Винагорода буде роздаватись одразу, тому почекайте 5 хвилин після заходу й чекніть нагороду.**", inline=True)

    embed.add_field(
        name="**📌 Шепотіть:**",
        value=f"```ansi\n\u001b[0;31m{raid_data['nick']}\u001b[0m```",
        inline=False)
    embed.add_field(name="**🏝️ Сервер:**", value=f"**Камасільва 5** *(уточнити в ПМ)*", inline=False)
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

class RaidModal(discord.ui.Modal, title="🛠️ Створити найм"):
    day = discord.ui.TextInput(label="День (dd)", max_length=2)
    month = discord.ui.TextInput(label="Місяць (mm)", max_length=2)
    year = discord.ui.TextInput(label="Рік (yyyy)", max_length=4)
    start_hour = discord.ui.TextInput(label="Година старту (hh)", max_length=2)
    start_minute = discord.ui.TextInput(label="Хвилина старту (mm)", max_length=2)
    hire_hour = discord.ui.TextInput(label="Година найму (hh)", max_length=2)
    hire_minute = discord.ui.TextInput(label="Хвилина найму (mm)", max_length=2)
    nick = discord.ui.TextInput(label="Нік", max_length=50)
    slots = discord.ui.TextInput(label="Кількість слотів", max_length=2)

    async def on_submit(self, interaction: Interaction):
        print(f"[DEBUG] 📥 Надіслано форму створення найму від {interaction.user.display_name}")
        raid_data['date'] = f"{self.day.value.zfill(2)}.{self.month.value.zfill(2)}.{self.year.value}"
        raid_data['time'] = f"{self.start_hour.value.zfill(2)}:{self.start_minute.value.zfill(2)}"
        raid_data['найм'] = f"{self.hire_hour.value.zfill(2)}:{self.hire_minute.value.zfill(2)}"
        raid_data['nick'] = self.nick.value
        raid_data['slots'] = int(self.slots.value)
        raid_data['taken'] = 0
        raid_data['is_closed'] = False
        raid_data['channel_id'] = interaction.channel.id

        embed = build_embed(interaction.client, interaction.user.id)
        try:
            await interaction.response.send_message(embed=embed, view=RaidView(interaction.client, interaction.user.id))
            msg = await interaction.original_response()
            raid_data['message_id'] = msg.id
            print(f"[RAID] ✅ Найм створено: {raid_data['date']} о {raid_data['time']} | Слоти: {raid_data['slots']}")
        except Exception as e:
            print(f"[ERROR] ❌ Не вдалося надіслати modal або повідомлення: {e}")
