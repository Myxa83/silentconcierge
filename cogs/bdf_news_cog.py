# -*- coding: utf-8 -*-
# cogs/bdf_news_cog.py

import asyncio
import json
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import discord
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from discord.ext import commands, tasks
from PIL import Image


CHANNEL_ID = 1324474229437108264
BDF_NEWS_URL = "https://www.blackdesertfoundry.com/category/all-news/"
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
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=45) as resp:
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
        except Exception as e:
            print(f"[BDFNewsCog] translate error: {e}")
            return text

    def make_bullets(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)

        lines = []

        blocked_words = [
            "cookie",
            "privacy",
            "advertisement",
            "subscribe",
            "newsletter",
            "black desert foundry",
            "comments",
            "leave a reply",
        ]

        for sentence in sentences:
            sentence = sentence.strip()

            if len(sentence) < 45:
                continue

            if any(word in sentence.lower() for word in blocked_words):
                continue

            uk_sentence = self.translate_uk(sentence)
            lines.append(f"• {uk_sentence}")

            if len(lines) >= 5:
                break

        if not lines:
            return (
                "• Нова публікація на Black Desert Foundry.\n"
                "• Відкрий посилання, щоб прочитати повний текст."
            )

        return "\n".join(lines)

    def extract_article_image(self, article_html: str) -> str | None:
        soup = BeautifulSoup(article_html, "lxml")

        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]

        twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            return twitter_image["content"]

        article = soup.find("article") or soup

        img = article.find("img")
        if img:
            for attr in ("data-src", "data-lazy-src", "src"):
                if img.get(attr):
                    return img[attr]

        return None

    def extract_date_from_article(self, article_html: str) -> str:
        soup = BeautifulSoup(article_html, "lxml")

        time_tag = soup.find("time")
        if time_tag:
            if time_tag.get("datetime"):
                return time_tag["datetime"]
            return time_tag.get_text(" ", strip=True)

        meta_date = soup.find("meta", property="article:published_time")
        if meta_date and meta_date.get("content"):
            return meta_date["content"]

        return "Дата не вказана"

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

    async def fetch_posts_from_page(self) -> list[SimpleNamespace]:
        html = await self.fetch_text(BDF_NEWS_URL)
        soup = BeautifulSoup(html, "lxml")

        posts = []
        seen = set()

        selectors = [
            "article",
            ".post",
            ".type-post",
            ".entry",
        ]

        article_nodes = []
        for selector in selectors:
            article_nodes = soup.select(selector)
            if article_nodes:
                break

        if not article_nodes:
            article_nodes = soup.find_all(["article", "div"])

        for node in article_nodes:
            title_tag = node.find(["h1", "h2", "h3"])
            link_tag = None

            if title_tag:
                link_tag = title_tag.find("a", href=True)

            if not link_tag:
                link_tag = node.find("a", href=True)

            if not title_tag or not link_tag:
                continue

            title = title_tag.get_text(" ", strip=True)
            link = link_tag["href"].strip()

            if not title or not link:
                continue

            if not link.startswith("http"):
                continue

            if "blackdesertfoundry.com" not in link:
                continue

            if link in seen:
                continue

            seen.add(link)

            posts.append(
                SimpleNamespace(
                    title=title,
                    link=link,
                    published="Дата не вказана",
                )
            )

            if len(posts) >= 5:
                break

        return posts

    async def send_post(self, entry: SimpleNamespace) -> None:
        link = entry.link

        if link in self.seen_links:
            return

        article_html = await self.fetch_text(link)
        article_text = self.clean_html(article_html)

        original_title = entry.title
        uk_title = self.translate_uk(original_title)

        summary = self.make_bullets(article_text[:6000])
        image_url = self.extract_article_image(article_html)
        published = self.extract_date_from_article(article_html)

        channel = self.bot.get_channel(CHANNEL_ID)
        if channel is None:
            channel = await self.bot.fetch_channel(CHANNEL_ID)

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
            value=published[:1024],
            inline=False,
        )

        embed.set_footer(text="Silent Concierge by Myxa | Black Desert Foundry")

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
            posts = await self.fetch_posts_from_page()

            if not posts:
                print("[BDFNewsCog] no posts found")
                return

            for entry in reversed(posts):
                await self.send_post(entry)
                await asyncio.sleep(2)

        except Exception as e:
            print(f"[BDFNewsCog] check error: {e}")

    @check_bdf_news.before_loop
    async def before_check_bdf_news(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(BDFNewsCog(bot))
    print("[BDF_NEWS] ✅ BDFNewsCog loaded")
