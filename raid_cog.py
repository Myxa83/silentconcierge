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
    date = discord.ui.TextInput(label="Дата (dd.mm.yyyy)", max_length=10)
    start_time = discord.ui.TextInput(label="Старт (hh:mm)", max_length=5)
    hire_time = discord.ui.TextInput(label="Найм (hh:mm)", max_length=5)
    nick = discord.ui.TextInput(label="Нік", max_length=50)
    slots = discord.ui.TextInput(label="Кількість слотів", max_length=2)

    async def on_submit(self, interaction: Interaction):
        print(f"[DEBUG] 📥 Надіслано форму створення найму від {interaction.user.display_name}")
        try:
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
            print(f"[RAID] ✅ Найм створено: {raid_data['date']} о {raid_data['time']} | Слоти: {raid_data['slots']}")
        except Exception as e:
            print(f"[ERROR] ❌ Помилка в on_submit: {e}")
            await interaction.response.send_message("❌ Помилка створення найму.", ephemeral=True)

class RaidView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=None)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="🗑️ Відмінити найм", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: Interaction, button: discord.ui.Button):
        print(f"[DEBUG] 🗑️ {interaction.user.display_name} тисне 'Відмінити найм'")
        try:
            channel = self.bot.get_channel(raid_data['channel_id'])
            message = await channel.fetch_message(raid_data['message_id'])
            await message.delete()
            await interaction.response.send_message("🗑️ Найм скасовано!", ephemeral=True)
            for key in raid_data:
                raid_data[key] = 0 if isinstance(raid_data[key], int) else None
            raid_data['is_closed'] = False
        except Exception as e:
            print(f"[ERROR] ❌ Не вдалося скасувати найм: {e}")

    @discord.ui.button(label="❌ Завершити найм", style=discord.ButtonStyle.secondary)
    async def close(self, interaction: Interaction, button: discord.ui.Button):
        print(f"[DEBUG] ❌ {interaction.user.display_name} тисне 'Завершити найм'")
        raid_data['is_closed'] = True
        await self.update_embed(interaction)

    async def update_embed(self, interaction: Interaction):
        print("[DEBUG] 🔁 Оновлення ембеду...")
        try:
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
        except Exception as e:
            print(f"[ERROR] ❌ Оновлення ембеду не вдалося: {e}")

class RaidCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="raid", description="Створити новий найм")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def raid(self, interaction: Interaction):
        print(f"[DEBUG] 🚀 Команда /raid від {interaction.user} ({interaction.user.id})")
        await interaction.response.send_modal(RaidModal())

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(RaidView(self.bot, user_id=0))
        print("[DEBUG] ✅ RaidView зареєстровано")

async def setup(bot):
    await bot.add_cog(RaidCog(bot))
