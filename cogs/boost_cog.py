# -*- coding: utf-8 -*-
import io
import traceback
from pathlib import Path
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from data.mongo_store import append_event, load_state, save_state


# ===================== CONFIG =====================

BOOST_CHANNEL_ID = 1324474229437108264

STATE_COLLECTION = "boost_state"
ERROR_COLLECTION = "boost_errors"

ASSETS_DIR = Path("assets")
BANNER_TEMPLATE = ASSETS_DIR / "boost_banner.png"

# Аватар
AVATAR_X = 722
AVATAR_Y = 52
AVATAR_SIZE = 126

# Цифри
LEVEL_FROM_X = 412
LEVEL_FROM_Y = 163

LEVEL_TO_X = 592
LEVEL_TO_Y = 163

LEVEL_FONT_PATH = ASSETS_DIR / "fonts" / "CinzelDecorative-Bold.ttf"
LEVEL_FONT_SIZE = 72

# Стиль цифр
TEXT_TOP_COLOR = (236, 196, 102)
TEXT_BOTTOM_COLOR = (118, 74, 35)
TEXT_STROKE_COLOR = (27, 22, 19)
TEXT_SHADOW_COLOR = (0, 0, 0, 190)
TEXT_GLOW_COLOR = (255, 185, 70, 90)


# ===================== UTILS =====================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_error(stage: str, err: Exception) -> None:
    append_event(ERROR_COLLECTION, {
        "time": now_iso(),
        "stage": stage,
        "error_type": type(err).__name__,
        "error": str(err),
        "traceback": traceback.format_exc(),
    })
    print(f"[BOOST_BANNER_ERROR] {stage}: {type(err).__name__}: {err}", flush=True)


async def download_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


def circle_crop(img: Image.Image, size: int) -> Image.Image:
    img = img.convert("RGBA").resize((size, size), Image.LANCZOS)

    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size, size), fill=255)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def get_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(LEVEL_FONT_PATH), size)
    except Exception:
        return ImageFont.load_default()


def make_vertical_gradient(size: tuple[int, int], top_color, bottom_color) -> Image.Image:
    w, h = size
    gradient = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = gradient.load()

    for y in range(h):
        ratio = y / max(h - 1, 1)
        r = int(top_color[0] * (1 - ratio) + bottom_color[0] * ratio)
        g = int(top_color[1] * (1 - ratio) + bottom_color[1] * ratio)
        b = int(top_color[2] * (1 - ratio) + bottom_color[2] * ratio)

        for x in range(w):
            pix[x, y] = (r, g, b, 255)

    return gradient


