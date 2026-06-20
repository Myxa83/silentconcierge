# -*- coding: utf-8 -*-
# cogs/bdf_news_cog.py

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import aiohttp
import discord
import feedparser
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from discord.ext import commands, tasks
from PIL import Image


CHANNEL_ID = 1324474229437108264

BDF_FEED_URL = "https://www.blackdesertfoundry.com/category/all-news/feed/"
STATE_FILE = Path("data/bdf_news_seen.json")


class BDFNewsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.seen_links = self.load_seen()
        self.check_bdf_news.start()

    def cog_unload(self):
        self.check_bdf_news.cancel()

    def load_seen(self) -> set[str]:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        if not STATE_FILE.exists():
            return set()

        try:
            return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            return set()

    def save_seen(self) -> None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(sorted(self.seen_links), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def fetch_bytes(self, url: str) -> bytes:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=40) as resp:
                resp.raise_for_status()
                return await resp.read()

    async def fetch_text(self, url: str) -> str:
        data = await self.fetch_bytes(url)
        return data.decode("utf-8", errors="ignore")

    def clean_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")

        for tag in soup(["script", "style", "nav", "footer", "aside", "form"]):
            tag.decompose()

        text = soup.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    def translate_uk(self, text: str) -> str:
        if not text:
            return ""

        try:
            return GoogleTranslator(source="auto", target="uk").translate(text)
        except Exception:
            return text

    def make_bullets(self, text: str) -> str:
        lines = []

        cleaned = re.sub(r"\s+", " ", text).strip()
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)

        for sentence in sentences:
            sentence = sentence.strip()

            if len(sentence) < 45:
                continue

            if any(bad in sentence.lower() for bad in [
                "cookie",
                "privacy",
                "advertisement",
                "subscribe",
                "newsletter",
                "black desert foundry",
            ]):
                continue

            uk_sentence = self.translate_uk(sentence)

            lines.append(f"• {uk_sentence}")

            if len(lines) >= 5:
                break

        if not lines:
            return "• Нова публікація на Black Desert Foundry.\n• Відкрий посилання, щоб прочитати повний текст."

        return "\n".join(lines)

    def extract_image_url(self, entry, article_html: str) -> str | None:
        if hasattr(entry, "media_content") and entry.media_content:
            url = entry.media_content[0].get("url")
            if url:
                return url

        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            url = entry.media_thumbnail[0].get("url")
            if url:
                return url

        soup = BeautifulSoup(article_html, "lxml")

        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]

        twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            return twitter_image["content"]

        img = soup.find("img")
        if img and img.get("src"):
            return img["src"]

        return None

    async def image_to_png_file(self, image_url: str) -> discord.File | None:
        try:
            data = await self.fetch_bytes(image_url)
            img = Image.open(BytesIO(data)).convert("RGBA")

            png_buffer = BytesIO()
            img.save(png_buffer, format="PNG")
            png_buffer.seek(0)

            return discord.File(
                fp=png_buffer,
                filename="bdf_news.png",
            )
        except Exception as e:
            print(f"[BDFNewsCog] image convert error: {e}")
            return None

    async def send_post(self, entry) -> None:
        link = entry.link

        if link in self.seen_links:
            return

        article_html = await self.fetch_text(link)
        article_text = self.clean_html(article_html)

        original_title = entry.title
        uk_title = self.translate_uk(original_title)

        summary = self.make_bullets(article_text[:5000])

        image_url = self.extract_image_url(entry, article_html)

        channel = self.bot.get_channel(CHANNEL_ID)
        if channel is None:
            channel = await self.bot.fetch_channel(CHANNEL_ID)

        published = getattr(entry, "published", "Дата не вказана")

        embed = discord.Embed(
            title=uk_title[:256],
            url=link,
            description=summary[:3500],
            color=discord.Color.teal(),
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name="Оригінальна назва",
            value=original_title[:1024],
            inline=False,
        )

        embed.add_field(
            name="Дата",
            value=published,
            inline=False,
        )

        embed.set_footer(text="Black Desert Foundry")

        file = None

        if image_url:
            if ".webp" in image_url.lower():
                file = await self.image_to_png_file(image_url)
                if file:
                    embed.set_image(url="attachment://bdf_news.png")
                else:
                    embed.set_image(url=image_url)
            else:
                embed.set_image(url=image_url)

        if file:
            await channel.send(embed=embed, file=file)
        else:
            await channel.send(embed=embed)

        self.seen_links.add(link)
        self.save_seen()

    @tasks.loop(minutes=30)
    async def check_bdf_news(self):
        try:
            feed_text = await self.fetch_text(BDF_FEED_URL)
            feed = feedparser.parse(feed_text)

            entries = list(feed.entries[:5])

            for entry in reversed(entries):
                await self.send_post(entry)
                await asyncio.sleep(2)

        except Exception as e:
            print(f"[BDFNewsCog] check error: {e}")

    @check_bdf_news.before_loop
    async def before_check_bdf_news(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(BDFNewsCog(bot))
