# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
from discord import app_commands, Interaction, SelectOption
from discord.ui import View, Modal, TextInput, Select, Button

# ---------------- CONFIG ----------------
MODERATOR_ROLE_ID = 1375070910138028044  # ID ролі модератора
FOOTER_TEXT = "Silent Concierge by Myxa"
EMBED_COLOR = 0x1F2427  # темний графіт


# ---------------- HELPERS ----------------
def convert_github_blob_to_raw(url: str) -> str:
    """Якщо це GitHub blob посилання, конвертуємо в raw. Інакше повертаємо як є."""
    if url and "github.com" in url and "/blob/" in url:
        return url.replace("github.com", "raw.githubusercontent.com").replace(
            "/blob/", "/"
        )
    return url


def build_post_embed(
    text: str,
    image_url: str | None,
    attachment: discord.Attachment | None,
    author: discord.Member | None,
) -> discord.Embed:
    """Збираємо ембед з тексту, опційного зображення та автора."""

    text = text.strip()

    # перший рядок робимо заголовком, решта йде в description
    lines = text.splitlines()
    if len(lines) > 1:
        title = lines[0].strip()
        description = "\n".join(lines[1:]).strip()
    else:
        title = None
        description = text

    embed = discord.Embed(
        title=title or None,
        description=description or None,
        color=EMBED_COLOR,
    )

    # вибираємо джерело зображення
    if attachment is not None:
        embed.set_image(url=attachment.url)
    elif image_url:
        embed.set_image(url=image_url)

    # додаємо автора тільки якщо він не анонімний
    if author is not None:
        author_line = f"\n\n**Автор:** {author.mention}"
        embed.description = (embed.description or "") + author_line

    embed.set_footer(text=FOOTER_TEXT)
    return embed


# ---------------- MODAL ----------------
class PostModal(Modal, title="Створити пост у вибраний канал"):
    def __init__(self, channel: discord.TextChannel, attachment: discord.Attachment | None):
        super().__init__(timeout=300)
        self.channel = channel
        self.attachment = attachment

        self.message_input = TextInput(
            label="Текст повідомлення",
            style=discord.TextStyle.paragraph,
            placeholder="Підтримуються абзаци, емодзі, теги ролей та посилання",
            required=True,
            max_length=4000,
        )

        self.image_url_input = TextInput(
            label="URL зображення (необовʼязково)",
            style=discord.TextStyle.short,
            placeholder="Пряме посилання або GitHub raw / Discord CDN",
            required=False,
            max_length=500,
        )

        self.add_item(self.message_input)
        self.add_item(self.image_url_input)

    async def on_submit(self, interaction: Interaction) -> None:
        text = str(self.message_input.value)
        image_url_raw = str(self.image_url_input.value).strip()
        image_url = convert_github_blob_to_raw(image_url_raw) if image_url_raw else ""

        # вʼю з вибором: з автором або анонімно
        view = AnonChoiceView(
            channel=self.channel,
            text=text,
            image_url=image_url,
            attachment=self.attachment,
        )

        preview_embed = build_post_embed(
            text=text,
            image_url=image_url,
            attachment=self.attachment,
            author=interaction.user,  # для превʼю показуємо з автором
        )

        await interaction.response.send_message(
            content="Ось превʼю поста. Обери, як відправити:",
            embed=preview_embed,
            view=view,
            ephemeral=True,
        )


# ---------------- VIEW: ВИБІР АНОНІМНОСТІ ----------------
class AnonChoiceView(View):
    def __init__(
        self,
        channel: discord.TextChannel,
        text: str,
        image_url: str,
        attachment: discord.Attachment | None,
    ):
        super().__init__(timeout=60)
        self.channel = channel
        self.text = text
        self.image_url = image_url
        self.attachment = attachment

    async def _send_post(
        self,
        interaction: Interaction,
        author: discord.Member | None,
    ):
        embed = build_post_embed(
            text=self.text,
            image_url=self.image_url,
            attachment=self.attachment,
            author=author,
        )
        await self.channel.send(embed=embed)

        # оновлюємо превʼю повідомлення
        await interaction.response.edit_message(
            content="✅ Пост надіслано.",
            embeds=[],
            view=None,
        )
        self.stop()

    @discord.ui.button(
        label="Надіслати з підписом",
        style=discord.ButtonStyle.primary,
    )
    async def send_with_author(
        self,
        interaction: Interaction,
        button: Button,
    ):
        await self._send_post(interaction, author=interaction.user)

    @discord.ui.button(
        label="Надіслати анонімно",
        style=discord.ButtonStyle.secondary,
    )
    async def send_anon(
        self,
        interaction: Interaction,
        button: Button,
    ):
        # автор None – жодного рядка "Автор" не буде
        await self._send_post(interaction, author=None)

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, Button):
                child.disabled = True


# ---------------- VIEW: ВИБІР КАНАЛУ ----------------
class ChannelSelect(Select):
    def __init__(self, guild: discord.Guild, attachment: discord.Attachment | None):
        self.guild = guild
        self.attachment = attachment

        options: list[SelectOption] = []
        me = guild.me

        for channel in guild.text_channels:
            perms = channel.permissions_for(me)
            if perms.send_messages:
                options.append(
                    SelectOption(
                        label=f"#{channel.name}",
                        value=str(channel.id),
                    )
                )

        placeholder = "Оберіть канал для поста"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options[:25],  # ліміт дискорду
        )

    async def callback(self, interaction: Interaction) -> None:
        channel_id = int(self.values[0])
        channel = self.guild.get_channel(channel_id)

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Неможливо надіслати пост у цей канал.",
                ephemeral=True,
            )
            return

        modal = PostModal(channel=channel, attachment=self.attachment)
        await interaction.response.send_modal(modal)


class ChannelSelectView(View):
    def __init__(self, guild: discord.Guild, attachment: discord.Attachment | None):
        super().__init__(timeout=60)
        self.add_item(ChannelSelect(guild=guild, attachment=attachment))

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, Select):
                child.disabled = True


# ---------------- COG ----------------
class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # slash команда
    @app_commands.command(
        name="post",
        description="Створити ембед пост у вибраний канал",
    )
    @app_commands.describe(
        image="Опційне зображення для поста (аттачмент з ПК)",
    )
    async def post(
        self,
        interaction: Interaction,
        image: discord.Attachment | None = None,
    ):
        """Відкрити вибір каналу і модалку для створення поста."""

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Ця команда доступна лише на сервері.",
                ephemeral=True,
            )
            return

        # перевірка ролі модератора
        member = interaction.user
        assert isinstance(member, discord.Member)

        mod_role = guild.get_role(MODERATOR_ROLE_ID)
        if mod_role not in member.roles and not member.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Лише модератори можуть користуватись цією командою.",
                ephemeral=True,
            )
            return

        view = ChannelSelectView(guild=guild, attachment=image)

        await interaction.response.send_message(
            "Оберіть канал нижче, щоб створити пост:",
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))
