# -*- coding: utf-8 -*-
import io
import re
import json
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


FOOTER_TEXT = "Silent Concierge by Myxa"

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "post_logs.json"
TB_FILE = LOG_DIR / "post_tracebacks.json"

HTTP_TIMEOUT = 15
WAIT_FILE_TIMEOUT = 180
VIEW_TIMEOUT = 600
ROUND_RADIUS = 40


def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


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
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def log_event(stage: str, interaction: Optional[Interaction], extra: Optional[Dict[str, Any]] = None) -> None:
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
    _append_json_list(LOG_FILE, entry)


def log_tb(stage: str, interaction: Optional[Interaction], err: BaseException) -> None:
    entry = {
        "time": _utc_now(),
        "stage": stage,
        "user_id": getattr(getattr(interaction, "user", None), "id", None),
        "error_type": type(err).__name__,
        "error": str(err),
        "traceback": "".join(traceback.format_exception(type(err), err, err.__traceback__)),
    }
    _append_json_list(TB_FILE, entry)


async def download_and_round(url: str) -> Tuple[Optional[discord.File], Optional[str], str]:
    if not url:
        return None, None, "empty_url"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)) as session:
            async with session.get(url) as r:
                if r.status != 200:
                    return None, None, f"http_{r.status}"
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

        return discord.File(buf, filename="image.png"), "attachment://image.png", "ok"
    except Exception as e:
        return None, None, f"err_{type(e).__name__}:{e}"


def parse_message_link(link: str) -> Optional[Tuple[int, int, int]]:
    # https://discord.com/channels/guild_id/channel_id/message_id
    m = re.search(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)", link or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def has_access(member: discord.Member) -> bool:
    # Права не чіпаю, але можеш підв'язати ROLE_ALLOWED як раніше
    # Тут зроблено максимально просто: або manage_messages, або адмін.
    return member.guild_permissions.manage_messages or member.guild_permissions.administrator


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
            max_length=4000,
            default=session.text or "",
        )

        self.add_item(self.title_input)
        self.add_item(self.text_input)

    async def on_submit(self, interaction: Interaction):
        try:
            self.session.title = (self.title_input.value or "").strip() or None
            self.session.text = (self.text_input.value or "").strip()
            log_event("text_modal_submit", interaction, {"edit_mode": self.session.edit_mode})
            await interaction.response.send_message(
                "Показувати автора?",
                ephemeral=True,
                view=AuthorView(self.cog, self.session),
            )
        except Exception as e:
            log_tb("text_modal_submit", interaction, e)
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Помилка. Дивись logs/post_tracebacks.json", ephemeral=True)
            else:
                await interaction.followup.send("❌ Помилка. Дивись logs/post_tracebacks.json", ephemeral=True)


class LinkModal(Modal, title="Картинка з посилання"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session
        self.url = TextInput(label="URL", required=True, max_length=400)
        self.add_item(self.url)

    async def on_submit(self, interaction: Interaction):
        self.session.image_url = (self.url.value or "").strip() or None
        self.session.keep_existing_image = False
        self.session.remove_image = False
        log_event("link_set", interaction, {"edit_mode": self.session.edit_mode})
        await interaction.response.send_modal(TextModal(self.cog, self.session))


class ImageChoiceView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З ПК", style=discord.ButtonStyle.primary)
    async def from_pc(self, interaction: Interaction, _):
        try:
            await interaction.response.send_message("Надішли повідомлення з картинкою (файлом)", ephemeral=True)

            def check(m: discord.Message) -> bool:
                return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id and bool(m.attachments)

            msg = await self.cog.bot.wait_for("message", timeout=WAIT_FILE_TIMEOUT, check=check)
            self.session.image_url = msg.attachments[0].url
            self.session.keep_existing_image = False
            self.session.remove_image = False
            log_event("file_received", interaction, {"filename": msg.attachments[0].filename, "edit_mode": self.session.edit_mode})
            await interaction.followup.send_modal(TextModal(self.cog, self.session))
        except Exception as e:
            log_tb("from_pc", interaction, e)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Не вийшло отримати файл. Дивись logs/post_tracebacks.json", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Не вийшло отримати файл. Дивись logs/post_tracebacks.json", ephemeral=True)

    @discord.ui.button(label="З посилання", style=discord.ButtonStyle.secondary)
    async def from_link(self, interaction: Interaction, _):
        await interaction.response.send_modal(LinkModal(self.cog, self.session))

    @discord.ui.button(label="Без картинки", style=discord.ButtonStyle.secondary)
    async def no_image(self, interaction: Interaction, _):
        self.session.image_url = None
        self.session.keep_existing_image = False
        self.session.remove_image = True
        log_event("no_image", interaction, {"edit_mode": self.session.edit_mode})
        await interaction.response.send_modal(TextModal(self.cog, self.session))


