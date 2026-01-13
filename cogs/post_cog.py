# -*- coding: utf-8 -*-
import io
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Any, Dict

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, Button
from PIL import Image, ImageDraw


LOG_DIR = Path("logs")
POST_LOG_FILE = LOG_DIR / "post_logs.json"

HTTP_TIMEOUT_SECONDS = 12
MAX_BUTTONS = 25


def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _safe_str(v: Any, limit: int = 500) -> str:
    try:
        s = str(v)
    except Exception:
        s = "<unprintable>"
    if len(s) > limit:
        return s[:limit] + "...(cut)"
    return s


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
        # лог не має валити бота
        pass


def _parse_options(opts: List[Optional[str]]) -> List[str]:
    cleaned: List[str] = []
    for o in opts:
        if not o:
            continue
        s = o.strip()
        if not s:
            continue
        cleaned.append(s)
    return cleaned[:MAX_BUTTONS]


async def rounded_image_from_url(url: str) -> Tuple[Optional[discord.File], Optional[str], Optional[str]]:
    """
    Returns: (file, attachment_url, debug_reason)
    Never crashes, never returns single None.
    """
    if not url:
        return None, None, "empty_url"

    try:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None, None, f"http_status_{resp.status}"
                data = await resp.read()
    except Exception as e:
        return None, None, f"download_error_{type(e).__name__}:{_safe_str(e, 200)}"

    try:
        image = Image.open(io.BytesIO(data)).convert("RGBA")
        w, h = image.size
        radius = 40

        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle((0, 0, w, h), radius=radius, fill=255)

        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.paste(image, (0, 0), mask)

        buffer = io.BytesIO()
        out.save(buffer, format="PNG")
        buffer.seek(0)

        file = discord.File(buffer, filename="rounded.png")
        return file, "attachment://rounded.png", "ok"
    except Exception as e:
        return None, None, f"pillow_error_{type(e).__name__}:{_safe_str(e, 200)}"


class PostButton(Button):
    def __init__(self, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"✅ Ви обрали: **{self.label}**",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    f"✅ Ви обрали: **{self.label}**",
                    ephemeral=True
                )
        except Exception:
            pass


class PostView(View):
    def __init__(self, options: List[str]):
        super().__init__(timeout=None)
        for label in options[:MAX_BUTTONS]:
            self.add_item(PostButton(label))


