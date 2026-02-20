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
from discord.ui import View, Modal, TextInput
from PIL import Image, ImageDraw

# ============================ CONFIG ============================
FOOTER_TEXT = "Silent Concierge by Myxa"
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "post_logs.json"
TB_FILE = LOG_DIR / "post_tracebacks.json"

HTTP_TIMEOUT = 15
WAIT_FILE_TIMEOUT = 180
VIEW_TIMEOUT = 600
ROUND_RADIUS = 40

# ============================ UTILS ============================

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
    
    # ПЕРЕВІРКА НА GIF: якщо це гіфка, ми її не обробляємо, щоб не вбити анімацію
    if url.lower().split('?')[0].endswith('.gif'):
        return None, url, "ok_gif"

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
    m = re.search(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)", link or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))

def has_access(member: discord.Member) -> bool:
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

# ============================ UI ============================

class TextModal(Modal, title="Текст поста"):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__()
        self.cog = cog
        self.session = session
        self.title_input = TextInput(label="Заголовок", required=False, max_length=256, default=session.title or "")
        self.text_input = TextInput(label="Текст", style=discord.TextStyle.paragraph, required=True, max_length=4000, default=session.text or "")
        self.add_item(self.title_input)
        self.add_item(self.text_input)

    async def on_submit(self, interaction: Interaction):
        try:
            self.session.title = (self.title_input.value or "").strip() or None
            self.session.text = (self.text_input.value or "").strip()
            log_event("text_modal_submit", interaction, {"edit_mode": self.session.edit_mode})
            await interaction.response.send_message("Показувати автора?", ephemeral=True, view=AuthorView(self.cog, self.session))
        except Exception as e:
            log_tb("text_modal_submit", interaction, e)

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
        await interaction.response.send_modal(TextModal(self.cog, self.session))

class ImageChoiceView(discord.ui.View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="З ПК", style=discord.ButtonStyle.primary)
    async def from_pc(self, interaction: Interaction, _):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("Надішли картинку файлом у цей канал.", ephemeral=True)
            
            def check(m: discord.Message) -> bool:
                return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id and bool(m.attachments)

            msg = await self.cog.bot.wait_for("message", timeout=WAIT_FILE_TIMEOUT, check=check)
            self.session.image_url = msg.attachments[0].url
            await interaction.followup.send_modal(TextModal(self.cog, self.session))
        except:
            await interaction.followup.send("❌ Час очікування вийшов.", ephemeral=True)

    @discord.ui.button(label="З посилання", style=discord.ButtonStyle.secondary)
    async def from_link(self, interaction: Interaction, _):
        await interaction.response.send_modal(LinkModal(self.cog, self.session))

    @discord.ui.button(label="Без картинки", style=discord.ButtonStyle.secondary)
    async def no_image(self, interaction: Interaction, _):
        self.session.image_url = None
        self.session.remove_image = True
        await interaction.response.send_modal(TextModal(self.cog, self.session))

class EditImageChoiceView(discord.ui.View):
    def __init__(self, cog: "PostCog", session: PostSession):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.cog = cog
        self.session = session

    @discord.ui.button(label="Залишити поточну", style=discord.ButtonStyle.success)
    async def keep(self, interaction: Interaction, _):
        self.session.keep_existing_image = True
        await interaction.response.send_modal(TextModal(self.cog, self.session))

    @discord.ui.button(label="Замінити (ПК)", style=discord.ButtonStyle.primary)
    async def repl_pc(self, interaction: Interaction, _):
        await interaction.response.send_message("Надішли файл.", ephemeral=True)
        def check(m: discord.Message) -> bool:
            return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id and bool(m.attachments)
        try:
            msg = await self.cog.bot.wait_for("message", timeout=WAIT_FILE_TIMEOUT, check=check)
            self.session.image_url = msg.attachments[0].url
            await interaction.followup.send_modal(TextModal(self.cog, self.session))
        except:
            await interaction.followup.send("❌ Помилка.", ephemeral=True)

    @discord.ui.button(label="Прибрати картинку", style=discord.ButtonStyle.danger)
    async def remove(self, interaction: Interaction, _):
        self.session.remove_image = True
        await interaction.response.send_modal(TextModal(self.cog, self.session))

