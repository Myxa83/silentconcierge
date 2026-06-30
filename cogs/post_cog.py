# -*- coding: utf-8 -*-
import io
import re
import json
import asyncio
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import Modal, TextInput
from PIL import Image, ImageDraw

# ============================ CONFIG ============================

FOOTER_TEXT = "Silent Concierge by Myxa"
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "post_logs.json"
TB_FILE = LOG_DIR / "post_tracebacks.json"

HTTP_TIMEOUT = 15
WAIT_FILE_TIMEOUT = 600
VIEW_TIMEOUT = 600
ROUND_RADIUS = 40

IMAGE_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"
)

# ============================ UTILS ============================

def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def bash_log(stage: str, data: str = "") -> None:
    print(f"[POST_COG] {stage}: {data}", flush=True)


def _append_json_list(path: Path, entry: Dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        data = []

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []

        data.append(entry)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        bash_log("LOG_WRITE_ERROR", f"{type(e).__name__}: {e}")


def log_event(
    stage: str,
    interaction: Optional[Interaction],
    extra: Optional[Dict[str, Any]] = None
) -> None:
    entry = {
        "time": _utc_now(),
        "stage": stage,
        "user_id": getattr(getattr(interaction, "user", None), "id", None),
        "guild_id": getattr(getattr(interaction, "guild", None), "id", None),
        "channel_id": getattr(getattr(interaction, "channel", None), "id", None),
        "cmd": getattr(getattr(interaction, "command", None), "qualified_name", None),
    }

    if extra:
        entry.update(extra)

    bash_log("EVENT", json.dumps(entry, ensure_ascii=False))
    _append_json_list(LOG_FILE, entry)


def log_tb(stage: str, interaction: Optional[Interaction], err: BaseException) -> None:
    tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))

    entry = {
        "time": _utc_now(),
        "stage": stage,
        "user_id": getattr(getattr(interaction, "user", None), "id", None),
        "error_type": type(err).__name__,
        "error": str(err),
        "traceback": tb,
    }

    bash_log("ERROR", f"{stage} | {type(err).__name__}: {err}")
    bash_log("TRACEBACK", tb)

    _append_json_list(TB_FILE, entry)


def is_message_after_start(msg: discord.Message, start_time: datetime) -> bool:
    msg_time = msg.created_at

    if msg_time.tzinfo is None:
        msg_time = msg_time.replace(tzinfo=timezone.utc)

    return msg_time >= start_time


def is_probably_image_url(url: str) -> bool:
    if not url:
        return False

    clean = url.split("?")[0].lower()

    if clean.endswith(IMAGE_EXTENSIONS):
        return True

    if "cdn.discordapp.com" in url:
        return True

    if "media.discordapp.net" in url:
        return True

    if "tenor.com" in url:
        return True

    if "giphy.com" in url:
        return True

    return False


def extract_image_url_from_message(msg: discord.Message) -> Optional[str]:
    bash_log(
        "MESSAGE_CHECK",
        f"author={msg.author.id} channel={msg.channel.id} "
        f"attachments={len(msg.attachments)} embeds={len(msg.embeds)} "
        f"stickers={len(msg.stickers)} content={msg.content!r}"
    )

    if msg.attachments:
        att = msg.attachments[0]
        bash_log(
            "ATTACHMENT_FOUND",
            f"url={att.url} filename={att.filename} content_type={att.content_type}"
        )
        return att.url

    for emb in msg.embeds:
        if emb.image and emb.image.url:
            bash_log("EMBED_IMAGE_FOUND", emb.image.url)
            return emb.image.url

        if emb.thumbnail and emb.thumbnail.url:
            bash_log("EMBED_THUMB_FOUND", emb.thumbnail.url)
            return emb.thumbnail.url

        if emb.url and is_probably_image_url(emb.url):
            bash_log("EMBED_URL_FOUND", emb.url)
            return emb.url

    if msg.content:
        urls = re.findall(r"https?://\S+", msg.content)

        for raw_url in urls:
            clean_url = raw_url.strip("<>()[]{}.,!?'\"")

            if is_probably_image_url(clean_url):
                bash_log("CONTENT_IMAGE_URL_FOUND", clean_url)
                return clean_url

        if urls:
            clean_url = urls[0].strip("<>()[]{}.,!?'\"")
            bash_log("CONTENT_URL_FOUND", clean_url)
            return clean_url

    bash_log("NO_IMAGE_FOUND", "message has no usable image url")
    return None


