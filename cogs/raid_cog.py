import discord
from discord.ext import commands
from discord import app_commands, Embed
import datetime
import pytz
import os
from dotenv import load_dotenv
import asyncio

load_dotenv()

raid_data = {
    'date': None,
    'time': None,
    'найм': None,
    'нік': None,
    'сервер': None,
    'слоти': 0,
    'taken': 0,
    'is_closed': False,
    'channel_id': None,
    'message_id': None,
    'created_at': None
}

class RaidCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("[DEBUG] Ініціалізація RaidCog")

    @commands.Cog.listener()
    async def on_ready(self):
        if not hasattr(self.bot, "synced"):
            self.bot.synced = True
            try:
                guild = discord.Object(id=1323454227816906802)
                await self.bot.tree.sync(guild=guild)
                print(f"[DEBUG] ✅ Slash-команди синхронізовано на сервері {guild.id}")
            except Exception as e:
                print(f"[DEBUG] ❌ Помилка синхронізації команд: {e}")

    @app_commands.command(name="raid", description="Створити новий найм")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def raid(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RaidModal())

class RaidModal(discord.ui.Modal, title="Створення найму на рейд"):
    день = discord.ui.TextInput(label="День", placeholder="Наприклад: 02", required=True)
    місяць = discord.ui.TextInput(label="Місяць", placeholder="Наприклад: 06", required=True)
    рік = discord.ui.TextInput(label="Рік", placeholder="2025", required=True)
    година = discord.ui.TextInput(label="Година", placeholder="03", required=True)
    хвилина = discord.ui.TextInput(label="Хвилина", placeholder="29", required=True)

    канал = discord.ui.TextInput(label="Канал ID або посилання", placeholder="ID або #назва", required=True)
    нік = discord.ui.TextInput(label="Нік відповідального", placeholder="Шепотіть", required=True)
    сервер = discord.ui.TextInput(label="Сервер", placeholder="Око Окілу", required=True)
    слоти = discord.ui.TextInput(label="Кількість слотів", placeholder="5", required=True)
    найм_час = discord.ui.TextInput(label="Час найму (ГГ:ХХ)", placeholder="04:00", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        print(f"[DEBUG] {interaction.user.display_name} заповнив форму найму.")
        try:
            raid_data['date'] = f"{self.день.value.zfill(2)}.{self.місяць.value.zfill(2)}.{self.рік.value}"
            raid_data['time'] = f"{self.година.value.zfill(2)}:{self.хвилина.value.zfill(2)}"
            raid_data['найм'] = self.найм_час.value
            raid_data['нік'] = self.нік.value
            raid_data['сервер'] = self.сервер.value
            raid_data['слоти'] = int(self.слоти.value)
            raid_data['taken'] = 0
            raid_data['is_closed'] = False
            raid_data['created_at'] = datetime.datetime.now(pytz.utc)

            if self.канал.value.startswith('<#'):
                raid_data['channel_id'] = int(self.канал.value.strip('<#>'))
            else:
                raid_data['channel_id'] = int(self.канал.value)

            await asyncio.sleep(3)  # Додали тайм-аут 3 секунди перед постінгом

            await self.post_raid(interaction)
        except Exception as e:
            print(f"[DEBUG] ❌ Помилка при обробці форми: {e}")
            await interaction.response.send_message("❌ Помилка при обробці даних. Перевірте заповнені поля.", ephemeral=True)

    async def post_raid(self, interaction: discord.Interaction):
        embed = self.build_embed(interaction.client)
        канал = interaction.guild.get_channel(raid_data['channel_id'])

        if канал:
            message = await канал.send(embed=embed)
            raid_data['message_id'] = message.id
            await interaction.response.send_message("✅ Найм створено!", ephemeral=True)
        else:
            await interaction.response.send_message("⛔ Канал не знайдено.", ephemeral=True)

    def build_embed(self, bot):
        embed_color = discord.Color.red() if raid_data['is_closed'] else discord.Color.teal()
        embed = Embed(
            title="<:00000005_special:1376430317270995024> Гільдійні боси з Silent Cove",
            description=f"📅 {raid_data['date']}",
            color=embed_color
        )
        embed.set_image(url="https://i.imgur.com/CNtxvsV.jpeg" if raid_data['is_closed'] else "https://i.imgur.com/5GvjWCd.jpeg")

        embed.add_field(name="⏰ Старт:", value=raid_data['time'], inline=False)
        embed.add_field(name="⏰ Найм:", value=raid_data['найм'], inline=True)
        embed.add_field(name="📌 Шепотіть:", value=f"```ansi\n\u001b[0;31m{raid_data['нік']}\u001b[0m```", inline=False)
        embed.add_field(name="🏝️ Сервер:", value=raid_data['сервер'], inline=False)
        embed.add_field(name="🛤️ Шлях:", value="Хан → Бруд → Феррід → CTG на Футурума (між босами 3–4 хв)", inline=False)
        embed.add_field(name="🐙 Бос:", value="3 рівня", inline=False)
        embed.add_field(name="🧮  Слоти:", value=f"{raid_data['taken']} ✅ Залишилось: {raid_data['слоти'] - raid_data['taken']}", inline=False)
        embed.add_field(name="🧾 Статус:", value="ВІДКРИТО", inline=False)

        footer_text = "Silent Cove | Ще побачимось наступного найму!" if raid_data['is_closed'] else "Silent Cove | Найм активний"
        avatar_url = bot.user.avatar.url if bot.user.avatar else bot.user.default_avatar.url
        embed.set_footer(text=footer_text, icon_url=avatar_url)

        return embed

async def setup(bot):
    await bot.add_cog(RaidCog(bot))
