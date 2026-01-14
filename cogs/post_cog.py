# -*- coding: utf-8 -*-
import io
import traceback
from dataclasses import dataclass
from typing import Optional

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, Button, Modal, TextInput
from PIL import Image, ImageDraw


FOOTER_TEXT = "Silent Concierge by Myxa"
ROUND_RADIUS = 40
HTTP_TIMEOUT = 15


@dataclass
class PostSession:
    title: Optional[str] = None
    text: Optional[str] = None
    image_url: Optional[str] = None
    anonymous: bool = False
    footer: bool = True
    edit_message: Optional[discord.Message] = None


async def round_image(url: str):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)) as session:
        async with session.get(url) as r:
            if r.status != 200:
                return None, None
            data = await r.read()

    img = Image.open(io.BytesIO(data)).convert("RGBA")
    w, h = img.size

    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, w, h), ROUND_RADIUS, fill=255)

    out = Image.new("RGBA", (w, h))
    out.paste(img, (0, 0), mask)

    buf = io.BytesIO()
    out.save(buf, format="PNG")
    buf.seek(0)

    return discord.File(buf, "image.png"), "attachment://image.png"


# ---------- MODALS ----------
class TextModal(Modal):
    def __init__(self, cog, session: PostSession):
        super().__init__(title="Текст поста")
        self.cog = cog
        self.session = session

        self.title_input = TextInput(label="Заголовок", required=False)
        self.text_input = TextInput(label="Текст", style=discord.TextStyle.paragraph)

        self.add_item(self.title_input)
        self.add_item(self.text_input)

    async def on_submit(self, interaction: Interaction):
        self.session.title = self.title_input.value or None
        self.session.text = self.text_input.value
        await interaction.response.send_message(
            "Показувати автора?",
            ephemeral=True,
            view=AuthorView(self.cog, self.session),
        )


# ---------- VIEWS ----------
class ImageView(View):
    def __init__(self, cog, session):
        super().__init__()
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З ПК", style=discord.ButtonStyle.primary)
    async def from_pc(self, interaction: Interaction, _):
        await interaction.response.send_message(
            "Надішли повідомлення з картинкою",
            ephemeral=True,
        )

        def check(m: discord.Message):
            return m.author.id == interaction.user.id and m.attachments

        msg = await self.cog.bot.wait_for("message", check=check)
        self.session.image_url = msg.attachments[0].url
        await interaction.followup.send_modal(TextModal(self.cog, self.session))

    @discord.ui.button(label="З посилання", style=discord.ButtonStyle.secondary)
    async def from_link(self, interaction: Interaction, _):
        await interaction.response.send_modal(LinkModal(self.cog, self.session))

    @discord.ui.button(label="Без картинки", style=discord.ButtonStyle.secondary)
    async def no_img(self, interaction: Interaction, _):
        await interaction.response.send_modal(TextModal(self.cog, self.session))


class LinkModal(Modal):
    def __init__(self, cog, session):
        super().__init__(title="Картинка з посилання")
        self.cog = cog
        self.session = session
        self.url = TextInput(label="URL", required=True)
        self.add_item(self.url)

    async def on_submit(self, interaction: Interaction):
        self.session.image_url = self.url.value
        await interaction.response.send_modal(TextModal(self.cog, self.session))


class AuthorView(View):
    def __init__(self, cog, session):
        super().__init__()
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З автором", style=discord.ButtonStyle.success)
    async def yes(self, interaction: Interaction, _):
        self.session.anonymous = False
        await interaction.response.send_message(
            "Додавати футер?",
            ephemeral=True,
            view=FooterView(self.cog, self.session),
        )

    @discord.ui.button(label="Анонімно", style=discord.ButtonStyle.primary)
    async def no(self, interaction: Interaction, _):
        self.session.anonymous = True
        await interaction.response.send_message(
            "Додавати футер?",
            ephemeral=True,
            view=FooterView(self.cog, self.session),
        )


class FooterView(View):
    def __init__(self, cog, session):
        super().__init__()
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З футером", style=discord.ButtonStyle.success)
    async def yes(self, interaction: Interaction, _):
        self.session.footer = True
        await self.cog.publish(interaction, self.session)

    @discord.ui.button(label="Без футера", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: Interaction, _):
        self.session.footer = False
        await self.cog.publish(interaction, self.session)


# ---------- COG ----------
class PostCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="post")
    async def post(self, interaction: Interaction):
        session = PostSession()
        await interaction.response.send_message(
            "Обери спосіб додавання картинки",
            ephemeral=True,
            view=ImageView(self, session),
        )

    @app_commands.command(name="post_edit")
    async def post_edit(self, interaction: Interaction, message: discord.Message):
        if message.author.id != self.bot.user.id:
            await interaction.response.send_message(
                "Можу редагувати тільки повідомлення бота",
                ephemeral=True,
            )
            return

        session = PostSession(
            title=message.embeds[0].title if message.embeds else None,
            text=message.embeds[0].description if message.embeds else None,
            edit_message=message,
        )
        await interaction.response.send_modal(TextModal(self, session))

    async def publish(self, interaction: Interaction, session: PostSession):
        try:
            embed = discord.Embed(
                title=session.title or "",
                description=session.text or "",
                color=discord.Color.teal(),
            )

            if not session.anonymous:
                embed.set_author(
                    name=interaction.user.display_name,
                    icon_url=interaction.user.display_avatar.url,
                )

            file = None
            if session.image_url:
                file, url = await round_image(session.image_url)
                if file:
                    embed.set_image(url=url)

            if session.footer:
                embed.set_footer(
                    text=FOOTER_TEXT,
                    icon_url=self.bot.user.display_avatar.url,
                )

            if session.edit_message:
                if file:
                    await session.edit_message.edit(embed=embed, attachments=[file])
                else:
                    await session.edit_message.edit(embed=embed)
                await interaction.response.send_message("✅ Пост оновлено", ephemeral=True)
            else:
                if file:
                    await interaction.channel.send(embed=embed, file=file)
                else:
                    await interaction.channel.send(embed=embed)
                await interaction.response.send_message("✅ Пост опубліковано", ephemeral=True)

        except Exception:
            traceback.print_exc()
            await interaction.response.send_message("❌ Помилка публікації", ephemeral=True)


async def setup(bot):
    await bot.add_cog(PostCog(bot))