async def download_and_round(url: str) -> Tuple[Optional[discord.File], Optional[str], str]:
    if not url:
        bash_log("DOWNLOAD_SKIP", "empty_url")
        return None, None, "empty_url"

    clean_url = url.split("?")[0].lower()

    if clean_url.endswith(".gif"):
        bash_log("DOWNLOAD_SKIP_GIF", url)
        return None, url, "ok_gif"

    try:
        bash_log("DOWNLOAD_START", url)

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        ) as session:
            async with session.get(url) as r:
                bash_log(
                    "DOWNLOAD_RESPONSE",
                    f"status={r.status} content_type={r.headers.get('content-type')}"
                )

                if r.status != 200:
                    return None, url, f"http_{r.status}"

                data = await r.read()

        img = Image.open(io.BytesIO(data)).convert("RGBA")
        w, h = img.size

        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, w, h), ROUND_RADIUS, fill=255)

        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask)

        buf = io.BytesIO()
        out.save(buf, format="PNG")
        buf.seek(0)

        bash_log("DOWNLOAD_DONE", f"size={w}x{h}")
        return discord.File(buf, filename="image.png"), "attachment://image.png", "ok"

    except Exception as e:
        bash_log("DOWNLOAD_ERROR", f"{type(e).__name__}: {e} | fallback_url={url}")
        return None, url, f"err_{type(e).__name__}"


def parse_message_link(link: str) -> Optional[Tuple[int, int, int]]:
    m = re.search(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)", link or "")

    if not m:
        return None

    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def has_access(member: discord.Member) -> bool:
    return (
        member.guild_permissions.manage_messages
        or member.guild_permissions.administrator
    )


@dataclass
class PostSession:
    title: Optional[str] = None
    text: Optional[str] = None
    image_url: Optional[str] = None

    anonymous: bool = False
    footer: bool = True

    edit_mode: bool = False
    target_channel_id: Optional[int] = None
    target_message_id: Optional[int] = None

    keep_existing_image: bool = False
    remove_image: bool = False


# ============================ UI ============================

