# -*- coding: utf-8 -*-
import io
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

import aiohttp
import discord
from discord.ext import commands
from discord import app_commands, Interaction
from discord.ui import View, Button
from PIL import Image, ImageDraw


LOG_DIR = Path("logs")
POST_LOG_FILE = LOG_DIR / "post_logs.json"


def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _append_post_log(entry: dict) -> None:
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


def _parse_options(opts: List[Optional[str]]) -> List[str]:
    return [o.strip() for o in opts if o and o.strip()]


async def rounded_image_from_url(url: str) -> Tuple[Optional[discord.File], Optional[str]]:
    """
    Завжди повертає 2 значення: (file, attachment_url) або (None, None).
    """
    if not url:
        return None, None

    try:
        timeout = aiohttp.ClientTimeout(total=12)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None, None
                data = await resp.read()
    except Exception:
        return None, None

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
        return file, "attachment://rounded.png"
    except Exception:
        return None, None


class PostButton(Button):
    def __init__(self, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(self, interaction: Interaction):
        try:
            await interaction.response.send_message(f"✅ Ви обрали: **{self.label}**", ephemeral=True)
        except Exception:
            pass


class PostView(View):
    def __init__(self, options: List[str]):
        super().__init__(timeout=None)
        for label in options[:25]:
            self.add_item(PostButton(label))


class PostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[COG][OK] Loaded cogs.post_cog")

    async def _run_post(
        self,
        interaction: Interaction,
        заголовок: Optional[str],
        текст: Optional[str],
        картинка: Optional[str],
        шрифт: Optional[str],
        options: List[Optional[str]],
    ):
        # Відповідаємо одразу, щоб не було "Програма не відповідає"
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            opts = _parse_options(options)

            if not any([заголовок, текст, картинка, шрифт, opts]):
                await interaction.followup.send("❌ Ви не заповнили жодне поле.", ephemeral=True)
                return

            embed = None
            file = None

            if заголовок or текст or картинка or шрифт:
                embed = discord.Embed(
                    title=заголовок or "",
                    description=текст or "",
                    color=discord.Color.teal(),
                )
                if шрифт:
                    embed.set_author(name=f"Шрифт: {шрифт}")

                if картинка:
                    file, image_url = await rounded_image_from_url(картинка)
                    if image_url:
                        embed.set_image(url=image_url)

            view = PostView(opts) if opts else None

            # Публічний пост в канал
            channel = interaction.channel

            # Лог старту
            _append_post_log({
                "time": _utc_now(),
                "event": "post_start",
                "cmd": getattr(getattr(interaction, "command", None), "qualified_name", None),
                "user_id": getattr(interaction.user, "id", None),
                "guild_id": getattr(getattr(interaction, "guild", None), "id", None),
                "channel_id": getattr(channel, "id", None),
                "has_embed": bool(embed),
                "has_view": bool(view),
                "has_file": bool(file),
            })

            if not embed and view:
                await channel.send("📊 Виберіть варіант:", view=view)
            elif embed and view:
                if file:
                    await channel.send(embed=embed, view=view, file=file)
                else:
                    await channel.send(embed=embed, view=view)
            elif embed:
                if file:
                    await channel.send(embed=embed, file=file)
                else:
                    await channel.send(embed=embed)
            else:
                # Теоретично сюди не попадемо, але хай буде
                await channel.send("❌ Ви не заповнили жодне поле.")

            await interaction.followup.send("✅ Пост відправлено.", ephemeral=True)

            _append_post_log({
                "time": _utc_now(),
                "event": "post_done",
                "user_id": getattr(interaction.user, "id", None),
            })

        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            print(f"[POST][ERR] {type(e).__name__}: {e}")
            _append_post_log({
                "time": _utc_now(),
                "event": "post_error",
                "error_type": type(e).__name__,
                "error": str(e),
                "traceback": tb,
            })

            try:
                await interaction.followup.send(f"❌ Помилка: `{type(e).__name__}: {e}`", ephemeral=True)
            except Exception:
                pass

    # Латиниця: /post
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
    ):
        await self._run_post(
            interaction,
            заголовок,
            текст,
            картинка,
            шрифт,
            [опитування1, опитування2, опитування3, опитування4, опитування5],
        )

    # Кирилиця: /пост
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
    ):
        await self._run_post(
            interaction,
            заголовок,
            текст,
            картинка,
            шрифт,
            [опитування1, опитування2, опитування3, опитування4, опитування5],
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PostCog(bot))
