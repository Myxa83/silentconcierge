# -*- coding: utf-8 -*-
import io
import json
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, Button, Modal, TextInput
from PIL import Image, ImageDraw


ROLE_ALLOWED = [
    1375070910138028044,  # Leader
    1425974196181270671,  # Officer
    1323454517664157736,  # Moderator
]

LOG_DIR = Path("logs")
POST_LOG_FILE = LOG_DIR / "post_logs.json"
POST_TB_FILE = LOG_DIR / "post_tracebacks.json"

HTTP_TIMEOUT_SECONDS = 15
VIEW_TIMEOUT_SECONDS = 600
WAIT_FILE_TIMEOUT_SECONDS = 120
MAX_POLL_OPTIONS = 5


def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _safe_str(x: Any, limit: int = 700) -> str:
    try:
        s = str(x)
    except Exception:
        s = "<unprintable>"
    return s if len(s) <= limit else s[:limit] + "...(cut)"


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


def _log_stage(stage: str, interaction: Optional[Interaction], extra: Optional[Dict[str, Any]] = None) -> None:
    entry = {
        "time": _utc_now(),
        "stage": stage,
        "user_id": getattr(getattr(interaction, "user", None), "id", None) if interaction else None,
        "guild_id": getattr(getattr(getattr(interaction, "guild", None), "id", None), "__int__", None) if interaction else None,
        "channel_id": getattr(getattr(getattr(interaction, "channel", None), "id", None), "__int__", None) if interaction else None,
        "cmd": getattr(getattr(interaction, "command", None), "qualified_name", None) if interaction else None,
    }
    if extra:
        entry.update(extra)
    _append_json_list(POST_LOG_FILE, entry)


def _log_traceback(stage: str, interaction: Optional[Interaction], err: BaseException) -> None:
    tb = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    entry = {
        "time": _utc_now(),
        "stage": stage,
        "user_id": getattr(getattr(interaction, "user", None), "id", None) if interaction else None,
        "cmd": getattr(getattr(interaction, "command", None), "qualified_name", None) if interaction else None,
        "error_type": type(err).__name__,
        "error": _safe_str(err),
        "traceback": tb,
    }
    _append_json_list(POST_TB_FILE, entry)


def _has_access(member: discord.Member) -> bool:
    return any(r.id in ROLE_ALLOWED for r in getattr(member, "roles", []))


async def _download_bytes(url: str) -> Tuple[Optional[bytes], str]:
    if not url:
        return None, "empty_url"
    try:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None, f"http_status_{resp.status}"
                return await resp.read(), "ok"
    except Exception as e:
        return None, f"download_error_{type(e).__name__}:{_safe_str(e)}"


def _rounded_png_from_bytes(data: bytes, radius: int = 40) -> Tuple[Optional[discord.File], Optional[str], str]:
    if not data:
        return None, None, "empty_bytes"
    try:
        image = Image.open(io.BytesIO(data)).convert("RGBA")
        w, h = image.size

        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)

        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.paste(image, (0, 0), mask)

        buff = io.BytesIO()
        out.save(buff, format="PNG")
        buff.seek(0)

        f = discord.File(buff, filename="rounded.png")
        return f, "attachment://rounded.png", "ok"
    except Exception as e:
        return None, None, f"pillow_error_{type(e).__name__}:{_safe_str(e)}"


def _clean_poll_options(raw: List[Optional[str]]) -> List[str]:
    out: List[str] = []
    for r in raw:
        if not r:
            continue
        s = r.strip()
        if not s:
            continue
        out.append(s)
    return out[:MAX_POLL_OPTIONS]


@dataclass
class PostSession:
    user_id: int
    channel_id: int
    guild_id: Optional[int]
    created_at: str

    mode: str = "post"  # post або poll

    title: Optional[str] = None
    text: Optional[str] = None

    image_url: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_filename: Optional[str] = None

    poll_options: Optional[List[str]] = None


