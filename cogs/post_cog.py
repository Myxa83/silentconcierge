# -*- coding: utf-8 -*-
import re
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
        return url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    return url


def _bot_footer_icon_url(bot: commands.Bot) -> str | None:
    u = getattr(bot, "user", None)
    if u is None:
        return None
    try:
        return u.display_avatar.url
    except Exception:
        return None


def build_post_embed(
    bot: commands.Bot,
    text: str,
    image_url: str | None,
    attachment: discord.Attachment | None,
    author: discord.Member | None,
    footer_enabled: bool = True,
) -> discord.Embed:
    """Збираємо ембед з тексту, опційного зображення та автора."""

    text = (text or "").strip()

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

    # футер: текст + аватарка бота
    if footer_enabled:
        embed.set_footer(text=FOOTER_TEXT, icon_url=_bot_footer_icon_url(bot))

    return embed


def parse_message_link(link_or_id: str) -> tuple[int | None, int | None, int | None]:
    """
    Повертає (guild_id, channel_id, message_id) з message link.
    Якщо передали просто message_id, повертає (None, None, message_id).
    """
    s = (link_or_id or "").strip()

    m = re.search(r"discord\.com/channels/(\d+)/(\d+)/(\d+)", s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))

    if s.isdigit():
        return None, None, int(s)

    return None, None, None


async def fetch_message_by_link(
    interaction: Interaction,
    link_or_id: str,
) -> discord.Message | None:
    """
    Дістає повідомлення.
    Якщо дали лінк - беремо channel_id звідти.
    Якщо дали тільки message_id - пробуємо шукати в поточному каналі.
    """
    guild = interaction.guild
    if guild is None:
        return None

    g_id, c_id, m_id = parse_message_link(link_or_id)
    if m_id is None:
        return None

    channel: discord.TextChannel | None = None

    if c_id is not None:
        ch = guild.get_channel(c_id)
        if isinstance(ch, discord.TextChannel):
            channel = ch
    else:
        if isinstance(interaction.channel, discord.TextChannel):
            channel = interaction.channel

    if channel is None:
        return None

    try:
        return await channel.fetch_message(m_id)
    except Exception:
        return None


# ---------------- MODALS ----------------
class PostModal(Modal, title="Створити пост у вибраний канал"):
    def __init__(self, bot: commands.Bot, channel: discord.TextChannel, attachment: discord.Attachment | None):
        super().__init__(timeout=300)
        self.bot = bot
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

        view = AnonChoiceView(
            bot=self.bot,
            mode="send",
            channel=self.channel,
            message=None,
            text=text,
            image_url=image_url,
            attachment=self.attachment,
        )

        preview_embed = build_post_embed(
            bot=self.bot,
            text=text,
            image_url=image_url,
            attachment=self.attachment,
            author=interaction.user,
            footer_enabled=True,
        )

        await interaction.response.send_message(
            content="Ось превʼю поста. Обери, як відправити, і чи потрібен футер:",
            embed=preview_embed,
            view=view,
            ephemeral=True,
        )


class EditPostModal(Modal, title="Редагувати існуючий пост"):
    def __init__(self, bot: commands.Bot, attachment: discord.Attachment | None):
        super().__init__(timeout=300)
        self.bot = bot
        self.attachment = attachment

        self.target_input = TextInput(
            label="Message link або Message ID",
            style=discord.TextStyle.short,
            placeholder="https://discord.com/channels/.../.../... або просто цифри",
            required=True,
            max_length=300,
        )

        self.message_input = TextInput(
            label="Новий текст",
            style=discord.TextStyle.paragraph,
            placeholder="Перший рядок стане заголовком, решта - описом",
            required=True,
            max_length=4000,
        )

        self.image_url_input = TextInput(
            label="Новий URL зображення (необовʼязково)",
            style=discord.TextStyle.short,
            placeholder="Порожньо - тоді або attachment, або без зображення",
            required=False,
            max_length=500,
        )

        self.add_item(self.target_input)
        self.add_item(self.message_input)
        self.add_item(self.image_url_input)

    async def on_submit(self, interaction: Interaction) -> None:
        target = str(self.target_input.value).strip()
        text = str(self.message_input.value)
        image_url_raw = str(self.image_url_input.value).strip()
        image_url = convert_github_blob_to_raw(image_url_raw) if image_url_raw else ""

        msg = await fetch_message_by_link(interaction, target)
        if msg is None:
            await interaction.response.send_message(
                "❌ Не знайшов повідомлення. Перевір лінк або ID, і що бот має доступ до каналу.",
                ephemeral=True,
            )
            return

        view = AnonChoiceView(
            bot=self.bot,
            mode="edit",
            channel=None,
            message=msg,
            text=text,
            image_url=image_url,
            attachment=self.attachment,
        )

        preview_embed = build_post_embed(
            bot=self.bot,
            text=text,
            image_url=image_url,
            attachment=self.attachment,
            author=interaction.user,
            footer_enabled=True,
        )

        await interaction.response.send_message(
            content="Ось превʼю редагування. Обери, як застосувати, і чи потрібен футер:",
            embed=preview_embed,
            view=view,
            ephemeral=True,
        )