class EditImageChoiceView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Залишити поточну", style=discord.ButtonStyle.success)
    async def keep(self, interaction: Interaction, _):
        self.session.keep_existing_image = True
        self.session.remove_image = False
        self.session.image_url = None
        log_event("keep_image", interaction)
        await interaction.response.send_modal(TextModal(self.cog, self.session))

    @discord.ui.button(label="Замінити (ПК)", style=discord.ButtonStyle.primary)
    async def repl_pc(self, interaction: Interaction, _):
        view = ImageChoiceView(self.cog, self.session)
        await view.from_pc(interaction, None)

    @discord.ui.button(label="Замінити (посилання)", style=discord.ButtonStyle.secondary)
    async def repl_link(self, interaction: Interaction, _):
        await interaction.response.send_modal(LinkModal(self.cog, self.session))

    @discord.ui.button(label="Прибрати картинку", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: Interaction, _):
        self.session.keep_existing_image = False
        self.session.remove_image = True
        self.session.image_url = None
        log_event("remove_image", interaction)
        await interaction.response.send_modal(TextModal(self.cog, self.session))


class AuthorView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З автором", style=discord.ButtonStyle.success)
    async def with_author(self, interaction: Interaction, _):
        self.session.anonymous = False
        await interaction.response.send_message("Додавати футер?", ephemeral=True, view=FooterView(self.cog, self.session))

    @discord.ui.button(label="Анонімно", style=discord.ButtonStyle.primary)
    async def anon(self, interaction: Interaction, _):
        self.session.anonymous = True
        await interaction.response.send_message("Додавати футер?", ephemeral=True, view=FooterView(self.cog, self.session))


class FooterView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З футером", style=discord.ButtonStyle.success)
    async def yes(self, interaction: Interaction, _):
        self.session.footer = True
        await self.cog.finalize(interaction, self.session)

    @discord.ui.button(label="Без футера", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: Interaction, _):
        self.session.footer = False
        await self.cog.finalize(interaction, self.session)


