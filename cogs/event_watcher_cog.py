# -*- coding: utf-8 -*-
import aiohttp
import asyncio
import aiofiles
import json
from datetime import datetime
from pathlib import Path
import discord
from discord.ext import commands, tasks
import random
import re

# --------- Основний API та резервні параметри ----------
API_URL = "https://api.playblackdesert.com/WebsiteData/News/GetList"
DETAIL_BASE = "https://www.naeu.playblackdesert.com"
TARGET_CHANNEL_ID = 1324089638880542811
DATA_FILE = Path("data/seen_events.json")
PHRASES_PATH = Path("config/concierge_phrases.json")

# Якщо доведеться використовувати проксі (наприклад, через VPN)
PROXY = None  # приклад: "http://127.0.0.1:7890"

DO_NOT_TRANSLATE = [
    "Vell", "Kzarka", "Kutum", "Nouver", "Karanda", "Garmoth", "Offin", "Quint", "Muraka",
    "Gyfin", "Valencia", "Calpheon", "Mediah", "Drieghan", "O'dyllita", "Kamasylvia", "Grána",
    "Cron Stone", "Black Spirit", "Shai", "Corsair", "Berserker", "Musa", "Maehwa", "Guardian",
    "Nova", "Witch", "Wizard", "Hashashin", "Dark Knight", "Sage", "Woosa", "Maegu"
]


class EventWatcherCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.phrases = {}
        self.check_events.start()
        self.bot.loop.create_task(self.load_phrases_on_start())
        self.bot.loop.create_task(self.initial_fetch())
        print("[SilentConcierge] ⚙️ EventWatcherCog ініціалізовано (stable API mode)")

    def cog_unload(self):
        self.check_events.cancel()

    # ------------------- CONFIG / PHRASES -------------------
    async def load_phrases_on_start(self):
        try:
            async with aiofiles.open(PHRASES_PATH, mode="r", encoding="utf-8") as f:
                data = await f.read()
            self.phrases = json.loads(data)
            print("[SilentConcierge] 🗂️ Фрази завантажено успішно.")
        except Exception as e:
            print(f"[SilentConcierge] ⚠️ Помилка завантаження фраз: {e}")
            self.phrases = {
                "intro": ["Виявлено новий івент у базі Silent Cove."],
                "after_post": ["Івент додано до архіву. Система залишається активною."],
                "notice": ["🎁 Івент доступний для всіх учасників! Не пропусти."]
            }

    def random_phrase(self, category: str) -> str:
        return random.choice(self.phrases.get(category, ["..."]))

    # ------------------- DATA CACHE -------------------
    def load_seen(self):
        if DATA_FILE.exists():
            try:
                return set(json.loads(DATA_FILE.read_text(encoding="utf-8")))
            except Exception:
                return set()
        return set()

    def save_seen(self, seen):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(list(seen), ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------- TRANSLATION -------------------
    def protect_terms(self, text: str):
        protected = {}
        for i, term in enumerate(DO_NOT_TRANSLATE):
            pattern = re.escape(term)
            if re.search(pattern, text, flags=re.IGNORECASE):
                key = f"@@TERM{i}@@"
                protected[key] = term
                text = re.sub(pattern, key, text, flags=re.IGNORECASE)
        return text, protected

    def restore_terms(self, text: str, protected: dict):
        for key, term in protected.items():
            text = text.replace(key, term)
        return text

    async def translate_text(self, text: str):
        text, protected = self.protect_terms(text)
        translated = text
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.post(
                    "https://libretranslate.com/translate",
                    json={"q": text, "source": "en", "target": "uk", "format": "text"}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        translated = data.get("translatedText", text)
        except Exception:
            pass
        return self.restore_terms(translated, protected)

    # ------------------- API FETCH -------------------
    async def get_api_events(self):
        """Отримати список івентів з офіційного API BDO."""
        payload = {"boardType": 3, "regionType": 1, "langType": 3, "page": 1}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.post(API_URL, json=payload, proxy=PROXY) as resp:
                    if resp.status != 200:
                        print(f"[SilentConcierge] ⚠️ API повернув HTTP {resp.status}")
                        return []
                    data = await resp.json()
                    events = data.get("Data", {}).get("List", [])
                    if events:
                        print(f"[SilentConcierge] ✅ Отримано {len(events)} івентів з API.")
                    else:
                        print("[SilentConcierge] ⚠️ API повернуло порожній список.")
                    return events
        except aiohttp.ClientConnectorError as e:
            print(f"[SilentConcierge] ❌ API недоступне ({e}).")
        except Exception as e:
            print(f"[SilentConcierge] ⚠️ Помилка при запиті API: {e}")
        return []

    # ------------------- MAIN LOOP -------------------
    @tasks.loop(minutes=30)
    async def check_events(self):
        print(f"[DEBUG] Перевірка розкладу на {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        await self.fetch_latest_events()

    async def fetch_latest_events(self, initial=False):
        events = await self.get_api_events()
        if not events:
            print("[SilentConcierge] ❌ Не вдалося отримати івенти (API недоступне).")
            return

        seen = self.load_seen()
        new_posts = []

        for e in events[:5]:
            url = DETAIL_BASE + e.get("DetailUrl", "")
            title = e.get("Title", "Без назви")
            date = e.get("RegDate", "")[:10]
            thumb = e.get("ThumbnailUrl", "")

            if initial or url not in seen:
                seen.add(url)
                new_posts.append((title, url, date, thumb))

        if not new_posts:
            print("[SilentConcierge] ℹ️ Нових івентів немає (усі у seen).")
            return

        channel = self.bot.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            print("[SilentConcierge] ⚠️ Канал не знайдено.")
            return

        await channel.send(f"<:SilentCove:1425637670197133444> **{self.random_phrase('intro')}**")

        for title, url, date, thumb in reversed(new_posts):
            translated_title = await self.translate_text(title)
            embed = discord.Embed(
                title=f"<:SilentCove:1425637670197133444> {translated_title}",
                description=f"🗓 **Дата публікації:** {date}\n\n🔗 [Деталі на сайті]({url})",
                color=0x05B2B4
            )
            if thumb:
                embed.set_image(url=thumb)
            embed.set_author(name="Silent Concierge | Система сповіщення Silent Cove")
            if self.bot.user:
                embed.set_footer(text="Silent Concierge", icon_url=self.bot.user.display_avatar.url)
            await channel.send(embed=embed)
            await asyncio.sleep(2)

        await channel.send(f"<:SilentCove:1425637670197133444> *{self.random_phrase('after_post')}*")
        self.save_seen(seen)
        print("[SilentConcierge] ✅ Івенти опубліковано або оновлено.")

    @check_events.before_loop
    async def before_check_events(self):
        await self.bot.wait_until_ready()

    async def initial_fetch(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(5)
        print("[SilentConcierge] ▶ Початкове завантаження останніх 5 івентів...")
        await self.fetch_latest_events(initial=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(EventWatcherCog(bot))
    print("✅ Silent Concierge | Автоматичний моніторинг івентів (stable API mode) активовано.")