# ---------------- VIEW: ВИБІР РЕЖИМУ ----------------
class PostModeView(View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, attachment: discord.Attachment | None):
        super().__init__(timeout=60)
        self.bot = bot
        self.guild = guild
        self.attachment = attachment

    @discord.ui.button(label="Створити новий пост", style=discord.ButtonStyle.primary)
    async def new_post(self, interaction: Interaction, button: Button):
        view = ChannelSelectView(bot=self.bot, guild=self.guild, attachment=self.attachment)
        await interaction.response.edit_message(
            content="Оберіть канал нижче, щоб створити пост:",
            view=view,
            embed=None,
        )
        self.stop()

    @discord.ui.button(label="Редагувати існуючий пост", style=discord.ButtonStyle.secondary)
    async def edit_post(self, interaction: Interaction, button: Button):
        modal = EditPostModal(bot=self.bot, attachment=self.attachment)
        await interaction.response.send_modal(modal)
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, Button):
                child.disabled = True


# ---------------- VIEW: ВИБІР АНОНІМНОСТІ + ФУТЕР ----------------
class AnonChoiceView(View):
    def __init__(
        self,
        bot: commands.Bot,
        mode: str,  # "send" або "edit"
        channel: discord.TextChannel | None,
        message: discord.Message | None,
        text: str,
        image_url: str,
        attachment: discord.Attachment | None,
    ):
        super().__init__(timeout=90)
        self.bot = bot
        self.mode = mode
        self.channel = channel
        self.message = message
        self.text = text
        self.image_url = image_url
        self.attachment = attachment
        self.footer_enabled = True

    def _make_embed(self, author: discord.Member | None) -> discord.Embed:
        return build_post_embed(
            bot=self.bot,
            text=self.text,
            image_url=self.image_url,
            attachment=self.attachment,
            author=author,
            footer_enabled=self.footer_enabled,
        )

    async def _apply(self, interaction: Interaction, author: discord.Member | None):
        embed = self._make_embed(author=author)

        if self.mode == "send":
            if self.channel is None:
                await interaction.response.send_message("❌ Канал не вибраний.", ephemeral=True)
                return
            await self.channel.send(embed=embed)

            await interaction.response.edit_message(
                content="✅ Пост надіслано.",
                embeds=[],
                view=None,
            )
            self.stop()
            return

        if self.mode == "edit":
            if self.message is None:
                await interaction.response.send_message("❌ Повідомлення для редагування не знайдено.", ephemeral=True)
                return

            try:
                await self.message.edit(embed=embed)
            except Exception:
                await interaction.response.send_message(
                    "❌ Не зміг відредагувати повідомлення. Перевір права бота (Edit Messages) і доступ до каналу.",
                    ephemeral=True,
                )
                return

            await interaction.response.edit_message(
                content="✅ Пост відредаговано.",
                embeds=[],
                view=None,
            )
            self.stop()
            return

        await interaction.response.send_message("❌ Невідомий режим.", ephemeral=True)

    @discord.ui.button(label="Футер: увімкнено", style=discord.ButtonStyle.success, row=0)
    async def toggle_footer(self, interaction: Interaction, button: Button):
        self.footer_enabled = not self.footer_enabled
        button.label = "Футер: увімкнено" if self.footer_enabled else "Футер: вимкнено"
        button.style = discord.ButtonStyle.success if self.footer_enabled else discord.ButtonStyle.danger

        preview_embed = self._make_embed(author=interaction.user)
        await interaction.response.edit_message(embed=preview_embed, view=self)

    @discord.ui.button(label="Надіслати з підписом", style=discord.ButtonStyle.primary, row=1)
    async def with_author(self, interaction: Interaction, button: Button):
        await self._apply(interaction, author=interaction.user)

    @discord.ui.button(label="Надіслати анонімно", style=discord.ButtonStyle.secondary, row=1)
    async def anon(self, interaction: Interaction, button: Button):
        await self._apply(interaction, author=None)

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, Button):
                child.disabled = True


# ---------------- VIEW: ВИБІР КАНАЛУ ----------------
class ChannelSelect(Select):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, attachment: discord.Attachment | None):
        self.bot = bot
        self.guild = guild
        self.attachment = attachment

        options: list[SelectOption] = []
        me = guild.me

        for channel in guild.text_channels:
            perms = channel.permissions_for(me)
            if perms.send_messages:
                options.append(SelectOption(label=f"#{channel.name}", value=str(channel.id)))

        super().__init__(
            placeholder="Оберіть канал для поста",
            min_values=1,
            max_values=1,
            options=options[:25],
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

        modal = PostModal(bot=self.bot, channel=channel, attachment=self.attachment)
        await interaction.response.send_modal(modal)


class ChannelSelectView(View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, attachment: discord.Attachment | None):
        super().__init__(timeout=60)
        self.add_item(ChannelSelect(bot=bot, guild=guild, attachment=attachment))

    async def on_timeout(self) -> None:
        for child in self.children:
            if isinstance(child, Select):
                child.disabled = True


# ---------------- COG ----------------
class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="post",
        description="Створити або відредагувати ембед пост",
    )
    @app_commands.describe(
        image="Опційне зображення для поста (attachment з ПК)",
    )
    async def post(
        self,
        interaction: Interaction,
        image: discord.Attachment | None = None,
    ):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "❌ Ця команда доступна лише на сервері.",
                ephemeral=True,
            )
            return

        member = interaction.user
        assert isinstance(member, discord.Member)

        mod_role = guild.get_role(MODERATOR_ROLE_ID)
        if mod_role not in member.roles and not member.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Лише модератори можуть користуватись цією командою.",
                ephemeral=True,
            )
            return

        view = PostModeView(bot=self.bot, guild=guild, attachment=image)
        await interaction.response.send_message(
            "Обери режим: створити новий пост або редагувати існуючий.",
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))