class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[COG] post_cog loaded")

    @app_commands.command(name="post", description="Створити пост")
    async def post_cmd(self, interaction: Interaction):
        try:
            if not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("❌ Тільки на сервері.", ephemeral=True)
                return
            if not has_access(interaction.user):
                await interaction.response.send_message("⛔ Нема прав.", ephemeral=True)
                return

            sess = PostSession(edit_mode=False)
            log_event("start_post", interaction)
            await interaction.response.send_message("Обери картинку: ПК, посилання, або без", ephemeral=True, view=ImageChoiceView(self, sess))
        except Exception as e:
            log_tb("start_post", interaction, e)
            await interaction.response.send_message("❌ Помилка. Дивись logs/post_tracebacks.json", ephemeral=True)

    @app_commands.command(name="post_edit", description="Редагувати пост бота по посиланню")
    @app_commands.describe(message_link="Посилання на повідомлення (discord.com/channels/...)")
    async def post_edit_cmd(self, interaction: Interaction, message_link: str):
        try:
            if not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("❌ Тільки на сервері.", ephemeral=True)
                return
            if not has_access(interaction.user):
                await interaction.response.send_message("⛔ Нема прав.", ephemeral=True)
                return

            parsed = parse_message_link(message_link)
            if not parsed:
                await interaction.response.send_message("❌ Невірне посилання.", ephemeral=True)
                return

            guild_id, channel_id, message_id = parsed
            if interaction.guild is None or interaction.guild.id != guild_id:
                await interaction.response.send_message("❌ Це інший сервер.", ephemeral=True)
                return

            channel = interaction.guild.get_channel(channel_id)
            if channel is None:
                channel = await interaction.guild.fetch_channel(channel_id)

            if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                await interaction.response.send_message("❌ Не текстовий канал.", ephemeral=True)
                return

            msg = await channel.fetch_message(message_id)
            if self.bot.user is None or msg.author.id != self.bot.user.id:
                await interaction.response.send_message("❌ Можу редагувати тільки повідомлення бота.", ephemeral=True)
                return

            title = None
            text = ""
            anonymous = True
            footer = False
            has_image = False

            if msg.embeds:
                emb = msg.embeds[0]
                title = emb.title or None
                text = emb.description or ""
                anonymous = not (emb.author and emb.author.name)
                footer = bool(emb.footer and emb.footer.text)
                has_image = bool(emb.image and emb.image.url)

            sess = PostSession(
                title=title,
                text=text,
                anonymous=anonymous,
                footer=footer,
                edit_mode=True,
                target_channel_id=channel_id,
                target_message_id=message_id,
            )

            log_event("start_edit", interaction, {"message_id": message_id, "has_image": has_image})

            if has_image:
                await interaction.response.send_message("Що робимо з картинкою?", ephemeral=True, view=EditImageChoiceView(self, sess))
            else:
                await interaction.response.send_message("Обери картинку: ПК, посилання, або без", ephemeral=True, view=ImageChoiceView(self, sess))

        except Exception as e:
            log_tb("start_edit", interaction, e)
            await interaction.response.send_message("❌ Помилка. Дивись logs/post_tracebacks.json", ephemeral=True)

    async def finalize(self, interaction: Interaction, session: PostSession):
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

            if session.footer and self.bot.user:
                embed.set_footer(text=FOOTER_TEXT, icon_url=self.bot.user.display_avatar.url)

            file_to_send = None
            if session.edit_mode:
                channel = interaction.guild.get_channel(session.target_channel_id) if interaction.guild else None
                if channel is None and interaction.guild:
                    channel = await interaction.guild.fetch_channel(session.target_channel_id)
                if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                    raise RuntimeError("bad_target_channel")

                msg = await channel.fetch_message(session.target_message_id)

                if session.keep_existing_image and msg.embeds and msg.embeds[0].image and msg.embeds[0].image.url:
                    embed.set_image(url=msg.embeds[0].image.url)
                    await msg.edit(embed=embed)
                    await interaction.response.send_message("✅ Оновлено.", ephemeral=True)
                    log_event("edit_done_keep_image", interaction, {"message_id": msg.id})
                    return

                if session.remove_image:
                    await msg.edit(embed=embed, attachments=[])
                    await interaction.response.send_message("✅ Оновлено (без картинки).", ephemeral=True)
                    log_event("edit_done_remove_image", interaction, {"message_id": msg.id})
                    return

                if session.image_url:
                    f, attach_url, reason = await download_and_round(session.image_url)
                    log_event("edit_image_round", interaction, {"reason": reason})
                    if f and attach_url:
                        embed.set_image(url=attach_url)
                        await msg.edit(embed=embed, attachments=[], files=[f])
                    else:
                        await msg.edit(embed=embed, attachments=[])
                    await interaction.response.send_message("✅ Оновлено.", ephemeral=True)
                    log_event("edit_done_replace_image", interaction, {"message_id": msg.id})
                    return

                await msg.edit(embed=embed)
                await interaction.response.send_message("✅ Оновлено.", ephemeral=True)
                log_event("edit_done_text_only", interaction, {"message_id": msg.id})
                return

            # publish new
            if session.image_url:
                f, attach_url, reason = await download_and_round(session.image_url)
                log_event("post_image_round", interaction, {"reason": reason})
                if f and attach_url:
                    file_to_send = f
                    embed.set_image(url=attach_url)

            if file_to_send:
                await interaction.channel.send(embed=embed, file=file_to_send)
            else:
                await interaction.channel.send(embed=embed)

            await interaction.response.send_message("✅ Опубліковано.", ephemeral=True)
            log_event("post_done", interaction)

        except Exception as e:
            log_tb("finalize", interaction, e)
            if interaction.response.is_done():
                await interaction.followup.send("❌ Помилка. Дивись logs/post_tracebacks.json", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Помилка. Дивись logs/post_tracebacks.json", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))