class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[COG][OK] Loaded cogs.post_cog")

    async def _defer(self, interaction: Interaction, debug: bool) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
        except Exception as e:
            _append_post_log({
                "time": _utc_now(),
                "stage": "defer_fail",
                "error_type": type(e).__name__,
                "error": _safe_str(e),
            })
            if debug:
                print(f"[POST][DBG] defer_fail {type(e).__name__}: {_safe_str(e)}")

    async def _reply_ephemeral(self, interaction: Interaction, content: str) -> None:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)
        except Exception:
            pass

    async def _run_post(
        self,
        interaction: Interaction,
        title: Optional[str],
        text: Optional[str],
        image_url: Optional[str],
        font: Optional[str],
        options: List[Optional[str]],
        debug: bool,
    ):
        await self._defer(interaction, debug=debug)

        cmd_name = getattr(getattr(interaction, "command", None), "qualified_name", None)
        guild_id = getattr(getattr(interaction, "guild", None), "id", None)
        channel_id = getattr(getattr(interaction, "channel", None), "id", None)
        user_id = getattr(getattr(interaction, "user", None), "id", None)

        # Stage: received
        recv_entry = {
            "time": _utc_now(),
            "stage": "received",
            "cmd": cmd_name,
            "user_id": user_id,
            "guild_id": guild_id,
            "channel_id": channel_id,
            "title": title,
            "text_len": (len(text) if text else 0),
            "image_url": image_url,
            "font": font,
            "options_raw": options,
        }
        _append_post_log(recv_entry)
        if debug:
            print(
                "[POST][DBG] received "
                f"cmd={cmd_name} user={user_id} guild={guild_id} channel={channel_id} "
                f"title={bool(title)} text_len={(len(text) if text else 0)} image={bool(image_url)} font={bool(font)} "
                f"opt_raw={len([o for o in options if o])}"
            )

        try:
            opts = _parse_options(options)

            # Stage: parsed
            _append_post_log({
                "time": _utc_now(),
                "stage": "parsed",
                "cmd": cmd_name,
                "options_parsed": opts,
                "options_count": len(opts),
            })
            if debug:
                print(f"[POST][DBG] parsed options_count={len(opts)}")

            if not any([title, text, image_url, font, opts]):
                _append_post_log({
                    "time": _utc_now(),
                    "stage": "empty_fields",
                    "cmd": cmd_name,
                    "title": title,
                    "text_len": (len(text) if text else 0),
                    "image": image_url,
                    "font": font,
                    "options_count": len(opts),
                })
                await self._reply_ephemeral(
                    interaction,
                    "❌ Ви не заповнили жодне поле.\n"
                    f"DEBUG: title={bool(title)}, text_len={(len(text) if text else 0)}, "
                    f"image={bool(image_url)}, font={bool(font)}, options={len(opts)}"
                )
                return

            # Build embed
            embed = discord.Embed(color=discord.Color.teal())
            if title:
                embed.title = title
            if text:
                embed.description = text
            if font:
                embed.set_author(name=f"Шрифт: {font}")

            file = None
            attach_url = None
            img_debug = None

            if image_url:
                file, attach_url, img_debug = await rounded_image_from_url(image_url)
                _append_post_log({
                    "time": _utc_now(),
                    "stage": "image_processed",
                    "cmd": cmd_name,
                    "image_url": image_url,
                    "image_result": img_debug,
                    "has_file": bool(file),
                    "attach_url": attach_url,
                })
                if debug:
                    print(f"[POST][DBG] image_processed result={img_debug} has_file={bool(file)}")

                if attach_url:
                    embed.set_image(url=attach_url)

            view = PostView(opts) if opts else None

            # Stage: sending
            _append_post_log({
                "time": _utc_now(),
                "stage": "sending",
                "cmd": cmd_name,
                "has_embed": True,
                "has_view": bool(view),
                "has_file": bool(file),
            })
            if debug:
                print(f"[POST][DBG] sending has_view={bool(view)} has_file={bool(file)}")

            channel = interaction.channel
            if channel is None:
                await self._reply_ephemeral(interaction, "❌ Не можу визначити канал для посту.")
                _append_post_log({
                    "time": _utc_now(),
                    "stage": "fail_no_channel",
                    "cmd": cmd_name,
                })
                return

            # Send public message to the channel
            if view and file:
                await channel.send(embed=embed, view=view, file=file)
            elif view and not file:
                await channel.send(embed=embed, view=view)
            elif (not view) and file:
                await channel.send(embed=embed, file=file)
            else:
                await channel.send(embed=embed)

            # Stage: done
            _append_post_log({
                "time": _utc_now(),
                "stage": "done",
                "cmd": cmd_name,
                "user_id": user_id,
            })
            await self._reply_ephemeral(interaction, "✅ Пост відправлено.")

        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            print(f"[POST][ERR] {type(e).__name__}: {e}")
            _append_post_log({
                "time": _utc_now(),
                "stage": "post_error",
                "cmd": cmd_name,
                "error_type": type(e).__name__,
                "error": _safe_str(e, 1000),
                "traceback": tb,
            })
            await self._reply_ephemeral(interaction, f"❌ Помилка: `{type(e).__name__}: {_safe_str(e, 300)}`")

    # Latin: /post
    @app_commands.command(name="post", description="Create a post or poll with buttons")
    @app_commands.describe(
        заголовок="Заголовок повідомлення",
        текст="Основний текст (markdown підтримується)",
        картинка="Посилання на зображення (буде округлене)",
        шрифт="Назва шрифту (як текст)",
        опитування1="Варіант 1",
        опитування2="Варіант 2",
        опитування3="Варіант 3",
        опитування4="Варіант 4",
        опитування5="Варіант 5",
        debug="Показати debug в логах і коротко в консолі",
    )
    async def post_cmd(
        self,
        interaction: Interaction,
        заголовок: str = None,
        текст: str = None,
        картинка: str = None,
        шрифт: str = None,
        опитування1: str = None,
        опитування2: str = None,
        опитування3: str = None,
        опитування4: str = None,
        опитування5: str = None,
        debug: bool = False,
    ):
        await self._run_post(
            interaction=interaction,
            title=заголовок,
            text=текст,
            image_url=картинка,
            font=шрифт,
            options=[опитування1, опитування2, опитування3, опитування4, опитування5],
            debug=debug,
        )

    # Ukrainian: /пост
    @app_commands.command(name="пост", description="Створити допис або опитування з кнопками")
    @app_commands.describe(
        заголовок="Заголовок повідомлення",
        текст="Основний текст (markdown підтримується)",
        картинка="Посилання на зображення (буде округлене)",
        шрифт="Назва шрифту (як текст)",
        опитування1="Варіант 1",
        опитування2="Варіант 2",
        опитування3="Варіант 3",
        опитування4="Варіант 4",
        опитування5="Варіант 5",
        debug="Показати debug в логах і коротко в консолі",
    )
    async def post_ua_cmd(
        self,
        interaction: Interaction,
        заголовок: str = None,
        текст: str = None,
        картинка: str = None,
        шрифт: str = None,
        опитування1: str = None,
        опитування2: str = None,
        опитування3: str = None,
        опитування4: str = None,
        опитування5: str = None,
        debug: bool = False,
    ):
        await self._run_post(
            interaction=interaction,
            title=заголовок,
            text=текст,
            image_url=картинка,
            font=шрифт,
            options=[опитування1, опитування2, опитування3, опитування4, опитування5],
            debug=debug,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))