class TextModal(Modal, title="Текст поста"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session

        self.title_input = TextInput(
            label="Заголовок",
            required=False,
            max_length=256,
            default=session.title or ""
        )

        self.text_input = TextInput(
            label="Текст",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000,
            default=session.text or ""
        )

        self.add_item(self.title_input)
        self.add_item(self.text_input)

    async def on_submit(self, interaction: Interaction):
        try:
            self.session.title = (self.title_input.value or "").strip() or None
            self.session.text = (self.text_input.value or "").strip()

            log_event(
                "text_modal_submit",
                interaction,
                {"edit_mode": self.session.edit_mode}
            )

            await interaction.response.send_message(
                "Показувати автора?",
                ephemeral=True,
                view=AuthorView(self.cog, self.session)
            )

        except Exception as e:
            log_tb("text_modal_submit", interaction, e)


class LinkModal(Modal, title="Картинка з посилання"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session

        self.url = TextInput(
            label="URL",
            required=True,
            max_length=400
        )

        self.add_item(self.url)

    async def on_submit(self, interaction: Interaction):
        try:
            self.session.image_url = (self.url.value or "").strip() or None
            self.session.keep_existing_image = False
            self.session.remove_image = False

            bash_log("LINK_MODAL_SUBMIT", f"url={self.session.image_url}")

            await interaction.response.send_modal(TextModal(self.cog, self.session))

        except Exception as e:
            log_tb("link_modal_submit", interaction, e)


class OpenTextModalView(discord.ui.View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Ввести текст", style=discord.ButtonStyle.success)
    async def open_text(self, interaction: Interaction, _):
        bash_log("OPEN_TEXT_MODAL", f"user={interaction.user.id}")
        await interaction.response.send_modal(TextModal(self.cog, self.session))


class ImageChoiceView(discord.ui.View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З ПК", style=discord.ButtonStyle.primary)
    async def from_pc(self, interaction: Interaction, _):
        try:
            await interaction.response.send_message(
                "Надішли картинку або GIF у цей канал.",
                ephemeral=True
            )

            start_time = datetime.now(timezone.utc)
            await asyncio.sleep(0.7)

            bash_log(
                "WAIT_IMAGE_START",
                f"user={interaction.user.id} channel={interaction.channel.id} start={start_time}"
            )

            def check(m: discord.Message) -> bool:
                if m.author.id != interaction.user.id:
                    bash_log(
                        "WAIT_IMAGE_IGNORE_AUTHOR",
                        f"got={m.author.id} need={interaction.user.id}"
                    )
                    return False

                if m.channel.id != interaction.channel.id:
                    bash_log(
                        "WAIT_IMAGE_IGNORE_CHANNEL",
                        f"got={m.channel.id} need={interaction.channel.id}"
                    )
                    return False

                if not is_message_after_start(m, start_time):
                    bash_log(
                        "WAIT_IMAGE_IGNORE_OLD",
                        f"msg_time={m.created_at} start={start_time}"
                    )
                    return False

                url = extract_image_url_from_message(m)
                return bool(url)

            msg = await self.cog.bot.wait_for(
                "message",
                timeout=WAIT_FILE_TIMEOUT,
                check=check
            )

            url = extract_image_url_from_message(msg)

            if not url:
                bash_log("WAIT_IMAGE_ERROR", "message passed check but url is empty")
                return await interaction.followup.send(
                    "❌ Я бачу повідомлення, але не бачу в ньому картинки або GIF.",
                    ephemeral=True
                )

            self.session.image_url = url
            self.session.keep_existing_image = False
            self.session.remove_image = False

            bash_log("WAIT_IMAGE_DONE", f"url={url}")

            await interaction.followup.send(
                "✅ Картинку отримано. Тепер натисни кнопку, щоб ввести текст.",
                ephemeral=True,
                view=OpenTextModalView(self.cog, self.session)
            )

        except Exception as e:
            bash_log("WAIT_IMAGE_EXCEPTION", f"{type(e).__name__}: {e}")
            log_tb("image_from_pc", interaction, e)

            await interaction.followup.send(
                "❌ Час очікування вийшов або картинка не була розпізнана. Деталі дивись у bash.",
                ephemeral=True
            )

    @discord.ui.button(label="З посилання", style=discord.ButtonStyle.secondary)
    async def from_link(self, interaction: Interaction, _):
        await interaction.response.send_modal(LinkModal(self.cog, self.session))

    @discord.ui.button(label="Без картинки", style=discord.ButtonStyle.secondary)
    async def no_image(self, interaction: Interaction, _):
        self.session.image_url = None
        self.session.keep_existing_image = False
        self.session.remove_image = True

        bash_log("NO_IMAGE_SELECTED", f"user={interaction.user.id}")

        await interaction.response.send_modal(TextModal(self.cog, self.session))


class EditImageChoiceView(discord.ui.View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Залишити поточну", style=discord.ButtonStyle.success)
    async def keep(self, interaction: Interaction, _):
        self.session.keep_existing_image = True
        self.session.remove_image = False
        self.session.image_url = None

        bash_log("EDIT_KEEP_IMAGE_SELECTED", f"user={interaction.user.id}")

        await interaction.response.send_modal(TextModal(self.cog, self.session))

    @discord.ui.button(label="Замінити (ПК)", style=discord.ButtonStyle.primary)
    async def repl_pc(self, interaction: Interaction, _):
        try:
            await interaction.response.send_message(
                "Надішли картинку або GIF у цей канал.",
                ephemeral=True
            )

            start_time = datetime.now(timezone.utc)
            await asyncio.sleep(0.7)

            bash_log(
                "WAIT_REPLACE_IMAGE_START",
                f"user={interaction.user.id} channel={interaction.channel.id} start={start_time}"
            )

            def check(m: discord.Message) -> bool:
                if m.author.id != interaction.user.id:
                    bash_log(
                        "WAIT_REPLACE_IGNORE_AUTHOR",
                        f"got={m.author.id} need={interaction.user.id}"
                    )
                    return False

                if m.channel.id != interaction.channel.id:
                    bash_log(
                        "WAIT_REPLACE_IGNORE_CHANNEL",
                        f"got={m.channel.id} need={interaction.channel.id}"
                    )
                    return False

                if not is_message_after_start(m, start_time):
                    bash_log(
                        "WAIT_REPLACE_IGNORE_OLD",
                        f"msg_time={m.created_at} start={start_time}"
                    )
                    return False

                url = extract_image_url_from_message(m)
                return bool(url)

            msg = await self.cog.bot.wait_for(
                "message",
                timeout=WAIT_FILE_TIMEOUT,
                check=check
            )

            url = extract_image_url_from_message(msg)

            if not url:
                bash_log("WAIT_REPLACE_IMAGE_ERROR", "message passed check but url is empty")
                return await interaction.followup.send(
                    "❌ Я бачу повідомлення, але не бачу в ньому картинки або GIF.",
                    ephemeral=True
                )

            self.session.image_url = url
            self.session.keep_existing_image = False
            self.session.remove_image = False

            bash_log("WAIT_REPLACE_IMAGE_DONE", f"url={url}")

            await interaction.followup.send(
                "✅ Картинку отримано. Тепер натисни кнопку, щоб ввести текст.",
                ephemeral=True,
                view=OpenTextModalView(self.cog, self.session)
            )

        except Exception as e:
            bash_log("WAIT_REPLACE_IMAGE_EXCEPTION", f"{type(e).__name__}: {e}")
            log_tb("edit_replace_pc", interaction, e)

            await interaction.followup.send(
                "❌ Час очікування вийшов або картинка не була розпізнана. Деталі дивись у bash.",
                ephemeral=True
            )

    @discord.ui.button(label="Замінити (URL)", style=discord.ButtonStyle.secondary)
    async def repl_url(self, interaction: Interaction, _):
        self.session.keep_existing_image = False
        self.session.remove_image = False

        bash_log("EDIT_REPLACE_URL_SELECTED", f"user={interaction.user.id}")

        await interaction.response.send_modal(LinkModal(self.cog, self.session))

    @discord.ui.button(label="Прибрати картинку", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: Interaction, _):
        self.session.remove_image = True
        self.session.keep_existing_image = False
        self.session.image_url = None

        bash_log("EDIT_REMOVE_IMAGE_SELECTED", f"user={interaction.user.id}")

        await interaction.response.send_modal(TextModal(self.cog, self.session))


class AuthorView(discord.ui.View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З автором", style=discord.ButtonStyle.success)
    async def with_author(self, interaction: Interaction, _):
        self.session.anonymous = False

        bash_log("AUTHOR_SELECTED", f"anonymous=False user={interaction.user.id}")

        await interaction.response.send_message(
            "Додавати футер?",
            ephemeral=True,
            view=FooterView(self.cog, self.session)
        )

    @discord.ui.button(label="Анонімно", style=discord.ButtonStyle.primary)
    async def anon(self, interaction: Interaction, _):
        self.session.anonymous = True

        bash_log("AUTHOR_SELECTED", f"anonymous=True user={interaction.user.id}")

        await interaction.response.send_message(
            "Додавати футер?",
            ephemeral=True,
            view=FooterView(self.cog, self.session)
        )


class FooterView(discord.ui.View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З футером", style=discord.ButtonStyle.success)
    async def yes(self, interaction: Interaction, _):
        self.session.footer = True
        bash_log("FOOTER_SELECTED", f"footer=True user={interaction.user.id}")
        await self.cog.finalize(interaction, self.session)

    @discord.ui.button(label="Без футера", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: Interaction, _):
        self.session.footer = False
        bash_log("FOOTER_SELECTED", f"footer=False user={interaction.user.id}")
        await self.cog.finalize(interaction, self.session)


# ============================ COG ============================

class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bash_log("COG_INIT", "PostCog loaded")

    @app_commands.command(name="post", description="Створити пост")
    @app_commands.describe(image="Прикріпи файл одразу")
    async def post_cmd(
        self,
        interaction: Interaction,
        image: Optional[discord.Attachment] = None
    ):
        if not isinstance(interaction.user, discord.Member) or not has_access(interaction.user):
            bash_log("NO_ACCESS", f"user={getattr(interaction.user, 'id', None)}")
            return await interaction.response.send_message(
                "⛔ Нема прав.",
                ephemeral=True
            )

        log_event("post_cmd_start", interaction)

        sess = PostSession()

        if image:
            sess.image_url = image.url
            bash_log("POST_WITH_ATTACHMENT", f"url={image.url} filename={image.filename}")
            await interaction.response.send_modal(TextModal(self, sess))
        else:
            await interaction.response.send_message(
                "Обери картинку:",
                ephemeral=True,
                view=ImageChoiceView(self, sess)
            )

    @app_commands.command(name="post_edit", description="Редагувати пост бота")
    @app_commands.describe(message_link="Посилання на повідомлення")
    async def post_edit_cmd(self, interaction: Interaction, message_link: str):
        if not isinstance(interaction.user, discord.Member) or not has_access(interaction.user):
            bash_log("NO_ACCESS_EDIT", f"user={getattr(interaction.user, 'id', None)}")
            return await interaction.response.send_message(
                "⛔ Нема прав.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        log_event("post_edit_start", interaction, {"message_link": message_link})

        parsed = parse_message_link(message_link)

        if not parsed:
            bash_log("BAD_MESSAGE_LINK", message_link)
            return await interaction.followup.send(
                "❌ Невірне посилання.",
                ephemeral=True
            )

        _, c_id, m_id = parsed

        try:
            channel = self.bot.get_channel(c_id) or await self.bot.fetch_channel(c_id)
            msg = await channel.fetch_message(m_id)

            bash_log(
                "EDIT_TARGET_FETCHED",
                f"channel={c_id} message={m_id} author={msg.author.id} "
                f"embeds={len(msg.embeds)} attachments={len(msg.attachments)}"
            )

        except Exception as e:
            log_tb("post_edit_fetch_message", interaction, e)
            return await interaction.followup.send(
                "❌ Не можу знайти це повідомлення.",
                ephemeral=True
            )

        if msg.author.id != self.bot.user.id:
            bash_log(
                "EDIT_NOT_BOT_MESSAGE",
                f"message_author={msg.author.id} bot={self.bot.user.id}"
            )
            return await interaction.followup.send(
                "❌ Це не мій пост.",
                ephemeral=True
            )

        title = None
        text = ""
        anon = True
        foot = False
        has_img = False

        if msg.embeds:
            emb = msg.embeds[0]

            title = emb.title or None
            text = emb.description or ""
            anon = not bool(emb.author and emb.author.name)
            foot = bool(emb.footer and emb.footer.text)
            has_img = bool((emb.image and emb.image.url) or msg.attachments)

            bash_log(
                "OLD_EMBED_PARSED",
                f"title={title!r} text_len={len(text)} anon={anon} footer={foot} has_img={has_img}"
            )

        sess = PostSession(
            title=title,
            text=text,
            anonymous=anon,
            footer=foot,
            edit_mode=True,
            target_channel_id=c_id,
            target_message_id=m_id
        )

        if has_img:
            await interaction.followup.send(
                "Що з картинкою?",
                ephemeral=True,
                view=EditImageChoiceView(self, sess)
            )
        else:
            await interaction.followup.send(
                "Додати картинку?",
                ephemeral=True,
                view=ImageChoiceView(self, sess)
            )

    async def finalize(self, interaction: Interaction, session: PostSession):
        await interaction.response.defer(ephemeral=True)

        try:
            bash_log(
                "FINALIZE_START",
                f"edit={session.edit_mode} title={session.title!r} "
                f"text_len={len(session.text or '')} image_url={session.image_url!r} "
                f"keep={session.keep_existing_image} remove={session.remove_image} "
                f"anon={session.anonymous} footer={session.footer}"
            )

            embed = discord.Embed(
                title=session.title or "",
                description=session.text or "",
                color=discord.Color.teal()
            )

            if not session.anonymous:
                embed.set_author(
                    name=interaction.user.display_name,
                    icon_url=interaction.user.display_avatar.url
                )

            if session.footer:
                embed.set_footer(
                    text=FOOTER_TEXT,
                    icon_url=self.bot.user.display_avatar.url
                )

            # ============================ EDIT ============================

            if session.edit_mode:
                channel = await self.bot.fetch_channel(session.target_channel_id)
                msg = await channel.fetch_message(session.target_message_id)

                old_attachments = list(msg.attachments)

                bash_log(
                    "EDIT_MESSAGE_STATE",
                    f"old_attachments={len(old_attachments)} embeds={len(msg.embeds)}"
                )

                if session.keep_existing_image:
                    if old_attachments:
                        embed.set_image(url=old_attachments[0].url)

                        bash_log(
                            "EDIT_KEEP_ATTACHMENT",
                            f"url={old_attachments[0].url}"
                        )

                        await msg.edit(
                            embed=embed,
                            attachments=old_attachments
                        )

                    elif msg.embeds and msg.embeds[0].image and msg.embeds[0].image.url:
                        embed.set_image(url=msg.embeds[0].image.url)

                        bash_log(
                            "EDIT_KEEP_EMBED_URL",
                            f"url={msg.embeds[0].image.url}"
                        )

                        await msg.edit(embed=embed)

                    else:
                        bash_log("EDIT_KEEP_NO_IMAGE", "no old image found")
                        await msg.edit(embed=embed)

                    log_event("post_edit_keep_image_done", interaction)

                    return await interaction.followup.send(
                        "✅ Оновлено.",
                        ephemeral=True
                    )

                if session.remove_image:
                    embed.set_image(url=None)

                    bash_log("EDIT_REMOVE_IMAGE", "attachments=[]")

                    await msg.edit(
                        embed=embed,
                        attachments=[]
                    )

                    log_event("post_edit_remove_image_done", interaction)

                    return await interaction.followup.send(
                        "✅ Оновлено.",
                        ephemeral=True
                    )

                if session.image_url:
                    f, url, status = await download_and_round(session.image_url)

                    bash_log(
                        "EDIT_REPLACE_IMAGE",
                        f"status={status} url={url} has_file={bool(f)}"
                    )

                    if url:
                        embed.set_image(url=url)

                    if f:
                        await msg.edit(
                            embed=embed,
                            attachments=[f]
                        )
                    else:
                        await msg.edit(
                            embed=embed,
                            attachments=[]
                        )

                    log_event(
                        "post_edit_replace_image_done",
                        interaction,
                        {"image_status": status}
                    )

                    return await interaction.followup.send(
                        "✅ Оновлено.",
                        ephemeral=True
                    )

                if old_attachments and msg.embeds and msg.embeds[0].image:
                    embed.set_image(url=old_attachments[0].url)

                    bash_log(
                        "EDIT_FALLBACK_KEEP_ATTACHMENT",
                        f"url={old_attachments[0].url}"
                    )

                    await msg.edit(
                        embed=embed,
                        attachments=old_attachments
                    )
                else:
                    bash_log("EDIT_NO_IMAGE_FALLBACK", "edit embed only")
                    await msg.edit(embed=embed)

                log_event("post_edit_done", interaction)

                return await interaction.followup.send(
                    "✅ Оновлено.",
                    ephemeral=True
                )

            # ============================ CREATE ============================

            f_send = None
            img_url = None
            image_status = None

            if session.image_url:
                f_send, img_url, image_status = await download_and_round(session.image_url)

                bash_log(
                    "CREATE_IMAGE_PREPARED",
                    f"status={image_status} url={img_url} has_file={bool(f_send)}"
                )

                if img_url:
                    embed.set_image(url=img_url)

            if f_send:
                bash_log("CREATE_SEND_WITH_FILE", "sending embed + file")
                await interaction.channel.send(
                    embed=embed,
                    file=f_send
                )
            else:
                bash_log("CREATE_SEND_EMBED_ONLY", "sending embed only")
                await interaction.channel.send(embed=embed)

            log_event(
                "post_create_done",
                interaction,
                {"image_status": image_status}
            )

            await interaction.followup.send(
                "✅ Готово.",
                ephemeral=True
            )

        except Exception as e:
            log_tb("finalize", interaction, e)

            try:
                await interaction.followup.send(
                    "❌ Щось зламалося. Помилка записана в logs/post_tracebacks.json і виведена в bash.",
                    ephemeral=True
                )
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))
