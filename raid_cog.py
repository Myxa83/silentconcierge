import discord
from discord.ext import commands
from discord import app_commands, Interaction, Embed
import datetime
import pytz
import os
from dotenv import load_dotenv

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

def build_embed(bot):
    залишилось = max(0, raid_data['slots'] - raid_data['taken'])
    status = (
        "```ansi
[2;31mЗАКРИТО[0m
```"
        if raid_data['is_closed'] else
        "```ansi
[2;36mВІДКРИТО[0m
```"
    )
    embed_color = discord.Color.teal() if not raid_data['is_closed'] else discord.Color.red()
    full_date = datetime.datetime.strptime(raid_data['date'], "%d.%m.%Y")
    date_timestamp = int(full_date.replace(tzinfo=pytz.timezone('Europe/London')).timestamp())
    embed = Embed(title=f"✨ Гільдійні боси з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲\n📅 <t:{date_timestamp}:D>", color=embed_color)
    embed.set_image(url="https://i.imgur.com/CNtxvsV.jpeg" if raid_data['is_closed'] else "https://i.imgur.com/5GvjWCd.jpeg")
    from_zone = pytz.timezone('Europe/London')
    hour, minute = map(int, raid_data['time'].split(":"))
    combined = datetime.datetime.combine(full_date.date(), datetime.time(hour, minute))
    localized_time = from_zone.localize(combined)
    timestamp = int(localized_time.timestamp())
    embed.add_field(name="**⏰ Старт:**", value=f"**<t:{timestamp}:t>**, після босів **LoML**", inline=False)
    embed.add_field(name="**🏝️ Сервер:**", value=f"**{raid_data['server']}** *(уточнити в ПМ)*", inline=False)
    найм_hour, найм_minute = map(int, raid_data['найм'].split(":"))
    найм_combined = datetime.datetime.combine(full_date.date(), datetime.time(найм_hour, найм_minute))
    найм_localized = pytz.timezone('Europe/London').localize(найм_combined)
    найм_timestamp = int(найм_localized.timestamp())
    embed.add_field(name="**⏰ Найм:**", value=f"**<t:{найм_timestamp}:F>** *(локальний час)*", inline=True)
    embed.add_field(
        name="**📌 Шепотіть:**",
        value=f"```ansi\n\u001b[0;31m{raid_data['nick']}\u001b[0m\n```", inline=False)
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

# Файл тільки для Cog. Без run().



