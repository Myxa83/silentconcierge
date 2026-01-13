# -*- coding: utf-8 -*-
import io
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


LOG_DIR = Path("logs")
POST_LOG_FILE = LOG_DIR / "post_logs.json"

HTTP_TIMEOUT_SECONDS = 15
VIEW_TIMEOUT_SECONDS = 600  # 10 хв


def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _append_post_log(entry: Dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        data = []
        if POST_LOG_FILE.exists():
            try:
                data = json.loads(POST_LOG_FILE.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []
        data.append(entry)
        POST_LOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _safe_str(x: Any, limit: int = 400) -> str:
    try:
        s = str(x)
    except Exception:
        s = "<unprintable>"
    if len(s) > limit:
        return s[:limit] + "...(cut)"
    return s


@dataclass
class PostSession:
    channel_id: int
    guild_id: Optional[int]
    user_id: int

    title: Optional[str] = None
    text: Optional[str] = None
    image_url: Optional[str] = None

    attachment_filename: Optional[str] = None
    attachment_bytes: Optional[bytes] = None  # якщо прикріпили файл-картинку

    created_at: str = ""


async def _download_bytes(url: str) -> Tuple[Optional[bytes], Optional[str]]:
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


def _rounded_png_from_bytes(data: bytes, radius: int = 40) -> Tuple[Optional[discord.File], Optional[str], Optional[str]]:
    """
    Робить округлення, повертає (discord.File, attachment_url, debug_reason)
    Ніколи не кидає виняток назовні.
    """
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


class AddImageView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT_SECONDS)
        self.cog = cog
        self.session = session

        self.add_item(AddImageButton())
        self.add_item(SkipImageButton())


class AddImageButton(Button):
    def __init__(self):
        super().__init__(label="Додати картинку (файл)", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        view: AddImageView = self.view  # type: ignore
        await view.cog._handle_add_image_click(interaction, view.session)


class SkipImageButton(Button):
    def __init__(self):
        super().__init__(label="Без картинки", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: Interaction):
        view: AddImageView = self.view  # type: ignore
        await view.cog._handle_skip_image_click(interaction, view.session)


class ImageUploadModal(Modal, title="Додати картинку файлом"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session

        self.image_link = TextInput(
            label="Посилання на картинку (якщо хочеш через URL)",
            required=False,
            placeholder="https://...png або GitHub raw",
            max_length=400,
        )
        self.add_item(self.image_link)

    async def on_submit(self, interaction: Interaction):
        url = (self.image_link.value or "").strip() or None
        await self.cog._handle_image_modal_submit(interaction, self.session, url)


class PostTextModal(Modal, title="Текст поста"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session

        self.title_input = TextInput(
            label="Заголовок (необовязково)",
            required=False,
            max_length=256,
        )
        self.text_input = TextInput(
            label="Текст",
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=4000,
        )
        self.image_url_input = TextInput(
            label="Картинка по посиланню (необовязково)",
            required=False,
            placeholder="https://...png або GitHub raw",
            max_length=400,
        )

        self.add_item(self.title_input)
        self.add_item(self.text_input)
        self.add_item(self.image_url_input)

    async def on_submit(self, interaction: Interaction):
        title = (self.title_input.value or "").strip() or None
        text = (self.text_input.value or "").strip() or None
        img = (self.image_url_input.value or "").strip() or None
        await self.cog._handle_text_modal_submit(interaction, self.session, title, text, img)


class AnonChoiceView(View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT_SECONDS)
        self.cog = cog
        self.session = session

        self.add_item(PostWithAuthorButton())
        self.add_item(PostAnonymousButton())
        self.add_item(CancelPostButton())


class PostWithAuthorButton(Button):
    def __init__(self):
        super().__init__(label="Пост з автором", style=discord.ButtonStyle.success)

    async def callback(self, interaction: Interaction):
        view: AnonChoiceView = self.view  # type: ignore
        await view.cog._finalize_post(interaction, view.session, anonymous=False)


class PostAnonymousButton(Button):
    def __init__(self):
        super().__init__(label="Анонімно", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        view: AnonChoiceView = self.view  # type: ignore
        await view.cog._finalize_post(interaction, view.session, anonymous=True)


class CancelPostButton(Button):
    def __init__(self):
        super().__init__(label="Скасувати", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: Interaction):
        view: AnonChoiceView = self.view  # type: ignore
        await view.cog._cancel_post(interaction, view.session)


class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: Dict[int, PostSession] = {}
        print("[COG][OK] Loaded cogs.post_cog")

    def _log(self, stage: str, interaction: Interaction, extra: Optional[Dict[str, Any]] = None):
        entry = {
            "time": _utc_now(),
            "stage": stage,
            "user_id": getattr(interaction.user, "id", None),
            "guild_id": getattr(getattr(interaction, "guild", None), "id", None),
            "channel_id": getattr(getattr(interaction, "channel", None), "id", None),
            "cmd": getattr(getattr(interaction, "command", None), "qualified_name", None),
        }
        if extra:
            entry.update(extra)
        _append_post_log(entry)
        print(f"[POST][DBG] stage={stage} user={entry['user_id']} cmd={entry['cmd']}")

    async def _reply_ephemeral(self, interaction: Interaction, content: str, *, view: Optional[View] = None):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True, view=view)
            else:
                await interaction.response.send_message(content, ephemeral=True, view=view)
        except Exception:
            pass

    def _get_or_create_session(self, interaction: Interaction) -> PostSession:
        uid = interaction.user.id
        sess = PostSession(
            channel_id=getattr(interaction.channel, "id", 0),
            guild_id=getattr(getattr(interaction, "guild", None), "id", None),
            user_id=uid,
            created_at=_utc_now(),
        )
        self.sessions[uid] = sess
        return sess

    # ---------- PUBLIC COMMANDS ----------
    @app_commands.command(name="post", description="Створити пост через модалки")
    async def post_cmd(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        sess = self._get_or_create_session(interaction)
        self._log("start", interaction)

        view = AddImageView(self, sess)
        await interaction.followup.send(
            "Починаємо пост.\nСпочатку вибери: додати картинку чи без неї.",
            ephemeral=True,
            view=view,
        )

    @app_commands.command(name="пост", description="Створити пост через модалки")
    async def post_cmd_ua(self, interaction: Interaction):
        await self.post_cmd(interaction)

    # ---------- FLOW HANDLERS ----------
    async def _handle_add_image_click(self, interaction: Interaction, session: PostSession):
        self._log("add_image_click", interaction)

        # Тут нема прямого способу отримати файл у кнопці, тому робимо модалку з URL.
        # А файл можна прикріпити до наступного повідомлення користувача руками, але це складніше.
        # Тому робимо: або URL, або пропуск. Якщо хочеш саме файл, я дам окрему схему з "слухати наступне повідомлення".
        await interaction.response.send_modal(ImageUploadModal(self, session))

    async def _handle_skip_image_click(self, interaction: Interaction, session: PostSession):
        self._log("skip_image_click", interaction)
        await interaction.response.send_modal(PostTextModal(self, session))

    async def _handle_image_modal_submit(self, interaction: Interaction, session: PostSession, url: Optional[str]):
        self._log("image_modal_submit", interaction, {"url": url})

        # Зберігаємо URL як "попередню картинку". Реально підтягнемо при фіналі.
        session.image_url = url or session.image_url

        # Далі текст
        await interaction.response.send_modal(PostTextModal(self, session))

    async def _handle_text_modal_submit(self, interaction: Interaction, session: PostSession, title: Optional[str], text: Optional[str], img: Optional[str]):
        self._log("text_modal_submit", interaction, {
            "title_set": bool(title),
            "text_len": len(text or ""),
            "img_set": bool(img),
        })

        session.title = title
        session.text = text
        if img:
            session.image_url = img

        # Показуємо превю і вибір анонімності
        preview = discord.Embed(
            title=session.title or "",
            description=session.text or "",
            color=discord.Color.teal()
        )
        preview_note = "Підтверди пост: анонімно чи з автором."

        view = AnonChoiceView(self, session)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(preview_note, ephemeral=True, embed=preview, view=view)
            else:
                await interaction.response.send_message(preview_note, ephemeral=True, embed=preview, view=view)
        except Exception:
            pass

    async def _cancel_post(self, interaction: Interaction, session: PostSession):
        self._log("cancel", interaction)
        self.sessions.pop(session.user_id, None)
        await self._reply_ephemeral(interaction, "Скасовано.", view=None)

    async def _finalize_post(self, interaction: Interaction, session: PostSession, anonymous: bool):
        self._log("finalize_start", interaction, {"anonymous": anonymous})

        # Захист від протухлої сесії
        if not session.text and not session.title and not session.image_url and not session.attachment_bytes:
            self._log("finalize_empty_session", interaction)
            await self._reply_ephemeral(interaction, "Сесія порожня. Запусти /post ще раз.")
            self.sessions.pop(session.user_id, None)
            return

        try:
            # Build embed
            embed = discord.Embed(
                title=session.title or "",
                description=session.text or "",
                color=discord.Color.teal(),
            )

            if not anonymous:
                try:
                    u = interaction.user
                    embed.set_author(name=u.display_name, icon_url=u.display_avatar.url)
                except Exception:
                    pass

            file_to_send = None

            # Image priority:
            # 1) session.attachment_bytes (поки не використовуємо в цій версії)
            # 2) session.image_url (якщо є)
            if session.image_url:
                self._log("image_download_start", interaction, {"url": session.image_url})
                data, reason = await _download_bytes(session.image_url)
                self._log("image_download_done", interaction, {"reason": reason, "has_bytes": bool(data)})
                if data:
                    f, attach_url, img_reason = _rounded_png_from_bytes(data)
                    self._log("image_round_done", interaction, {"reason": img_reason, "has_file": bool(f)})
                    if f and attach_url:
                        file_to_send = f
                        embed.set_image(url=attach_url)

            # Send to channel
            channel = interaction.channel
            if channel is None or not hasattr(channel, "send"):
                self._log("finalize_no_channel", interaction)
                await self._reply_ephemeral(interaction, "Не бачу канал для відправки поста.")
                return

            self._log("send_channel_start", interaction, {"has_file": bool(file_to_send)})

            if file_to_send:
                await channel.send(embed=embed, file=file_to_send)
            else:
                await channel.send(embed=embed)

            self._log("send_channel_done", interaction)

            await self._reply_ephemeral(interaction, "✅ Пост опубліковано.")
            self.sessions.pop(session.user_id, None)

        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            self._log("finalize_error", interaction, {"error_type": type(e).__name__, "error": _safe_str(e, 800)})
            _append_post_log({
                "time": _utc_now(),
                "stage": "finalize_traceback",
                "traceback": tb,
            })
            await self._reply_ephemeral(interaction, f"❌ Помилка: `{type(e).__name__}: {_safe_str(e, 300)}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))
