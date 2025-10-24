# -*- coding: utf-8 -*-
import os
import random
import discord
from discord.ext import commands
from discord import app_commands, Interaction, SelectOption
from discord.ui import View, Modal, TextInput, Select, Button

# ---------------- CONFIG ----------------
MODERATOR_ROLE_ID = 1375070910138028044  # твій ID ролі модератора
FOOTER_TEXT = "Silent Concierge by Myxa"

# ---------------- HELPERS ----------------
def convert_github_blob_to_raw(url: str) -> str:
    """Якщо це GitHub blob-посилання — конвертуємо в raw. Інакше повертаємо як є."""
    if url and "github.com" in url and "/blob/" in url:
        return url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    return url

def normalize_image_url(url: str) -> str:
    """Підтримує будь-які прямі URL (Discord CDN, GitHub raw, Imgur direct тощо)."""
    if not url:
        return None
    url = url.strip()
    url = convert_github_blob_to_raw(url)
    return url if url.lower().startswith(("http://", "https://")) else None

def random_anon_name() -> str:
    """Генерує випадковий підпис для анонімного посту."""
    animals = ["Bee", "Fox", "Otter", "Dove", "Sparrow", "Cat", "Wolf", "Hedgehog", "Lynx"]
    return f"Anonymous {random.choice(animals)} #{random.randint(1, 999):03}"

# ---------------- UI ----------------
class ChannelSelectView(View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=60)
        self.bot = bot
        self.select = Select(placeholder="Оберіть канал для публікації", min_values=1, max_values=1)

        for channel in bot.get_all_channels():
            if isinstance(channel, discord.TextChannel):
                self.select.append_option(SelectOption(label=channel.name, value=str(channel.id)))

        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        selected_channel_id = int(self.select.values[0])
        await interaction.response.send_modal(PostModal(self.bot, selected_channel_id))

class PostModal(Modal, title="Створити пост у вибраний канал"):
    def __init__(self, bot: commands.Bot, channel_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.channel_id = channel_id

        self.text = TextInput(
            label="Текст повідомлення",
            style=discord.TextStyle.paragraph,
            required=True,
            placeholder="Підтримуються абзаци й розділювачі (𓆟 ⊹ ࣪ ˖ …)"
        )
        self.image_url = TextInput(
            label="URL зображення (необов'язково)",
            required=False,
            placeholder="Пряме посилання або GitHub raw / Discord CDN"
        )
        self.add_item(self.text)
        self.add_item(self.image_url)

    async def on_submit(self, interaction: Interaction):
        channel = self.bot.get_channel(self.channel_id)
        if not channel:
            await interaction.response.send_message("❌ Канал не знайдено.", ephemeral=True)
            return

        # Кнопка вибору публікації — анонімно чи ні
        class AnonChoiceView(View):
            def __init__(self, modal, channel, text, image_url):
                super().__init__(timeout=60)
                self.modal = modal
                self.channel = channel
                self.text = text
                self.image_url = image_url

            @discord.ui.button(label="🕵️‍♀️ Анонімно", style=discord.ButtonStyle.secondary)
            async def anon_btn(self, button, i: Interaction):
                await self.send_post(i, anonymous=True)

            @discord.ui.button(label="👤 Від мого імені", style=discord.ButtonStyle.success)
            async def public_btn(self, button, i: Interaction):
                await self.send_post(i, anonymous=False)

            async def send_post(self, i: Interaction, anonymous: bool):
                # Формуємо ембед
                embed = discord.Embed(description=self.text, color=discord.Color.teal())
                img_url = normalize_image_url(self.image_url)
                if img_url:
                    embed.set_image(url=img_url)

                # Якщо не анонімно — показуємо автора
                if not anonymous:
                    author = i.user
                    author_link = f"https://discord.com/users/{author.id}"
                    embed.add_field(
                        name="Автор:",
                        value=f"[{author.display_name}]({author_link})",
                        inline=False
                    )
                    embed.set_thumbnail(url=author.display_avatar.url)
                else:
                    # Анонімний підпис
                    anon_name = random_anon_name()
                    embed.add_field(
                        name="Автор:",
                        value=anon_name,
                        inline=False
                    )

                # Футер — стандартний
                embed.set_footer(
                    text=FOOTER_TEXT,
                    icon_url=i.client.user.display_avatar.url
                )

                await self.channel.send(embed=embed)
                await i.response.send_message(
                    f"✅ {'Анонімне ' if anonymous else ''}повідомлення надіслано в {self.channel.mention}",
                    ephemeral=True
                )
                self.stop()

        await interaction.response.send_message(
            "Оберіть спосіб публікації:",
            view=AnonChoiceView(self, channel, self.text.value, self.image_url.value),
            ephemeral=True
        )

# ---------------- COG ----------------
class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="допис", description="Створити пост з текстом та зображенням у вибраний канал")
    async def допис(self, interaction: Interaction):
        if not any(role.id == MODERATOR_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message("❌ Лише модератори можуть користуватись цією командою.", ephemeral=True)
            return

        view = ChannelSelectView(self.bot)
        await interaction.response.send_message("Оберіть канал нижче, щоб створити пост:", view=view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))