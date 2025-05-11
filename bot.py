import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction, Embed
import asyncio
import datetime
import pytz
import os
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

raid_data = {
    'slots': 0,
    'taken': 0,
    'is_closed': False,
    'channel_id': None,
    'message_id': None
}

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"🔌 Бот увійшов як {bot.user} (ID: {bot.user.id})")
    print("✅ Slash-команди синхронізовано.")

@bot.tree.command(name="debug", description="Перевірка активності бота")
async def debug(interaction: Interaction):
    await interaction.response.send_message("✅ Бот активний і працює.")

@bot.tree.command(name="add", description="Додає учасників до найму (за замовчуванням 1)")
@app_commands.describe(count="Кількість учасників")
async def add(interaction: Interaction, count: int = 1):
    if raid_data['is_closed']:
        await interaction.response.send_message("❌ Найм уже закрито.", ephemeral=True)
        return
    raid_data['taken'] += count
    remaining = raid_data['slots'] - raid_data['taken']
    await interaction.response.send_message(f"✅ Додано {count} учасників. Залишилось: {remaining} слотів.")

@bot.tree.command(name="remove", description="Видаляє учасників з найму")
@app_commands.describe(count="Кількість учасників")
async def remove(interaction: Interaction, count: int = 1):
    raid_data['taken'] = max(0, raid_data['taken'] - count)
    remaining = raid_data['slots'] - raid_data['taken']
    await interaction.response.send_message(f"✅ Видалено {count} учасників. Залишилось: {remaining} слотів.")

@bot.tree.command(name="закрити", description="Закриває найм вручну")
async def close(interaction: Interaction):
    raid_data['is_closed'] = True
    await interaction.response.send_message("🔒 Найм закрито вручну.")

@bot.tree.command(name="скинути", description="Скидає всі дані про найм")
async def reset(interaction: Interaction):
    raid_data.update({'slots': 0, 'taken': 0, 'is_closed': False, 'channel_id': None, 'message_id': None})
    await interaction.response.send_message("🔄 Дані найму скинуто.")

@bot.tree.command(name="найм", description="Створює найм у вказаному каналі")
@app_commands.describe(
    date="Дата найму",
    recruit_time="Час найму",
    start_time="Час старту",
    server="Сервер",
    nickname="Нік шепотіння",
    slots="Кількість слотів",
    channel_name="Канал для найму"
)
async def raid_post(interaction: Interaction, date: str, recruit_time: str, start_time: str, server: str, nickname: str, slots: int, channel_name: str):
    if not any(role.name == "Менеджмент" for role in interaction.user.roles):
        await interaction.response.send_message("⛔ У вас немає прав для цієї команди.", ephemeral=True)
        return

    raid_data['slots'] = slots
    raid_data['taken'] = 0
    raid_data['is_closed'] = False

    channel = discord.utils.get(interaction.guild.text_channels, name=channel_name)
    if not channel:
        await interaction.response.send_message(f"❌ Канал з назвою '{channel_name}' не знайдено.", ephemeral=True)
        return

    now = datetime.datetime.now(pytz.timezone("Europe/London"))
    recruit_timestamp = int(now.timestamp())
    start_timestamp = int((now + datetime.timedelta(hours=1)).timestamp())
    remaining = slots

    embed = Embed(
        title="✨ Гільдійні боси з Ｓｉｌｅｎｔ Ｃｏｖｅ",
        description=(
            f"📅 **Дата: {date}**\n\n"
            f"📌 **Шепотіть:**\n```ansi\n\u001b[0;31m{nickname}\u001b[0m\n```\n\n"
            f"⏰ **Найм:** <t:{recruit_timestamp}:t> *(можу бути афк)*\n\n"
            f"🏝️ **Сервер: {server}**\n\n"
            f"⏰ **Старт:** <t:{start_timestamp}:t>\n\n"
            f"🛤️ **Шлях: Хан → Бруд → Феррід → CTG на Футурума**\n\n"
            f"🐙 **Боси: 3 рівня**\n\n"
            f"📌 **Не протискайте прийняття до часу.**\n\n"
            f"🧾 **Слотів:** {slots}    ✅ **Залишилось:** {remaining}"
        ),
        color=0x00ffcc
    )

    msg = await channel.send(embed=embed)
    await interaction.response.send_message(f"✅ Найм створено в <#{channel.id}>", ephemeral=True)

    if msg:
        raid_data['channel_id'] = channel.id
        raid_data['message_id'] = msg.id

    async def auto_close():
        while not raid_data['is_closed']:
            await asyncio.sleep(30)
            current_time = datetime.datetime.now(pytz.timezone("Europe/London"))
            if current_time.hour == 17 and current_time.minute == 59:
                raid_data['is_closed'] = True
                embed.color = 0xff3333
                embed.title = "🔒 **НАЙМ ЗАВЕРШЕНО**"
                embed.description += "\n\n🔴 **НАЙМ ЗАКРИТО — ЧАС ЗАВЕРШЕННЯ**"
                await msg.edit(embed=embed)
                break

    bot.loop.create_task(auto_close())

async def run():
    async with bot:
        await bot.start(os.getenv("DISCORD_TOKEN"))

asyncio.run(run())
