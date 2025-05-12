from discord.ext import commands
from discord import app_commands, Interaction, Embed, TextChannel
import discord
import datetime
import pytz

raid_data = {
    'slots': 0,
    'taken': 0,
    'is_closed': False,
    'channel_id': None,
    'message_id': None
}

class RaidCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def build_embed(self):
        timestamp = getattr(self, 'timestamp', int(datetime.datetime.now().timestamp()))
        закрито = raid_data['is_closed']
        залишилось = max(0, raid_data['slots'] - raid_data['taken'])

        # ANSI-рядок статусу
        status_block = (
            "```ansi\n[0;31mЗАКРИТО[0m\n```"
            if закрито else
            "```ansi\n[0;32mВІДКРИТО[0m\n```"
        )

        # ANSI-нік в рамці
        nickname_block = f"```ansi\n[0;31m{self.nickname}[0m\n```"

        description = (
            f"📅 **Дата:** <t:{timestamp}:D>\n"
            f"{status_block}\n"
        )

        if закрито:
            description += "**🟥 НАЙМ ЗАВЕРШЕНО**\n"
        else:
            description += (
                f"📌 **Шепотіть:\n{nickname_block}**\n\n"
                f"⏰ **Найм:** <t:{timestamp}:t> *(можу бути afk)* **Винагорода буде роздаватись одразу, тому почекайте 5 хвилин після заходу й чекніть нагороду.**\n\n"
                f"🏝️ **Сервер: {self.server} *(уточніть в ПМ)* **\n\n"
                f"⏰ **Старт: {self.start_time}, після босів LoML**\n\n"
                f"🛤️ **Шлях: Хан → Бруд → Феррід → CTG на Футурума *(між босами 3–4 хв)* **\n\n"
                f"🐙 **Боси: 3 рівня**\n\n"
                f"📌 **Примітка: Якщо ви забукіровали місце в альянсі, не протискайте прийняття до відведеного часу.**\n\n"
                f"🧮 **Слотів:** {raid_data['slots']} ✅ **Залишилось:** {залишилось}"
            )

        embed = Embed(
            title="**✨ Гільдійні боси з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲**",
            description=description,
            colour=discord.Color.red() if закрито else discord.Color.from_str("#00f0dc")
        )

        image_url = "https://i.imgur.com/CNtxvsV.jpeg" if закрито else "https://i.imgur.com/Mt7OfAO.jpeg"
        embed.set_image(url=image_url)

        footer_text = "Silent Concierge by Myxa | 🟥 НАЙМ ЗАВЕРШЕНО" if закрито else "Silent Concierge by Myxa | Найм активний"
        embed.set_footer(text=footer_text)
        return embed

    @app_commands.command(name="найм", description="Створити найм")
    @app_commands.describe(
        дата="Дата проведення (дд.мм.рррр)",
        найм="Час початку найму (год:хв, 24г формат)",
        старт="Старт активності",
        сервер="Сервер",
        нік="Ваш нік",
        кількість="Кількість слотів",
        канал="Канал, куди надіслати"
    )
    async def найм(self, interaction: Interaction, дата: str, найм: str, старт: str, сервер: str, нік: str, кількість: int, канал: TextChannel):
        try:
            datetime_str = f"{дата} {найм}"
            british = pytz.timezone("Europe/London")
            raid_dt = datetime.datetime.strptime(datetime_str, "%d.%m.%Y %H:%M")
            raid_dt = british.localize(raid_dt)
            self.timestamp = int(raid_dt.timestamp())
        except Exception as e:
            await interaction.response.send_message(f"❌ Помилка дати/часу: {e}", ephemeral=True)
            return

        self.nickname = нік
        self.server = сервер
        self.start_time = старт

        raid_data['slots'] = кількість
        raid_data['taken'] = 0
        raid_data['is_closed'] = False
        raid_data['channel_id'] = канал.id

        embed = self.build_embed()
        message = await канал.send(embed=embed)
        raid_data['message_id'] = message.id

        await interaction.response.send_message(f"✅ Найм надіслано в канал {канал.mention}", ephemeral=True)

    async def update_embed(self, interaction: Interaction):
        channel = interaction.guild.get_channel(raid_data['channel_id'])
        try:
            message = await channel.fetch_message(raid_data['message_id'])
            embed = self.build_embed()
            await message.edit(embed=embed)
        except:
            pass

    @app_commands.command(name="add", description="Додати учасників")
    @app_commands.describe(кількість="Кількість (за замовчуванням 1)")
    async def add(self, interaction: Interaction, кількість: int = 1):
        if raid_data['is_closed']:
            await interaction.response.send_message("❌ Найм уже закрито.", ephemeral=True)
            return

        raid_data['taken'] += кількість
        if raid_data['taken'] >= raid_data['slots']:
            raid_data['is_closed'] = True

        await self.update_embed(interaction)
        await interaction.response.send_message(f"✅ Додано {кількість} учасників.", ephemeral=True)

    @app_commands.command(name="remove", description="Видалити учасників")
    @app_commands.describe(кількість="Кількість (за замовчуванням 1)")
    async def remove(self, interaction: Interaction, кількість: int = 1):
        raid_data['taken'] = max(0, raid_data['taken'] - кількість)
        raid_data['is_closed'] = False
        await self.update_embed(interaction)
        await interaction.response.send_message(f"♻️ Видалено {кількість} учасників.", ephemeral=True)

    @app_commands.command(name="закрити", description="Закрити найм вручну")
    async def закрити(self, interaction: Interaction):
        raid_data['is_closed'] = True
        await self.update_embed(interaction)
        await interaction.response.send_message("🚪 Найм вручну закрито.", ephemeral=True)

    @app_commands.command(name="скинути", description="Скинути всі дані про найм")
    async def скинути(self, interaction: Interaction):
        raid_data.update({'slots': 0, 'taken': 0, 'is_closed': False, 'channel_id': None, 'message_id': None})
        await interaction.response.send_message("🔄 Усі дані про найм скинуто.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(RaidCog(bot))