def draw_luxury_number(
    base: Image.Image,
    text: str,
    center_x: int,
    center_y: int,
    font: ImageFont.FreeTypeFont,
) -> None:
    bbox = font.getbbox(text, stroke_width=3)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    pad = 18
    layer_w = text_w + pad * 2
    layer_h = text_h + pad * 2

    x = int(center_x - layer_w / 2)
    y = int(center_y - layer_h / 2)

    text_x = pad - bbox[0]
    text_y = pad - bbox[1]

    # Тінь
    shadow = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.text(
        (text_x + 4, text_y + 5),
        text,
        font=font,
        fill=TEXT_SHADOW_COLOR,
        stroke_width=3,
        stroke_fill=TEXT_SHADOW_COLOR,
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(3))
    base.alpha_composite(shadow, (x, y))

    # М’яке золотисте світіння
    glow = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.text(
        (text_x, text_y),
        text,
        font=font,
        fill=TEXT_GLOW_COLOR,
        stroke_width=4,
        stroke_fill=TEXT_GLOW_COLOR,
    )
    glow = glow.filter(ImageFilter.GaussianBlur(2))
    base.alpha_composite(glow, (x, y))

    # Маска тексту
    mask = Image.new("L", (layer_w, layer_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text(
        (text_x, text_y),
        text,
        font=font,
        fill=255,
        stroke_width=0,
    )

    # Обводка як у рамки
    stroke_layer = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    stroke_draw = ImageDraw.Draw(stroke_layer)
    stroke_draw.text(
        (text_x, text_y),
        text,
        font=font,
        fill=(0, 0, 0, 0),
        stroke_width=3,
        stroke_fill=TEXT_STROKE_COLOR,
    )
    base.alpha_composite(stroke_layer, (x, y))

    # Градієнт усередині цифр
    gradient = make_vertical_gradient(
        (layer_w, layer_h),
        TEXT_TOP_COLOR,
        TEXT_BOTTOM_COLOR
    )

    number_layer = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    number_layer.paste(gradient, (0, 0), mask)

    # Легкий верхній блік
    highlight = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    highlight_draw = ImageDraw.Draw(highlight)
    highlight_draw.text(
        (text_x - 1, text_y - 2),
        text,
        font=font,
        fill=(255, 235, 170, 90),
        stroke_width=0,
    )
    number_layer.alpha_composite(highlight)

    base.alpha_composite(number_layer, (x, y))


async def make_boost_banner(member: discord.Member, old_level: int, new_level: int) -> discord.File:
    if not BANNER_TEMPLATE.exists():
        raise FileNotFoundError(f"Не знайдено шаблон: {BANNER_TEMPLATE}")

    base = Image.open(BANNER_TEMPLATE).convert("RGBA")

    avatar_url = member.display_avatar.replace(size=256, static_format="png").url
    avatar_data = await download_bytes(avatar_url)
    avatar = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
    avatar = circle_crop(avatar, AVATAR_SIZE)

    base.alpha_composite(avatar, (AVATAR_X, AVATAR_Y))

    font = get_font(LEVEL_FONT_SIZE)

    draw_luxury_number(base, str(old_level), LEVEL_FROM_X, LEVEL_FROM_Y, font)
    draw_luxury_number(base, str(new_level), LEVEL_TO_X, LEVEL_TO_Y, font)

    buf = io.BytesIO()
    base.save(buf, format="PNG")
    buf.seek(0)

    return discord.File(buf, filename="silent_cove_boost.png")


# ===================== COG =====================

class BoostBannerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        seen = load_state(
            STATE_COLLECTION,
            {},
            legacy_path="data/boost_seen.json",
        )
        self.seen = seen if isinstance(seen, dict) else {}
        print("[BOOST_BANNER] Cog loaded", flush=True)

    def save_seen(self):
        save_state(STATE_COLLECTION, self.seen)

    def is_duplicate(self, member_id: int, boost_count: int, level: int) -> bool:
        key = str(member_id)
        sig = f"{boost_count}:{level}"
        return self.seen.get(key) == sig

    def mark_seen(self, member_id: int, boost_count: int, level: int) -> None:
        key = str(member_id)
        sig = f"{boost_count}:{level}"
        self.seen[key] = sig
        self.save_seen()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        try:
            if before.guild.id != after.guild.id:
                return

            if before.premium_since is not None:
                return

            if after.premium_since is None:
                return

            guild = after.guild
            channel = guild.get_channel(BOOST_CHANNEL_ID)

            if channel is None:
                channel = await self.bot.fetch_channel(BOOST_CHANNEL_ID)

            boost_count = guild.premium_subscription_count or 0
            new_level = guild.premium_tier or 0
            old_level = max(new_level - 1, 0)

            if self.is_duplicate(after.id, boost_count, new_level):
                print(
                    f"[BOOST_BANNER] duplicate skipped member={after.id} boosts={boost_count} level={new_level}",
                    flush=True,
                )
                return

            banner = await make_boost_banner(after, old_level, new_level)

            await channel.send(
                content=f"{after.mention} дякуємо за підтримку **Silent Cove**!",
                file=banner,
            )
            self.mark_seen(after.id, boost_count, new_level)

            print(
                f"[BOOST_BANNER] sent member={after.id} boosts={boost_count} level={new_level}",
                flush=True,
            )

        except Exception as e:
            log_error("on_member_update", e)

    @commands.command(name="test_boost_banner")
    @commands.has_permissions(administrator=True)
    async def test_boost_banner(
        self,
        ctx: commands.Context,
        old_level: int = 15,
        new_level: int = 16
    ):
        try:
            banner = await make_boost_banner(ctx.author, old_level, new_level)

            await ctx.send(
                content=f"{ctx.author.mention} дякуємо за підтримку **Silent Cove**!",
                file=banner,
            )

        except Exception as e:
            log_error("test_boost_banner", e)
            await ctx.send("❌ Помилка генерації банера. Деталі записані в MongoDB.")

    @commands.command(name="boost_debug")
    @commands.has_permissions(administrator=True)
    async def boost_debug(self, ctx: commands.Context):
        guild = ctx.guild

        await ctx.send(
            f"Boosts: `{guild.premium_subscription_count}`\n"
            f"Level: `{guild.premium_tier}`\n"
            f"Seen records: `{len(self.seen)}`\n"
            f"Template exists: `{BANNER_TEMPLATE.exists()}`\n"
            f"Font exists: `{LEVEL_FONT_PATH.exists()}`"
        )

    @commands.command(name="boost_seen_clear")
    @commands.has_permissions(administrator=True)
    async def boost_seen_clear(self, ctx: commands.Context):
        self.seen = {}
        self.save_seen()
        await ctx.send("✅ boost_seen очищено.")


async def setup(bot: commands.Bot):
    await bot.add_cog(BoostBannerCog(bot))
