# -*- coding: utf-8 -*-
import io
import json
import re
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, Button, Modal, TextInput
from PIL import Image, ImageDraw


# ================== CONFIG ==================
ROLE_ALLOWED = [
    1375070910138028044,  # Leader
    1425974196181270671,  # Officer
    1323454517664157736,  # Moderator
]

FOOTER_TEXT = "Silent Concierge by Myxa"

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "post_logs.json"
TB_FILE = LOG_DIR / "post_tracebacks.json"

HTTP_TIMEOUT = 15
WAIT_FILE_TIMEOUT = 180
VIEW_TIMEOUT = 600
ROUND_RADIUS = 40
# ============================================


def utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def log_event(stage: str, interaction: Optional[Interaction], extra: Optional[Dict[str, Any]] = None):
    try:
        LOG_DIR.mkdir(exist_ok=True)
        entry = {
            "time": utc_now(),
            "stage": stage,
            "user": getattr(getattr(interaction, "user", None), "id", None),
            "channel": getattr(getattr(interaction, "channel", None), "id", None),
            "guild": getattr(getattr(interaction, "guild", None), "id", None),
            "cmd": getattr(getattr(interaction, "command", None), "qualified_name", None),
        }
        if extra:
            entry.update(extra)

        data = []
        if LOG_FILE.exists():
            try:
                data = json.loads(LOG_FILE.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []

        data.append(entry)
        LOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def log_traceback(stage: str, interaction: Optional[Interaction], err: Exception):
    try:
        LOG_DIR.mkdir(exist_ok=True)
        entry = {
            "time": utc_now(),
            "stage": stage,
            "user": getattr(getattr(interaction, "user", None), "id", None),
            "cmd": getattr(getattr(interaction, "command", None), "qualified_name", None),
            "error": str(err),
            "traceback": traceback.format_exc(),
        }

        data = []
        if TB_FILE.exists():
            try:
                data = json.loads(TB_FILE.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []
        data.append(entry)
        TB_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def has_access(member: discord.Member) -> bool:
    return any(r.id in ROLE_ALLOWED for r in member.roles)


async def download_and_round(url: str) -> Tuple[Optional[discord.File], Optional[str]]:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None, None
            data = await resp.read()

    img = Image.open(io.BytesIO(data)).convert("RGBA")
    w, h = img.size

    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, w, h), ROUND_RADIUS, fill=255)

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)

    buff = io.BytesIO()
    out.save(buff, format="PNG")
    buff.seek(0)

    return discord.File(buff, filename="image.png"), "attachment://image.png"


def parse_message_link(link: str) -> Optional[Tuple[int, int, int]]:
    # https://discord.com/channels/guild_id/channel_id/message_id
    m = re.search(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)", link)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


# ================== SESSION ==================
@dataclass
class PostSession:
    title: Optional[str] = None
    text: Optional[str] = None

    image_url: Optional[str] = None      # посилання
    file_url: Optional[str] = None       # вкладення (cdn)

    anonymous: bool = False
    footer: bool = True

    # edit target
    edit_mode: bool = False
    target_channel_id: Optional[int] = None
    target_message_id: Optional[int] = None

    # image behavior
    keep_existing_image: bool = False
    remove_image: bool = False
# ============================================