class PostTextModal(Modal, title="Текст"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session

        self.title_input = TextInput(label="Заголовок (необовязково)", required=False, max_length=256)
        self.text_input = TextInput(label="Текст", required=True, style=discord.TextStyle.paragraph, max_length=4000)
        self.image_url_input = TextInput(
            label="Додатково: картинка по посиланню (необовязково)",
            required=False,
            placeholder="https://...png",
            max_length=400,
        )

        self.add_item(self.title_input)
        self.add_item(self.text_input)
        self.add_item(self.image_url_input)

    async def on_submit(self, interaction: Interaction):
        await self.cog._safe_call("modal_text_submit", interaction, self.cog._handle_text_submit, interaction, self.session,
                                  (self.title_input.value or "").strip() or None,
                                  (self.text_input.value or "").strip() or None,
                                  (self.image_url_input.value or "").strip() or None)


class ImageLinkModal(Modal, title="Картинка по посиланню"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session
        self.image_link = TextInput(label="Посилання", required=True, max_length=400)
        self.add_item(self.image_link)

    async def on_submit(self, interaction: Interaction):
        await self.cog._safe_call("modal_link_submit", interaction, self.cog._handle_image_link_submit, interaction, self.session,
                                  (self.image_link.value or "").strip() or None)


class PollOptionsModal(Modal, title="Опитування: варіанти"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session

        self.o1 = TextInput(label="Варіант 1", required=True, max_length=80)
        self.o2 = TextInput(label="Варіант 2", required=True, max_length=80)
        self.o3 = TextInput(label="Варіант 3 (необовязково)", required=False, max_length=80)
        self.o4 = TextInput(label="Варіант 4 (необовязково)", required=False, max_length=80)
        self.o5 = TextInput(label="Варіант 5 (необовязково)", required=False, max_length=80)

        self.add_item(self.o1)
        self.add_item(self.o2)
        self.add_item(self.o3)
        self.add_item(self.o4)
        self.add_item(self.o5)

    async def on_submit(self, interaction: Interaction):
        opts = _clean_poll_options([self.o1.value, self.o2.value, self.o3.value, self.o4.value, self.o5.value])
        await self.cog._safe_call("modal_poll_submit", interaction, self.cog._handle_poll_options_submit, interaction, self.session, opts)


class StartPostView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT_SECONDS)
        self.cog = cog
        self.session = session
        self.add_item(UploadFromDeviceButton())
        self.add_item(AddImageLinkButton())
        self.add_item(NoImageButton())
        self.add_item(PollButton())
        self.add_item(CancelButton())


class UploadFromDeviceButton(Button):
    def __init__(self):
        super().__init__(label="З машини (файл)", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        view: StartPostView = self.view  # type: ignore
        await view.cog._safe_call("btn_device", interaction, view.cog._handle_wait_file, interaction, view.session)


class AddImageLinkButton(Button):
    def __init__(self):
        super().__init__(label="З посилання", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: Interaction):
        view: StartPostView = self.view  # type: ignore
        await view.cog._safe_call("btn_link", interaction, view.cog._handle_open_link_modal, interaction, view.session)


class NoImageButton(Button):
    def __init__(self):
        super().__init__(label="Без картинки", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: Interaction):
        view: StartPostView = self.view  # type: ignore
        await view.cog._safe_call("btn_noimg", interaction, view.cog._handle_open_text_modal, interaction, view.session)


class PollButton(Button):
    def __init__(self):
        super().__init__(label="Опитування", style=discord.ButtonStyle.success)

    async def callback(self, interaction: Interaction):
        view: StartPostView = self.view  # type: ignore
        await view.cog._safe_call("btn_poll", interaction, view.cog._handle_start_poll, interaction, view.session)


class CancelButton(Button):
    def __init__(self):
        super().__init__(label="Скасувати", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: Interaction):
        view: StartPostView = self.view  # type: ignore
        await view.cog._safe_call("btn_cancel", interaction, view.cog._cancel, interaction, view.session)


class OpenModalView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT_SECONDS)
        self.cog = cog
        self.session = session
        self.add_item(OpenTextModalButton())
        self.add_item(CancelButton2())


class OpenTextModalButton(Button):
    def __init__(self):
        super().__init__(label="Відкрити модалку тексту", style=discord.ButtonStyle.success)

    async def callback(self, interaction: Interaction):
        view: OpenModalView = self.view  # type: ignore
        await view.cog._safe_call("btn_open_modal", interaction, view.cog._handle_open_text_modal, interaction, view.session)


class CancelButton2(Button):
    def __init__(self):
        super().__init__(label="Скасувати", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: Interaction):
        view: OpenModalView = self.view  # type: ignore
        await view.cog._safe_call("btn_cancel2", interaction, view.cog._cancel, interaction, view.session)


class PollButtonView(View):
    def __init__(self, options: List[str]):
        super().__init__(timeout=None)
        for label in options[:25]:
            self.add_item(PollChoiceButton(label))


class PollChoiceButton(Button):
    def __init__(self, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"✅ Обрано: **{self.label}**", ephemeral=True)
            else:
                await interaction.followup.send(f"✅ Обрано: **{self.label}**", ephemeral=True)
        except Exception:
            pass


class ConfirmView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT_SECONDS)
        self.cog = cog
        self.session = session
        self.add_item(PostWithAuthorButton())
        self.add_item(PostAnonymousButton())
        self.add_item(CancelFinalizeButton())


class PostWithAuthorButton(Button):
    def __init__(self):
        super().__init__(label="З автором", style=discord.ButtonStyle.success)

    async def callback(self, interaction: Interaction):
        view: ConfirmView = self.view  # type: ignore
        await view.cog._safe_call("btn_author", interaction, view.cog._finalize, interaction, view.session, False)


class PostAnonymousButton(Button):
    def __init__(self):
        super().__init__(label="Анонімно", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        view: ConfirmView = self.view  # type: ignore
        await view.cog._safe_call("btn_anon", interaction, view.cog._finalize, interaction, view.session, True)


class CancelFinalizeButton(Button):
    def __init__(self):
        super().__init__(label="Скасувати", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: Interaction):
        view: ConfirmView = self.view  # type: ignore
        await view.cog._safe_call("btn_cancel_finalize", interaction, view.cog._cancel, interaction, view.session)


class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: Dict[int, PostSession] = {}
        print("[COG][OK] Loaded cogs.post_cog")

    async def _reply_ephemeral(self, interaction: Interaction, content: str, *, view: Optional[View] = None, embed: Optional[discord.Embed] = None):
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True, view=view, embed=embed)
        else:
            await interaction.response.send_message(content, ephemeral=True, view=view, embed=embed)

    async def _safe_call(self, stage: str, interaction: Interaction, fn, *args):
        try:
            _log_stage(stage, interaction)
            return await fn(*args)
        except Exception as e:
            _log_stage("error", interaction, {"at": stage, "error_type": type(e).__name__, "error": _safe_str(e)})
            _log_traceback(stage, interaction, e)
            try:
                await self._reply_ephemeral(interaction, f"❌ Помилка в /post: `{type(e).__name__}`. Дивись logs/post_tracebacks.json")
            except Exception:
                pass
            return None

    async def _access_check(self, interaction: Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            await self._reply_ephemeral(interaction, "❌ Тільки на сервері.")
            return False
        if not _has_access(interaction.user):
            await self._reply_ephemeral(interaction, "⛔ Нема прав для /post.")
            return False
        return True

    def _new_session(self, interaction: Interaction) -> PostSession:
        sess = PostSession(
            user_id=interaction.user.id,
            channel_id=getattr(interaction.channel, "id", 0),
            guild_id=getattr(getattr(interaction, "guild", None), "id", None),
            created_at=_utc_now(),
        )
        self.sessions[sess.user_id] = sess
        return sess

    @app_commands.command(name="post", description="Пост або опитування через майстер")
    @app_commands.describe(image="Опційне зображення для поста (attachment з ПК)")
    async def post_cmd(self, interaction: Interaction, image: Optional[discord.Attachment] = None):
        if not await self._access_check(interaction):
            return

        sess = self._new_session(interaction)
        _log_stage("start", interaction, {"has_image": bool(image)})

        if image:
            sess.attachment_url = image.url
            sess.attachment_filename = image.filename
            _log_stage("image_set_from_slash", interaction, {"filename": image.filename})
            await interaction.response.send_modal(PostTextModal(self, sess))
            return

        view = StartPostView(self, sess)
        await interaction.response.send_message(
            "Обери варіант: з машини, з посилання, без картинки, або опитування.",
            ephemeral=True,
            view=view,
        )

    @app_commands.command(name="пост", description="Пост або опитування через майстер")
    @app_commands.describe(image="Опційне зображення для поста (attachment з ПК)")
    async def post_cmd_ua(self, interaction: Interaction, image: Optional[discord.Attachment] = None):
        await self.post_cmd(interaction, image)

    async def _cancel(self, interaction: Interaction, session: PostSession):
        self.sessions.pop(session.user_id, None)
        await self._reply_ephemeral(interaction, "Скасовано.")

    async def _handle_open_text_modal(self, interaction: Interaction, session: PostSession):
        await interaction.response.send_modal(PostTextModal(self, session))

    async def _handle_open_link_modal(self, interaction: Interaction, session: PostSession):
        await interaction.response.send_modal(ImageLinkModal(self, session))

    async def _handle_start_poll(self, interaction: Interaction, session: PostSession):
        session.mode = "poll"
        await interaction.response.send_modal(PostTextModal(self, session))

    async def _handle_image_link_submit(self, interaction: Interaction, session: PostSession, url: Optional[str]):
        session.image_url = url
        await interaction.response.send_modal(PostTextModal(self, session))

    async def _handle_wait_file(self, interaction: Interaction, session: PostSession):
        await self._reply_ephemeral(interaction, f"Надішли 1 повідомлення з картинкою (файлом). Чекаю {WAIT_FILE_TIMEOUT_SECONDS} секунд.")

        channel = interaction.channel
        if channel is None:
            await self._reply_ephemeral(interaction, "❌ Не бачу канал.")
            return

        def check(msg: discord.Message) -> bool:
            if msg.author.id != session.user_id:
                return False
            if msg.channel.id != session.channel_id:
                return False
            return bool(msg.attachments)

        msg: discord.Message = await self.bot.wait_for("message", timeout=WAIT_FILE_TIMEOUT_SECONDS, check=check)
        att = msg.attachments[0]
        session.attachment_url = att.url
        session.attachment_filename = att.filename

        view = OpenModalView(self, session)
        await self._reply_ephemeral(interaction, "✅ Файл отримано. Натисни кнопку щоб відкрити модалку тексту.", view=view)

    async def _handle_text_submit(self, interaction: Interaction, session: PostSession, title: Optional[str], text: Optional[str], img: Optional[str]):
        session.title = title
        session.text = text
        if img:
            session.image_url = img

        if session.mode == "poll" and not session.poll_options:
            await interaction.response.send_modal(PollOptionsModal(self, session))
            return

        await self._show_confirm(interaction, session)

    async def _handle_poll_options_submit(self, interaction: Interaction, session: PostSession, options: List[str]):
        if len(options) < 2:
            await self._reply_ephemeral(interaction, "❌ Треба мінімум 2 варіанти.")
            return
        session.poll_options = options
        await self._show_confirm(interaction, session)

    async def _show_confirm(self, interaction: Interaction, session: PostSession):
        preview = discord.Embed(title=session.title or "", description=session.text or "", color=discord.Color.teal())
        if session.mode == "poll" and session.poll_options:
            preview.add_field(name="Опитування", value="\n".join([f"- {o}" for o in session.poll_options]), inline=False)

        view = ConfirmView(self, session)
        await self._reply_ephemeral(interaction, "Підтверди: анонімно чи з автором.", view=view, embed=preview)

    async def _finalize(self, interaction: Interaction, session: PostSession, anonymous: bool):
        embed = discord.Embed(title=session.title or "", description=session.text or "", color=discord.Color.teal())
        if not anonymous:
            u = interaction.user
            if hasattr(u, "display_avatar"):
                embed.set_author(name=u.display_name, icon_url=u.display_avatar.url)

        file_to_send = None

        if session.attachment_url:
            data, reason = await _download_bytes(session.attachment_url)
            _log_stage("image_download_attachment", interaction, {"reason": reason, "has_bytes": bool(data)})
            if data:
                f, attach_url, r = _rounded_png_from_bytes(data)
                _log_stage("image_round_attachment", interaction, {"reason": r, "has_file": bool(f)})
                if f and attach_url:
                    file_to_send = f
                    embed.set_image(url=attach_url)

        if (not file_to_send) and session.image_url:
            data, reason = await _download_bytes(session.image_url)
            _log_stage("image_download_url", interaction, {"reason": reason, "has_bytes": bool(data)})
            if data:
                f, attach_url, r = _rounded_png_from_bytes(data)
                _log_stage("image_round_url", interaction, {"reason": r, "has_file": bool(f)})
                if f and attach_url:
                    file_to_send = f
                    embed.set_image(url=attach_url)

        view = None
        if session.mode == "poll" and session.poll_options:
            view = PollButtonView(session.poll_options)

        channel = interaction.channel
        if channel is None or not hasattr(channel, "send"):
            await self._reply_ephemeral(interaction, "❌ Не бачу канал для поста.")
            return

        if file_to_send:
            await channel.send(embed=embed, view=view, file=file_to_send)
        else:
            await channel.send(embed=embed, view=view)

        self.sessions.pop(session.user_id, None)
        await self._reply_ephemeral(interaction, "✅ Готово.")


async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))
