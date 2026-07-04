# -*- coding: utf-8 -*-
# cogs/boost_cog.py

import json
from io import BytesIO
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageSequence, ImageOps


TEST_CHANNEL_ID = 1370522199873814528
BOOST_CHANNEL_ID = 1331734685683945523

BACKGROUND_URL = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/Boost.png"

STATE_FILE = Path("data/boost_state.json")

NUMBER_FONT_PATH = Path("assets/fonts/Cinzel-VariableFont_wght.ttf")

ORIGINAL_BG_W = 666
ORIGINAL_BG_H = 375

BANNER_CROP_BOX = (13, 79, 653, 289)

CLEAN_W = 640
CLEAN_H = 210

OLD_LEVEL_CENTER = (260, 122)
NEW_LEVEL_CENTER = (399, 122)

LEVEL_FONT_SIZE = 38

AVATAR_SIZE = 120
AVATAR_CENTER = (541, 104)

AVATAR_X = AVATAR_CENTER[0] - AVATAR_SIZE // 2
AVATAR_Y = AVATAR_CENTER[1] - AVATAR_SIZE // 2


class BoostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bg_cache = None
        self.state = self.load_state()

    def load_state(self) -> dict:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        if not STATE_FILE.exists():
            return {}

        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_state(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_saved_tier(self, guild_id: int):
        guild_data = self.state.get(str(guild_id), {})
        tier = guild_data.get("premium_tier")
        return tier if isinstance(tier, int) else None

    def set_saved_guild_state(self, guild: discord.Guild):
        self.state[str(guild.id)] = {
            "premium_tier": guild.premium_tier or 0,
            "premium_subscription_count": guild.premium_subscription_count or 0,
        }
        self.save_state()

    async def fetch_bytes(self, url: str) -> bytes:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.read()

    async def get_background(self) -> Image.Image:
        if self.bg_cache is None:
            data = await self.fetch_bytes(BACKGROUND_URL)
            img = Image.open(BytesIO(data)).convert("RGBA")

            if img.size == (ORIGINAL_BG_W, ORIGINAL_BG_H):
                img = img.crop(BANNER_CROP_BOX)

            elif img.size != (CLEAN_W, CLEAN_H):
                img = ImageOps.fit(
                    img,
                    (CLEAN_W, CLEAN_H),
                    method=Image.LANCZOS,
                    centering=(0.5, 0.5),
                )

            self.bg_cache = img

        return self.bg_cache.copy()

    async def get_avatar_frames(self, member: discord.Member):
        avatar_asset = member.display_avatar

        try:
            if avatar_asset.is_animated():
                avatar_asset = avatar_asset.replace(format="gif", size=256)
            else:
                avatar_asset = avatar_asset.replace(static_format="png", size=256)
        except Exception:
            avatar_asset = member.display_avatar.replace(size=256)

        avatar_bytes = await avatar_asset.read()
        avatar_img = Image.open(BytesIO(avatar_bytes))

        frames = []
        durations = []

        if getattr(avatar_img, "is_animated", False):
            for frame in ImageSequence.Iterator(avatar_img):
                frames.append(frame.convert("RGBA"))
                durations.append(frame.info.get("duration", 80))
        else:
            frames.append(avatar_img.convert("RGBA"))
            durations.append(100)

        return frames, durations

    def circle_crop_avatar(self, img: Image.Image, size: int) -> Image.Image:
        img = img.convert("RGBA")

        img = ImageOps.fit(
            img,
            (size, size),
            method=Image.LANCZOS,
            centering=(0.5, 0.5),
        )

        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size, size), fill=255)

        result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        result.paste(img, (0, 0), mask)

        return result

    def get_number_font(self, size: int):
        font_paths = [
            str(NUMBER_FONT_PATH),
            "assets/fonts/Cinzel-VariableFont_wght.ttf",
            "assets/fonts/FixelDisplay-Bold.otf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/georgia.ttf",
            "C:/Windows/Fonts/times.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]

        for path in font_paths:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue

        return ImageFont.load_default()

    def draw_centered_number(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        center: tuple[int, int],
        font,
        fill: tuple[int, int, int, int],
        stroke: tuple[int, int, int, int],
        glow: bool = False,
    ):
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=1)

        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        x = center[0] - text_w // 2
        y = center[1] - text_h // 2 - 1

        draw.text(
            (x + 2, y + 2),
            text,
            font=font,
            fill=(0, 0, 0, 130),
        )

        if glow:
            draw.text(
                (x, y),
                text,
                font=font,
                fill=(255, 175, 40, 28),
                stroke_width=2,
                stroke_fill=(255, 150, 35, 28),
            )

        draw.text(
            (x, y),
            text,
            font=font,
            fill=fill,
            stroke_width=1,
            stroke_fill=stroke,
        )

        draw.text(
            (x - 1, y - 1),
            text,
            font=font,
            fill=(255, 245, 200, 45),
        )

    def draw_level_numbers(
        self,
        base: Image.Image,
        old_level: int,
        new_level: int,
    ):
        draw = ImageDraw.Draw(base)
        font = self.get_number_font(LEVEL_FONT_SIZE)

        self.draw_centered_number(
            draw=draw,
            text=str(old_level),
            center=OLD_LEVEL_CENTER,
            font=font,
            fill=(178, 178, 172, 255),
            stroke=(35, 35, 38, 200),
            glow=False,
        )

        self.draw_centered_number(
            draw=draw,
            text=str(new_level),
            center=NEW_LEVEL_CENTER,
            font=font,
            fill=(230, 178, 68, 255),
            stroke=(68, 42, 20, 200),
            glow=True,
        )

    async def make_boost_image(
        self,
        member: discord.Member,
        old_level: int,
        new_level: int,
    ) -> discord.File:
        bg = await self.get_background()
        avatar_frames, durations = await self.get_avatar_frames(member)

        final_frames = []

        for avatar in avatar_frames:
            frame = bg.copy()

            self.draw_level_numbers(
                base=frame,
                old_level=old_level,
                new_level=new_level,
            )

            avatar = self.circle_crop_avatar(
                img=avatar,
                size=AVATAR_SIZE,
            )

            frame.paste(
                avatar,
                (AVATAR_X, AVATAR_Y),
                avatar,
            )

            final_frames.append(frame)

        output = BytesIO()

        if len(final_frames) > 1:
            final_frames[0].save(
                output,
                format="GIF",
                save_all=True,
                append_images=final_frames[1:],
                duration=durations,
                loop=0,
                disposal=2,
                optimize=False,
            )
            filename = "silent_cove_boost.gif"
        else:
            final_frames[0].save(output, format="PNG")
            filename = "silent_cove_boost.png"

        output.seek(0)
        return discord.File(output, filename=filename)

    async def send_boost_notice(
        self,
        channel: discord.abc.Messageable,
        member: discord.Member,
        old_level: int,
        new_level: int,
    ):
        file = await self.make_boost_image(
            member=member,
            old_level=old_level,
            new_level=new_level,
        )

        await channel.send(
            content=f"{member.mention} дякуємо за підтримку **Silent Cove**!",
            file=file,
        )

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member,
    ):
        if before.premium_since is not None:
            return

        if after.premium_since is None:
            return

        guild = after.guild
        current_tier = guild.premium_tier or 0

        saved_tier = self.get_saved_tier(guild.id)

        if saved_tier is None:
            old_level = current_tier
            new_level = current_tier
        else:
            old_level = saved_tier
            new_level = current_tier

        if new_level < old_level:
            old_level = new_level

        channel = self.bot.get_channel(BOOST_CHANNEL_ID)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(BOOST_CHANNEL_ID)
            except Exception:
                return

        await self.send_boost_notice(
            channel=channel,
            member=after,
            old_level=old_level,
            new_level=new_level,
        )

        self.set_saved_guild_state(guild)

    @commands.Cog.listener()
    async def on_guild_update(
        self,
        before: discord.Guild,
        after: discord.Guild,
    ):
        before_tier = before.premium_tier or 0
        after_tier = after.premium_tier or 0

        before_boosts = before.premium_subscription_count or 0
        after_boosts = after.premium_subscription_count or 0

        if before_tier != after_tier or before_boosts != after_boosts:
            self.set_saved_guild_state(after)

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            if self.get_saved_tier(guild.id) is None:
                self.set_saved_guild_state(guild)

    @commands.command(
        name="testboost",
        help="Тестове повідомлення про буст сервера Silent Cove.",
        brief="Тест буст-банера.",
    )
    @commands.has_permissions(administrator=True)
    async def test_boost(
        self,
        ctx: commands.Context,
        old_level: int = 1,
        new_level: int = 2,
    ):
        if ctx.channel.id != TEST_CHANNEL_ID:
            await ctx.reply(
                "Тест бусту можна запускати тільки в тестовому каналі.",
                mention_author=False,
            )
            return

        await self.send_boost_notice(
            channel=ctx.channel,
            member=ctx.author,
            old_level=old_level,
            new_level=new_level,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(BoostCog(bot))
