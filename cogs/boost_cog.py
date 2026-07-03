# -*- coding: utf-8 -*-
# cogs/boost_cog.py

import aiohttp
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageSequence
from io import BytesIO


TEST_CHANNEL_ID = 1370522199873814528
BOOST_CHANNEL_ID = 1331734685683945523

BACKGROUND_URL = "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/backgrounds/Boost.png"


class BoostCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bg_cache = None

    async def fetch_bytes(self, url: str) -> bytes:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.read()

    async def get_background(self) -> Image.Image:
        if self.bg_cache is None:
            data = await self.fetch_bytes(BACKGROUND_URL)
            self.bg_cache = Image.open(BytesIO(data)).convert("RGBA")
        return self.bg_cache.copy()

    async def get_avatar_frames(self, member: discord.Member, size: int = 230):
        avatar_asset = member.display_avatar.replace(size=256)

        avatar_bytes = await avatar_asset.read()
        avatar_img = Image.open(BytesIO(avatar_bytes))

        frames = []
        durations = []

        if getattr(avatar_img, "is_animated", False):
            for frame in ImageSequence.Iterator(avatar_img):
                frame = frame.convert("RGBA").resize((size, size), Image.LANCZOS)
                frames.append(frame)
                durations.append(frame.info.get("duration", 80))
        else:
            frame = avatar_img.convert("RGBA").resize((size, size), Image.LANCZOS)
            frames.append(frame)
            durations.append(100)

        return frames, durations

    def circle_crop(self, img: Image.Image) -> Image.Image:
        size = img.size[0]
        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size, size), fill=255)

        result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        result.paste(img, (0, 0), mask)
        return result

    def draw_glow_ring(self, base: Image.Image, x: int, y: int, size: int):
        draw = ImageDraw.Draw(base)

        # золоте світіння навколо аватарки
        for i in range(18, 0, -3):
            alpha = max(10, 70 - i * 3)
            draw.ellipse(
                (x - i, y - i, x + size + i, y + size + i),
                outline=(255, 190, 55, alpha),
                width=5,
            )

        # золота рамка
        draw.ellipse(
            (x - 8, y - 8, x + size + 8, y + size + 8),
            outline=(255, 207, 91, 255),
            width=8,
        )

        draw.ellipse(
            (x - 17, y - 17, x + size + 17, y + size + 17),
            outline=(122, 82, 24, 255),
            width=4,
        )

    def draw_level_numbers(self, base: Image.Image, old_level: int, new_level: int):
        draw = ImageDraw.Draw(base)

        try:
            font = ImageFont.truetype("arial.ttf", 92)
        except Exception:
            font = ImageFont.load_default()

        # координати під шестикутники на твоєму фоні
        left_pos = (604, 555)
        right_pos = (955, 555)

        def centered_text(text: str, center):
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]

            x = center[0] - w // 2
            y = center[1] - h // 2 - 6

            # тінь
            draw.text((x + 3, y + 4), text, font=font, fill=(0, 0, 0, 180))

            # ліва сіра, права золота
            fill = (200, 200, 200, 255) if center == left_pos else (255, 207, 91, 255)

            draw.text((x, y), text, font=font, fill=fill)

        centered_text(str(old_level), left_pos)
        centered_text(str(new_level), right_pos)

    async def make_boost_image(
        self,
        member: discord.Member,
        old_level: int,
        new_level: int,
    ) -> discord.File:
        bg = await self.get_background()

        avatar_size = 230
        avatar_x = bg.width - 315
        avatar_y = 245

        avatar_frames, durations = await self.get_avatar_frames(member, avatar_size)

        final_frames = []

        for avatar in avatar_frames:
            frame = bg.copy()

            self.draw_level_numbers(frame, old_level, new_level)

            avatar = self.circle_crop(avatar)

            self.draw_glow_ring(frame, avatar_x, avatar_y, avatar_size)
            frame.paste(avatar, (avatar_x, avatar_y), avatar)

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
            )
            filename = "silent_cove_boost.gif"
        else:
            final_frames[0].save(output, format="PNG")
            filename = "silent_cove_boost.png"

        output.seek(0)
        return discord.File(output, filename=filename)

    async def send_boost_notice(
        self,
        channel: discord.TextChannel,
        member: discord.Member,
        old_level: int,
        new_level: int,
    ):
        file = await self.make_boost_image(member, old_level, new_level)

        await channel.send(
            content=f"{member.mention} дякуємо за підтримку **Silent Cove**!",
            file=file,
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.premium_since is None and after.premium_since is not None:
            guild = after.guild

            old_level = before.guild.premium_tier
            new_level = guild.premium_tier

            if new_level < old_level:
                new_level = old_level

            channel = self.bot.get_channel(BOOST_CHANNEL_ID)
            if channel is None:
                return

            await self.send_boost_notice(
                channel=channel,
                member=after,
                old_level=old_level,
                new_level=new_level,
            )

    @commands.command(name="testboost")
    @commands.has_permissions(administrator=True)
    async def test_boost(self, ctx: commands.Context):
        if ctx.channel.id != TEST_CHANNEL_ID:
            return await ctx.reply("Тест бусту можна запускати тільки в тестовому каналі.")

        await self.send_boost_notice(
            channel=ctx.channel,
            member=ctx.author,
            old_level=1,
            new_level=2,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(BoostCog(bot))
