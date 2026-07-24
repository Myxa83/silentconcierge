# -*- coding: utf-8 -*-
# cogs/bdf_news_cog.py

import asyncio
import re
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace

import aiohttp
import discord
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from discord.ext import commands, tasks
from PIL import Image

from data.mongo_store import load_state, save_state


CHANNEL_ID = 1324474229437108264
BDF_NEWS_URL = "https://www.blackdesertfoundry.com/category/all-news/"
STATE_COLLECTION = "bdf_news_state"

UKRAINIAN_MONTHS = (
    "",
    "січня",
    "лютого",
    "березня",
    "квітня",
    "травня",
    "червня",
    "липня",
    "серпня",
    "вересня",
    "жовтня",
    "листопада",
    "грудня",
)

ASL = "<a:ASL:1447205981133209773>"
RSL = "<a:RSL:1447204908494225529>"
BULLET_POINT = "<a:bulletpoint:1447549436137046099>"
DEFF = "<:def:1445058422234943732>"
DIVIDER = DEFF * 16
QUESTION_MARK = "<:QM:1445058301485121727>"
EXCLAMATION_MARK = "<:EM:1445058338055393341>"
BUBBLES = "<a:bulabubbles:1430618519166259211>"
BOAT = "<a:boat:1469018496426840339>"
NEWS_LOGO_URL = (
    "https://cdn.discordapp.com/emojis/"
    "1482553264825438330.webp?size=96&quality=lossless"
)


class BDFNewsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.seen_links = self.load_seen()
        self.check_bdf_news.start()

    def cog_unload(self):
        self.check_bdf_news.cancel()

    def load_seen(self) -> set[str]:
        links = load_state(
            STATE_COLLECTION,
            [],
            legacy_path="data/bdf_news_seen.json",
        )
        if not isinstance(links, list):
            return set()
        return {
            link
            for link in links
            if isinstance(link, str) and link
        }

    def save_seen(self) -> None:
        save_state(
            STATE_COLLECTION,
            sorted(self.seen_links),
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

        article = (
            soup.select_one(".entry-content")
            or soup.select_one(".post-content")
            or soup.select_one(".td-post-content")
            or soup.find("article")
            or soup
        )

        lines = []
        seen = set()

        for node in article.find_all(["h2", "h3", "h4", "p", "li", "tr"]):
            # Текст усередині пункту списку вже буде взято з самого <li>.
            if node.name == "p" and node.find_parent("li"):
                continue

            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            key = text.casefold()

            if not text or key in seen:
                continue

            seen.add(key)
            lines.append(text)

        if lines:
            return "\n".join(lines)

        text = article.get_text("\n", strip=True)
        return re.sub(r"\n{2,}", "\n", text)

    def translate_uk(self, text: str) -> str:
        if not text:
            return ""

        try:
            return GoogleTranslator(source="auto", target="uk").translate(text)
        except Exception as e:
            print(f"[BDFNewsCog] translate error: {e}")
            return text

    def split_long_summary_item(
        self,
        text: str,
        max_length: int = 320,
    ) -> list[str]:
        """
        Ділить довгі пункти на читабельні частини.
        Окремо враховує переліки предметів із кількостями на кшталт x250.
        """
        text = re.sub(
            r"(x\d+(?:[.,]\d+)?)\s+(?=[A-ZА-ЯІЇЄҐ])",
            r"\1\n",
            text,
        )

        rough_parts = re.split(r"(?<=[.!?;])\s+|\n+", text)
        parts = []

        for rough_part in rough_parts:
            rough_part = re.sub(r"\s+", " ", rough_part).strip(" •-\t")

            if not rough_part:
                continue

            words = rough_part.split()
            current = []
            current_length = 0

            for word in words:
                extra = len(word) + (1 if current else 0)

                if current and current_length + extra > max_length:
                    parts.append(" ".join(current))
                    current = [word]
                    current_length = len(word)
                else:
                    current.append(word)
                    current_length += extra

            if current:
                parts.append(" ".join(current))

        return parts

    def format_summary_item(self, text: str) -> str:
        text = text.strip()
        label_match = re.match(r"^([^:]{2,55}:)\s+(.+)$", text)

        if label_match:
            label, value = label_match.groups()
            return f"{BULLET_POINT} **{label}** {value}"

        return f"{BULLET_POINT} {text}"

    def make_bullets(self, text: str) -> str:
        blocks = [
            re.sub(r"\s+", " ", block).strip()
            for block in re.split(r"\n+", text)
        ]
        lines = []
        used_characters = 0
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

        for block in blocks:
            if len(block) < 35:
                continue

            if any(word in block.lower() for word in blocked_words):
                continue

            uk_block = self.translate_uk(block)

            for part in self.split_long_summary_item(uk_block):
                line = self.format_summary_item(part)

                if used_characters + len(line) > 3000:
                    break

                lines.append(line)
                used_characters += len(line)

                if len(lines) >= 8:
                    break

            if len(lines) >= 8 or used_characters >= 3000:
                break

        if not lines:
            return (
                f"{BULLET_POINT} Нова публікація на Black Desert Foundry.\n\n"
                f"{BULLET_POINT} Відкрий посилання, щоб прочитати повний текст."
            )

        return "\n\n".join(lines)

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

    def format_published_date(self, value: str) -> str:
        value = value.strip()

        if not value or value == "Дата не вказана":
            return "Дата не вказана"

        try:
            published = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value

        month = UKRAINIAN_MONTHS[published.month]
        return (
            f"{published.day} {month} {published.year} "
            f"о {published.hour:02d}:{published.minute:02d}"
        )

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

        summary = self.make_bullets(article_text[:10000])
        image_url = self.extract_article_image(article_html)
        published = self.format_published_date(
            self.extract_date_from_article(article_html)
        )

        channel = self.bot.get_channel(CHANNEL_ID)
        if channel is None:
            channel = await self.bot.fetch_channel(CHANNEL_ID)

        title_limit = 256 - len(ASL) - len(RSL) - 2
        formatted_title = f"{ASL} {uk_title[:title_limit]} {RSL}"

        embed = discord.Embed(
            title=formatted_title,
            url=link,
            description=(
                f"{EXCLAMATION_MARK} **Коротко про оновлення**\n\n"
                f"{summary}\n\n"
                f"{DIVIDER}"
            )[:4000],
            color=discord.Color.teal(),
            timestamp=datetime.now(timezone.utc),
        )

        embed.add_field(
            name=f"{BUBBLES} Оригінальна назва",
            value=original_title[:1024],
            inline=False,
        )

        embed.add_field(
            name=f"{BOAT} Опубліковано",
            value=published[:1024],
            inline=False,
        )

        embed.add_field(
            name=f"{QUESTION_MARK} Де прочитати повністю?",
            value=f"[Відкрити на Black Desert Foundry]({link})",
            inline=False,
        )

        embed.set_author(
            name="Black Desert Foundry",
            icon_url=NEWS_LOGO_URL,
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

            if not self.seen_links:
                for entry in posts:
                    self.seen_links.add(entry.link)

                self.save_seen()

                print(
                    f"[BDFNewsCog] first run: "
                    f"saved {len(posts)} existing posts, no spam"
                )

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