# ================== MODALS ===================
class TextModal(Modal, title="Текст поста"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session

        self.title_input = TextInput(
            label="Заголовок",
            required=False,
            max_length=256,
            default=session.title or "",
        )
        self.text_input = TextInput(
            label="Текст",
            style=discord.TextStyle.paragraph,
            required=True,
            default=session.text or "",
            max_length=4000,
        )

        self.add_item(self.title_input)
        self.add_item(self.text_input)

    async def on_submit(self, interaction: Interaction):
        try:
            self.session.title = (self.title_input.value or "").strip() or None
            self.session.text = (self.text_input.value or "").strip()
            log_event("text_submitted", interaction, {"edit_mode": self.session.edit_mode})

            await interaction.response.send_message(
                "Вибери: показувати автора чи ні",
                ephemeral=True,
                view=AuthorView(self.cog, self.session),
            )
        except Exception as e:
            log_traceback("text_modal_submit", interaction, e)
            try:
                await interaction.response.send_message("❌ Помилка модалки. Дивись logs/post_tracebacks.json", ephemeral=True)
            except Exception:
                pass


class LinkModal(Modal, title="Картинка з посилання"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session
        self.link = TextInput(label="URL", required=True, max_length=400)
        self.add_item(self.link)

    async def on_submit(self, interaction: Interaction):
        try:
            self.session.image_url = (self.link.value or "").strip()
            self.session.file_url = None
            self.session.keep_existing_image = False
            self.session.remove_image = False
            log_event("image_link_set", interaction, {"edit_mode": self.session.edit_mode})
            await interaction.response.send_modal(TextModal(self.cog, self.session))
        except Exception as e:
            log_traceback("link_modal_submit", interaction, e)
            try:
                await interaction.response.send_message("❌ Помилка посилання. Дивись logs/post_tracebacks.json", ephemeral=True)
            except Exception:
                pass
# ============================================


# ================== VIEWS ====================
class ImageChoiceView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З ПК", style=discord.ButtonStyle.primary)
    async def from_pc(self, interaction: Interaction, _):
        try:
            log_event("wait_file_start", interaction, {"edit_mode": self.session.edit_mode})
            await interaction.response.send_message(
                "Надішли повідомлення з картинкою (файлом) в цей канал",
                ephemeral=True,
            )

            def check(msg: discord.Message):
                return msg.author.id == interaction.user.id and msg.channel.id == interaction.channel.id and bool(msg.attachments)

            msg = await self.cog.bot.wait_for("message", timeout=WAIT_FILE_TIMEOUT, check=check)
            self.session.file_url = msg.attachments[0].url
            self.session.image_url = None
            self.session.keep_existing_image = False
            self.session.remove_image = False
            log_event("file_received", interaction, {"filename": msg.attachments[0].filename, "edit_mode": self.session.edit_mode})

            await interaction.followup.send_modal(TextModal(self.cog, self.session))
        except Exception as e:
            log_traceback("from_pc", interaction, e)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Не вийшло отримати файл. Дивись logs/post_tracebacks.json", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Не вийшло отримати файл. Дивись logs/post_tracebacks.json", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="З посилання", style=discord.ButtonStyle.secondary)
    async def from_link(self, interaction: Interaction, _):
        try:
            await interaction.response.send_modal(LinkModal(self.cog, self.session))
        except Exception as e:
            log_traceback("from_link", interaction, e)

    @discord.ui.button(label="Без картинки", style=discord.ButtonStyle.secondary)
    async def no_image(self, interaction: Interaction, _):
        try:
            self.session.file_url = None
            self.session.image_url = None
            self.session.keep_existing_image = False
            self.session.remove_image = True
            log_event("no_image", interaction, {"edit_mode": self.session.edit_mode})
            await interaction.response.send_modal(TextModal(self.cog, self.session))
        except Exception as e:
            log_traceback("no_image", interaction, e)


class EditImageChoiceView(View):
    # Для edit: додаємо ще "залишити поточну"
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Залишити поточну", style=discord.ButtonStyle.success)
    async def keep(self, interaction: Interaction, _):
        try:
            self.session.keep_existing_image = True
            self.session.remove_image = False
            self.session.file_url = None
            self.session.image_url = None
            log_event("keep_existing_image", interaction, {})
            await interaction.response.send_modal(TextModal(self.cog, self.session))
        except Exception as e:
            log_traceback("keep_existing_image", interaction, e)

    @discord.ui.button(label="З ПК", style=discord.ButtonStyle.primary)
    async def from_pc(self, interaction: Interaction, _):
        view = ImageChoiceView(self.cog, self.session)
        await view.from_pc.callback(interaction)  # type: ignore

    @discord.ui.button(label="З посилання", style=discord.ButtonStyle.secondary)
    async def from_link(self, interaction: Interaction, _):
        await interaction.response.send_modal(LinkModal(self.cog, self.session))

    @discord.ui.button(label="Прибрати картинку", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: Interaction, _):
        self.session.keep_existing_image = False
        self.session.remove_image = True
        self.session.file_url = None
        self.session.image_url = None
        log_event("remove_image", interaction, {})
        await interaction.response.send_modal(TextModal(self.cog, self.session))


class AuthorView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З автором", style=discord.ButtonStyle.success)
    async def with_author(self, interaction: Interaction, _):
        self.session.anonymous = False
        log_event("author_yes", interaction, {"edit_mode": self.session.edit_mode})
        await interaction.response.send_message("Додавати футер?", ephemeral=True, view=FooterView(self.cog, self.session))

    @discord.ui.button(label="Анонімно", style=discord.ButtonStyle.primary)
    async def anonymous(self, interaction: Interaction, _):
        self.session.anonymous = True
        log_event("author_no", interaction, {"edit_mode": self.session.edit_mode})
        await interaction.response.send_message("Додавати футер?", ephemeral=True, view=FooterView(self.cog, self.session))


class FooterView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З футером", style=discord.ButtonStyle.success)
    async def with_footer(self, interaction: Interaction, _):
        self.session.footer = True
        log_event("footer_yes", interaction, {"edit_mode": self.session.edit_mode})
        await self.cog.publish_or_edit(interaction, self.session)

    @discord.ui.button(label="Без футера", style=discord.ButtonStyle.secondary)
    async def no_footer(self, interaction: Interaction, _):
        self.session.footer = False
        log_event("footer_no", interaction, {"edit_mode": self.session.edit_mode})
        await self.cog.publish_or_edit(interaction, self.session)
# ============================================


# ================== COG =====================
class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[COG] post_cog loaded")

    @app_commands.command(name="post", description="Створити пост")
    async def post(self, interaction: Interaction):
        try:
            if not isinstance(interaction.user, discord.Member) or not has_access(interaction.user):
                await interaction.response.send_message("⛔ Нема прав", ephemeral=True)
                return

            session = PostSession(edit_mode=False)
            log_event("start_post", interaction)

            await interaction.response.send_message(
                "Обери спосіб додавання картинки",
                ephemeral=True,
                view=ImageChoiceView(self, session),
            )
        except Exception as e:
            log_traceback("start_post", interaction, e)
            try:
                await interaction.response.send_message("❌ Помилка /post. Дивись logs/post_tracebacks.json", ephemeral=True)
            except Exception:
                pass

    @app_commands.command(name="post_edit", description="Відредагувати пост бота за посиланням на повідомлення")
    @app_commands.describe(message_link="Посилання на повідомлення (discord.com/channels/...)")
    async def post_edit(self, interaction: Interaction, message_link: str):
        try:
            if not isinstance(interaction.user, discord.Member) or not has_access(interaction.user):
                await interaction.response.send_message("⛔ Нема прав", ephemeral=True)
                return

            parsed = parse_message_link(message_link)
            if not parsed:
                await interaction.response.send_message("❌ Не бачу посилання. Потрібен формат discord.com/channels/...", ephemeral=True)
                return

            guild_id, channel_id, message_id = parsed
            if interaction.guild is None or interaction.guild.id != guild_id:
                await interaction.response.send_message("❌ Це посилання з іншого сервера.", ephemeral=True)
                return

            channel = interaction.guild.get_channel(channel_id)
            if channel is None:
                channel = await interaction.guild.fetch_channel(channel_id)

            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                await interaction.response.send_message("❌ Це не текстовий канал.", ephemeral=True)
                return

            msg = await channel.fetch_message(message_id)
            if msg.author.id != self.bot.user.id:
                await interaction.response.send_message("❌ Я можу редагувати тільки повідомлення, які написав бот.", ephemeral=True)
                return

            # Витягуємо дані з embed (підтримуємо перший embed)
            title = None
            text = ""
            anonymous = True
            footer = False
            existing_image = None

            if msg.embeds:
                emb = msg.embeds[0]
                title = emb.title or None
                text = emb.description or ""
                anonymous = (emb.author is None) or (not emb.author.name)
                footer = bool(emb.footer and emb.footer.text)
                existing_image = emb.image.url if emb.image else None

            session = PostSession(
                title=title,
                text=text,
                anonymous=anonymous,
                footer=footer,
                edit_mode=True,
                target_channel_id=channel_id,
                target_message_id=message_id,
            )

            # Якщо була картинка в embed, дамо вибір: лишити, замінити, прибрати
            if existing_image:
                log_event("start_edit_with_image", interaction, {"message_id": message_id})
                await interaction.response.send_message(
                    "Редагування поста. Обери що робити з картинкою",
                    ephemeral=True,
                    view=EditImageChoiceView(self, session),
                )
            else:
                log_event("start_edit_no_image", interaction, {"message_id": message_id})
                await interaction.response.send_message(
                    "Редагування поста. Обери спосіб додавання картинки",
                    ephemeral=True,
                    view=ImageChoiceView(self, session),
                )

        except Exception as e:
            log_traceback("start_edit", interaction, e)
            try:
                await interaction.response.send_message("❌ Помилка /post_edit. Дивись logs/post_tracebacks.json", ephemeral=True)
            except Exception:
                pass

    async def publish_or_edit(self, interaction: Interaction, session: PostSession):
        try:
            if not session.text:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Текст порожній.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Текст порожній.", ephemeral=True)
                return

            embed = discord.Embed(
                title=session.title or "",
                description=session.text,
                color=discord.Color.teal(),
            )

            if not session.anonymous:
                embed.set_author(
                    name=interaction.user.display_name,
                    icon_url=interaction.user.display_avatar.url,
                )

            if session.footer:
                embed.set_footer(
                    text=FOOTER_TEXT,
                    icon_url=self.bot.user.display_avatar.url,
                )

            file = None
            # edit image rules
            # - keep_existing_image: не чіпаємо embed.image (але ми не маємо старий url, тому залишимо як є через message.edit(embed=embed) не вийде)
            # Рішення: якщо keep_existing_image, ми беремо поточний embed у повідомленні і лише міняємо title/desc/author/footer.
            # Якщо заміна: підвантажуємо і додаємо як attachment://image.png
            # Якщо remove_image: не ставимо embed.image і при edit чистимо attachments.

            if session.edit_mode:
                channel = interaction.guild.get_channel(session.target_channel_id) if interaction.guild else None
                if channel is None and interaction.guild:
                    channel = await interaction.guild.fetch_channel(session.target_channel_id)

                if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                    raise RuntimeError("Target channel is not text channel")

                msg = await channel.fetch_message(session.target_message_id)

                if session.keep_existing_image and msg.embeds:
                    # Залишаємо стару картинку, беремо існуючий embed і оновлюємо поля
                    old = msg.embeds[0]
                    if old.image and old.image.url:
                        embed.set_image(url=old.image.url)

                    if msg.embeds and msg.embeds[0].thumbnail and msg.embeds[0].thumbnail.url:
                        embed.set_thumbnail(url=msg.embeds[0].thumbnail.url)

                    await msg.edit(embed=embed)
                    await interaction.response.send_message("✅ Пост відредаговано", ephemeral=True)
                    log_event("edited_keep_image", interaction, {"message_id": msg.id})
                    return

                # remove image
                if session.remove_image:
                    await msg.edit(embed=embed, attachments=[])
                    await interaction.response.send_message("✅ Пост відредаговано (картинку прибрано)", ephemeral=True)
                    log_event("edited_remove_image", interaction, {"message_id": msg.id})
                    return

                # replace image from file_url or image_url
                image_source = session.file_url or session.image_url
                if image_source:
                    file, attach_url = await download_and_round(image_source)
                    if file and attach_url:
                        embed.set_image(url=attach_url)
                        await msg.edit(embed=embed, attachments=[], files=[file])
                    else:
                        await msg.edit(embed=embed, attachments=[])
                    await interaction.response.send_message("✅ Пост відредаговано", ephemeral=True)
                    log_event("edited_replace_image", interaction, {"message_id": msg.id})
                    return

                # no image change and no existing image
                await msg.edit(embed=embed)
                await interaction.response.send_message("✅ Пост відредаговано", ephemeral=True)
                log_event("edited_no_image", interaction, {"message_id": msg.id})
                return

            # publish new
            channel = interaction.channel
            if channel is None or not hasattr(channel, "send"):
                raise RuntimeError("No channel to send")

            # image for new post
            image_source = session.file_url or session.image_url
            if image_source:
                file, attach_url = await download_and_round(image_source)
                if file and attach_url:
                    embed.set_image(url=attach_url)

            if file:
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)

            await interaction.response.send_message("✅ Пост опубліковано", ephemeral=True)
            log_event("published", interaction)

        except Exception as e:
            log_traceback("publish_or_edit", interaction, e)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Помилка. Дивись logs/post_tracebacks.json", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Помилка. Дивись logs/post_tracebacks.json", ephemeral=True)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot)