class AuthorView(discord.ui.View):
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

class FooterView(discord.ui.View):
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

# ============================ COG ============================

class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="post", description="Створити пост")
    @app_commands.describe(image="Прикріпи файл одразу")
    async def post_cmd(self, interaction: Interaction, image: Optional[discord.Attachment] = None):
        if not isinstance(interaction.user, discord.Member) or not has_access(interaction.user):
            return await interaction.response.send_message("⛔ Нема прав.", ephemeral=True)

        sess = PostSession()
        if image:
            sess.image_url = image.url
            await interaction.response.send_modal(TextModal(self, sess))
        else:
            await interaction.response.send_message("Обери картинку:", ephemeral=True, view=ImageChoiceView(self, sess))

    @app_commands.command(name="post_edit", description="Редагувати пост бота")
    @app_commands.describe(message_link="Посилання на повідомлення")
    async def post_edit_cmd(self, interaction: Interaction, message_link: str):
        if not isinstance(interaction.user, discord.Member) or not has_access(interaction.user):
            return await interaction.response.send_message("⛔ Нема прав.", ephemeral=True)

        parsed = parse_message_link(message_link)
        if not parsed:
            return await interaction.response.send_message("❌ Невірне посилання.", ephemeral=True)

        _, c_id, m_id = parsed
        channel = self.bot.get_channel(c_id) or await self.bot.fetch_channel(c_id)
        msg = await channel.fetch_message(m_id)

        if msg.author.id != self.bot.user.id:
            return await interaction.response.send_message("❌ Це не мій пост.", ephemeral=True)

        title, text, anon, foot, has_img = None, "", True, False, False
        if msg.embeds:
            emb = msg.embeds[0]
            title, text = emb.title, emb.description or ""
            anon = not (emb.author and emb.author.name)
            foot = bool(emb.footer and emb.footer.text)
            has_img = bool(emb.image and emb.image.url)

        sess = PostSession(title=title, text=text, anonymous=anon, footer=foot, edit_mode=True, target_channel_id=c_id, target_message_id=m_id)
        
        if has_img:
            await interaction.response.send_message("Що з картинкою?", ephemeral=True, view=EditImageChoiceView(self, sess))
        else:
            await interaction.response.send_message("Додати картинку?", ephemeral=True, view=ImageChoiceView(self, sess))

    async def finalize(self, interaction: Interaction, session: PostSession):
        await interaction.response.defer(ephemeral=True)
        
        embed = discord.Embed(title=session.title or "", description=session.text or "", color=discord.Color.teal())
        if not session.anonymous:
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        if session.footer:
            embed.set_footer(text=FOOTER_TEXT, icon_url=self.bot.user.display_avatar.url)

        # Редагування
        if session.edit_mode:
            channel = await self.bot.fetch_channel(session.target_channel_id)
            msg = await channel.fetch_message(session.target_message_id)
            
            if session.keep_existing_image and msg.embeds and msg.embeds[0].image:
                embed.set_image(url=msg.embeds[0].image.url)
                await msg.edit(embed=embed)
            elif session.remove_image:
                await msg.edit(embed=embed, attachments=[])
            elif session.image_url:
                f, url, _ = await download_and_round(session.image_url)
                if f:
                    embed.set_image(url=url)
                    await msg.edit(embed=embed, attachments=[f])
                else: # Це випадок для GIF або якщо завантаження не потрібне
                    embed.set_image(url=url)
                    await msg.edit(embed=embed, attachments=[])
            else:
                await msg.edit(embed=embed)
            return await interaction.followup.send("✅ Оновлено.", ephemeral=True)

        # Створення
        f_send = None
        url_to_set = None
        if session.image_url:
            f_send, url_to_set, _ = await download_and_round(session.image_url)
            if url_to_set: embed.set_image(url=url_to_set)

        if f_send: 
            await interaction.channel.send(embed=embed, file=f_send)
        else: 
            await interaction.channel.send(embed=embed)
        
        await interaction.followup.send("✅ Готово.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))
