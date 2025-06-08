# cogs/Vell1_cog.py
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Select, Modal, TextInput
from datetime import datetime
import pytz

DEFAULT_TZ = "Europe/London"

class Vell(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.posts = {}  # {channel_id: message_id}
        self.vell_config = {}

    def build_active_embed(self, user: discord.User):
        timezone = pytz.timezone(DEFAULT_TZ)
        now = datetime.now(timezone)

        vell_dt = now.replace(hour=15, minute=0, second=0, microsecond=0)
        vell_timestamp = int(vell_dt.timestamp())
        departure_timestamp = int(self.vell_config['departure_time'].timestamp())

        embed = discord.Embed(
            description="<:Vell:1375254921259257906> Давай з нами за серцем Велла, чи за 4 кронами <:crone:1375254950925438986>",
            color=discord.Color.teal()
        )
        embed.set_author(
            name="Платун на Велла з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
            icon_url="https://raw.githubusercontent.com/Myxa83/silentconcierge/main/vell_title_icon.png"
        )
        embed.add_field(
            name="**📜 Статус:**",
            value="```ansi\n\u001b[0;36mАКТИВНИЙ\u001b[0m\n```",
            inline=False
        )
        embed.add_field(
            name="**🐙 Велл:**",
            value=f"<t:{vell_timestamp}:t> *(локальний час)*",
            inline=False
        )
        embed.add_field(
            name="**📌 Шепотіть:**",
            value=f"```ansi\n\u001b[0;31m{self.vell_config['responsible']}\u001b[0m\n```",
            inline=False
        )
        embed.add_field(
            name="**🏝️ Сервер**",
            value=self.vell_config['server'],
            inline=False
        )
        embed.add_field(
            name="**⏰ Вирушаємо о:**",
            value=f"<t:{departure_timestamp}:t> *(локальний час)*",
            inline=False
        )
        embed.add_field(
            name="**⛵ Платун вирушає з:**",
            value=self.vell_config['place'],
            inline=False
        )
        embed.set_image(url="https://raw.githubusercontent.com/Myxa83/silentconcierge/main/raw.png")
        embed.set_footer(
            text="Silent Concierge by Myxa | Швидше за таранькой - пиво гріється",
            icon_url=user.display_avatar.url
        )
        return embed

    def build_final_embed(self, user: discord.User):
        timezone = pytz.timezone(DEFAULT_TZ)
        now = datetime.now(timezone)

        vell_dt = now.replace(hour=15, minute=0, second=0, microsecond=0)
        vell_timestamp = int(vell_dt.timestamp())
        departure_timestamp = int(self.vell_config['departure_time'].timestamp())

        embed = discord.Embed(
            description="<:Vell:1375254921259257906> Дякуємо за участь! До зустрічі на наступному Веллі! <:crone:1375254950925438986>",
            color=discord.Color.from_str("#fc0303")
        )
        embed.set_author(
            name="Платун на Велла з 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲",
            icon_url="https://raw.githubusercontent.com/Myxa83/silentconcierge/main/vell_title_icon.png"
        )
        embed.add_field(
            name="**📜 Статус:**",
            value="```ansi\n\u001b[0;31mЗАВЕРШЕНО\u001b[0m\n```",
            inline=False
        )
        embed.add_field(
            name="**🐙 Велл:**",
            value=f"<t:{vell_timestamp}:t> *(локальний час)*",
            inline=False
        )
        embed.add_field(
            name="**📌 Шепотіть:**",
            value=f"```ansi\n\u001b[0;31m{self.vell_config['responsible']}\u001b[0m\n```",
            inline=False
        )
        embed.add_field(
            name="**🏝️ Сервер**",
            value=self.vell_config['server'],
            inline=False
        )
        embed.add_field(
            name="**⏰ Вирушаємо о:**",
            value=f"<t:{departure_timestamp}:t> *(локальний час)*",
            inline=False
        )
        embed.add_field(
            name="**⛵ Платун вирушає з:**",
            value=self.vell_config['place'],
            inline=False
        )
        embed.set_image(url="https://raw.githubusercontent.com/Myxa83/silentconcierge/main/Vell1.png")
        embed.set_footer(
            text="Silent Concierge by Myxa | Таранька вже померла",
            icon_url=user.display_avatar.url
        )
        return embed

    @app_commands.command(name="vell", description="Створити пост Велла в обраному каналі")
    @app_commands.checks.has_role("Модератор")
    async def vell(self, interaction: discord.Interaction):
        class VellModal(Modal, title="Створення поста Велла"):
            responsible = TextInput(label="Кому писати (Шепотіть)", placeholder="Пані Мушка", default="Пані Мушка")
            server = TextInput(label="Сервер", placeholder="EU_Kamasylvia5", default="EU_Kamasylvia5")
            departure_time = TextInput(label="Час вирушаємо (год:хв)", placeholder="16:00")
            place = TextInput(label="Звідки вирушаємо", placeholder="Око Окілу", default="Око Окілу")

            async def on_submit(self, interaction_modal: discord.Interaction):
                timezone = pytz.timezone(DEFAULT_TZ)
                now = datetime.now(timezone)

                departure_hour, departure_minute = map(int, self.departure_time.value.split(":"))
                departure_dt = now.replace(hour=departure_hour, minute=departure_minute, second=0, microsecond=0)

                self.vell_config = {
                    "responsible": self.responsible.value,
                    "server": self.server.value,
                    "departure_time": departure_dt,
                    "place": self.place.value
                }

                channels = [
                    discord.SelectOption(label=channel.name, value=str(channel.id))
                    for channel in interaction.guild.text_channels
                ]
                select = Select(placeholder="Оберіть канал для поста", options=channels[:25])
                view = View()
                view.add_item(select)

                async def select_callback(interaction_select):
                    channel_id = int(select.values[0])
                    channel = interaction.guild.get_channel(channel_id)
                    embed = self.build_active_embed(interaction_modal.user)
                    message = await channel.send(embed=embed)
                    self.posts[channel_id] = message.id
                    await interaction_select.response.send_message(f"✅ Пост створено в {channel.mention}!", ephemeral=True)

                select.callback = select_callback
                await interaction_modal.response.send_message("Оберіть канал:", view=view, ephemeral=True)

        modal = VellModal()
        await interaction.response.send_modal(modal)

    @app_commands.command(name="vell_finish", description="Завершити пост Велла")
    @app_commands.checks.has_role("Модератор")
    async def vell_finish(self, interaction: discord.Interaction):
        if not self.posts:
            await interaction.response.send_message("⚠️ Спочатку потрібно створити пост командою /vell.", ephemeral=True)
            return

        channels = [
            discord.SelectOption(label=interaction.guild.get_channel(ch_id).name, value=str(ch_id))
            for ch_id in self.posts
        ]
        select = Select(placeholder="Оберіть канал для завершення", options=channels)
        view = View()
        view.add_item(select)

        async def callback(interaction_select):
            channel_id = int(select.values[0])
            channel = interaction.guild.get_channel(channel_id)
            message_id = self.posts[channel_id]
            message = await channel.fetch_message(message_id)
            new_embed = self.build_final_embed(interaction_select.user)
            await message.edit(embed=new_embed)
            await interaction_select.response.send_message(f"✅ Пост у {channel.mention} оновлено на завершений!", ephemeral=True)

        select.callback = callback
        await interaction.response.send_message("Оберіть канал:", view=view, ephemeral=True)

    # ДОДАЙ ОЦЕ В КІНЕЦЬ:
async def setup(bot):
    await bot.add_cog(Vell(bot))