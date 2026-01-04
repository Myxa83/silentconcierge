import os
import re
import json
import time
import random
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from xml.etree import ElementTree as ET

import aiohttp
import discord
from discord.ext import commands, tasks
from discord import app_commands

# Pillow (опціонально) для обробки зображень: коло-аватар + масштаб іконок
try:
    from PIL import Image, ImageDraw
    from io import BytesIO
    _PIL_OK = True
except Exception:
    _PIL_OK = False

"""
Stream Cog — ПОВНИЙ КОД (оновлена версія)

ДОДАНО:
- Виявлення НОВИХ ВІДЕО (не стріми) на YouTube через RSS і на Twitch через Helix Videos API.
- Окремі анонси для live та для звичайних відео (в описі явно пишемо «Нове відео на каналі @...»).
- Кеш останніх оголошених відео, щоб не дублювати анонси.

ЗБЕРЕЖЕНО:
- Існуюча логіка live-перевірок через decapi.me (Twitch/YouTube uptime).
- Візуальна структура ембедів і тест-команда.
"""

# ==== НАЛАШТУВАННЯ ====
GUILD_ID = int(os.getenv("GUILD_ID", 1323454227816906802))
STREAMERS_FILE = "streamers.json"  # [{platform, username, discord_id, ...}]
GAME_ICONS_FILE = "game_icons.json"  # Мапа "гра → URL іконки"
LAST_SEEN_FILE = "streams_last_seen.json"  # кеш останніх відео/стрімів
STREAM_ANNOUNCE_CHANNEL_NAME = "streams"

# Часове вікно «свіжості» відео (щоб не анонсувати надто старе, якщо кеш втрачено)
NEW_VIDEO_MAX_AGE_HOURS = int(os.getenv("NEW_VIDEO_MAX_AGE_HOURS", "48"))

# Випадкові кольори для ембедів
STREAM_COLORS = [
    0xFF4000,
    0xFFFF00,
    0x00FF00,
    0x00FF80,
    0x00BFFF,
    0x4000FF,
    0x8000FF,
    0xFF0040,
]

# Платформені іконки (fallback картинки)
TWITCH_ICON_IMG = "https://i.imgur.com/5Us8X2r.png"
YOUTUBE_ICON_IMG = "https://i.imgur.com/xD7czCG.png"

# Емодзі/іконки для текстових рядків (замінити на ваші кастом-емодзі за потреби)
TWITCH_EMOJI = "<:twitch_icon:1403350256271364268>"
YOUTUBE_EMOJI = "<:youtube_icon:1403350209630699652>"

# Емодзі гри
GAME_EMOJI = os.getenv("GAME_EMOJI", "")  # наприклад, <:bdo:123456789012345678>

# Twitch Helix (для live-boxart та відео uploads)
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
_TWITCH_TOKEN: Optional[str] = None
_TWITCH_TOKEN_EXP = 0

# Рандомні фрази (для контенту повідомлення)
ANNOUNCE_LINES = [
    "Наш спеціальний агент {mention} працює у [небезпечних умовах]({url})",
    "Агент {mention} уже в ефірі — дивись [тут]({url})",
    "На зв'язку агент {mention}. Приєднуйся [тут]({url})",
    "{mention} виходить на зв'язок зі зони турбулентності — клацай [тут]({url})",
    "{mention} ризикує заради контенту — залітай [тут]({url})",
    "Стрим на місії! Агент {mention} чекає [тут]({url})",
    "Гарячий ефір від агента {mention} — тисни [тут]({url})",
    "{mention} веде пряму трансляцію. Заціни [тут]({url})",
]

# ---- helpers: дати/час ----
_UA_MONTHS_GEN = [
    "", "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
]
try:
    TZ_LONDON = ZoneInfo("Europe/London")
except ZoneInfoNotFoundError:
    TZ_LONDON = timezone.utc


def format_ua_datetime(dt: datetime) -> str:
    """Напр.: 9 серпня 2025 р. 05:16"""
    m = _UA_MONTHS_GEN[dt.month]
    return f"{dt.day} {m} {dt.year} р. {dt.hour:02d}:{dt.minute:02d}"


async def _get_twitch_headers(session: aiohttp.ClientSession) -> Optional[dict]:
    """Отримати/оновити токен Helix і повернути headers, або None."""
    global _TWITCH_TOKEN, _TWITCH_TOKEN_EXP
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        return None
    now = time.time()
    if not _TWITCH_TOKEN or now >= _TWITCH_TOKEN_EXP:
        async with session.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id": TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
        ) as resp:
            data = await resp.json()
            _TWITCH_TOKEN = data.get("access_token")
            _TWITCH_TOKEN_EXP = now + int(data.get("expires_in", 3600)) - 60
    if not _TWITCH_TOKEN:
        return None
    return {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {_TWITCH_TOKEN}"}



def discord_ts(dt: datetime, style: str = "f") -> str:
    """Discord localized timestamp that auto-adjusts to each viewer's timezone.
    style: 'f' = full date & time; use 'R' for relative (e.g., '5 minutes ago').
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ts = int(dt.timestamp())
    return f"<t:{ts}:{style}>"

class StreamCog(commands.Cog):
    # ---------- image helpers ----------
    async def _circle_avatar_file(self, session: aiohttp.ClientSession, avatar_url: str, size: int = 96) -> Optional[discord.File]:
        """Скачує аватар і повертає його як круглий PNG (прозорий фон)."""
        if not _PIL_OK:
            return None
        try:
            async with session.get(avatar_url) as av:
                av_bytes = await av.read()
            avatar = Image.open(BytesIO(av_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, size, size), fill=255)
            avatar.putalpha(mask)
            out = BytesIO()
            avatar.save(out, format="PNG")
            out.seek(0)
            return discord.File(out, filename="avatar_circle.png")
        except Exception:
            return None

    async def _fetch_icon_60(self, session: aiohttp.ClientSession, url: str, size: int = 60) -> Optional[discord.File]:
        if not _PIL_OK:
            return None
        try:
            async with session.get(url) as r:
                b = await r.read()
            img = Image.open(BytesIO(b)).convert("RGBA").resize((size, size), Image.LANCZOS)
            out = BytesIO()
            img.save(out, format="PNG")
            out.seek(0)
            return discord.File(out, filename=f"platform_{size}.png")
        except Exception:
            return None

    # ---------- init & persistence ----------
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # {platform, username, discord_id, yt_channel_id?}
        self.streamers: list[dict] = []
        self.game_icons: dict[str, str] = {}
        self.last_seen: Dict[str, Dict[str, str]] = {"youtube": {}, "twitch": {}}
        self._checked_live: set[tuple[str, str]] = set()
        self.load_streamers()
        self.load_game_icons()
        self.load_last_seen()
        self.check_streams.start()

    def cog_unload(self):
        if self.check_streams.is_running():
            self.check_streams.cancel()

    # ---- files ----
    def load_streamers(self):
        if os.path.exists(STREAMERS_FILE):
            with open(STREAMERS_FILE, "r", encoding="utf-8") as f:
                try:
                    self.streamers = json.load(f)
                except Exception:
                    self.streamers = []
        else:
            self.save_streamers()

    def save_streamers(self):
        with open(STREAMERS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.streamers, f, ensure_ascii=False, indent=2)

    def load_game_icons(self):
        if os.path.exists(GAME_ICONS_FILE):
            with open(GAME_ICONS_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    self.game_icons = {str(k).strip().lower(): str(v).strip() for k, v in data.items() if v}
                except Exception:
                    self.game_icons = {}
        else:
            self.save_game_icons()

    def save_game_icons(self):
        with open(GAME_ICONS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.game_icons, f, ensure_ascii=False, indent=2)

    def load_last_seen(self):
        if os.path.exists(LAST_SEEN_FILE):
            try:
                with open(LAST_SEEN_FILE, "r", encoding="utf-8") as f:
                    self.last_seen = json.load(f)
            except Exception:
                self.last_seen = {"youtube": {}, "twitch": {}}
        else:
            self.save_last_seen()

    def save_last_seen(self):
        with open(LAST_SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(self.last_seen, f, ensure_ascii=False, indent=2)

    def get_game_icon(self, game_name: Optional[str]) -> Optional[str]:
        if not game_name:
            return None
        return self.game_icons.get(game_name.strip().lower())

    # ---- helpers ----
    @staticmethod
    def extract_username(platform: str, value: str) -> Optional[str]:
        value = value.strip()
        if platform == "twitch":
            if value.startswith("http"):
                m = re.search(r"twitch\.tv/([-\w]+)", value)
                return m.group(1) if m else None
            return value
        # youtube: може бути video id, channel id, @handle, /user/
        if value.startswith("http"):
            m = re.search(r"(?:youtube\.com/(?:watch\?v=|live/)|youtu\.be/)([-\w]{6,})", value)
            if m:
                return m.group(1)
            m = re.search(r"youtube\.com/(?:channel/([-\w]+)|user/([-\w]+)|@([-.\w]+))", value)
            if m:
                return next(g for g in m.groups() if g)
        return value or None

    @staticmethod
    def platform_assets(platform: str) -> Tuple[str, str]:
        return (TWITCH_ICON_IMG, TWITCH_EMOJI) if platform == "twitch" else (YOUTUBE_ICON_IMG, YOUTUBE_EMOJI)

    async def _yt_resolve_channel_id(self, session: aiohttp.ClientSession, identifier: str) -> Optional[str]:
        """Повертає channel_id (UC...), приймає @handle / user / channel / video id."""
        try:
            # decapi сам розрулить пошук по @handle, user, url, id
            async with session.get(f"https://decapi.me/youtube/channelid?search={identifier}") as r:
                cid = (await r.text()).strip()
                if cid.startswith("UC") and len(cid) > 10:
                    return cid
        except Exception:
            pass
        return None

    async def _twitch_user_id(self, session: aiohttp.ClientSession, login: str) -> Optional[str]:
        headers = await _get_twitch_headers(session)
        if not headers:
            return None
        async with session.get(f"https://api.twitch.tv/helix/users?login={login}", headers=headers) as r:
            jd = await r.json()
        if isinstance(jd, dict) and jd.get("data"):
            return jd["data"][0].get("id")
        return None

    async def _twitch_latest_upload(self, session: aiohttp.ClientSession, login: str) -> Optional[Dict[str, Any]]:
        """Останнє ЗВИЧАЙНЕ ВІДЕО (type=upload). Повертає {id, title, url, thumbnail_url, created_at}."""
        headers = await _get_twitch_headers(session)
        if not headers:
            return None
        uid = await self._twitch_user_id(session, login)
        if not uid:
            return None
        url = f"https://api.twitch.tv/helix/videos?user_id={uid}&type=upload&first=1"
        async with session.get(url, headers=headers) as r:
            jd = await r.json()
        data = jd.get("data", []) if isinstance(jd, dict) else []
        if not data:
            return None
        v = data[0]
        return {
            "id": v.get("id"),
            "title": v.get("title") or "Відео",
            "url": v.get("url"),
            "thumbnail_url": (v.get("thumbnail_url") or "").replace("%{width}", "640").replace("%{height}", "360"),
            "created_at": v.get("created_at"),
        }

    async def _yt_latest_video_from_rss(self, session: aiohttp.ClientSession, channel_id: str) -> Optional[Dict[str, Any]]:
        """Парсить RSS каналу і повертає {video_id, title, published, link, thumb}."""
        try:
            rss = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            async with session.get(rss) as r:
                text = await r.text()
            root = ET.fromstring(text)
            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'yt': 'http://www.youtube.com/xml/schemas/2015'
            }
            entry = root.find('atom:entry', ns)
            if entry is None:
                return None
            title = (entry.find('atom:title', ns).text or '').strip()
            link_el = entry.find('atom:link', ns)
            link = link_el.get('href') if link_el is not None else ''
            vid_el = entry.find('yt:videoId', ns)
            video_id = vid_el.text if vid_el is not None else None
            pub_el = entry.find('atom:published', ns)
            published = pub_el.text if pub_el is not None else None
            thumb = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg" if video_id else None
            if not video_id:
                return None
            return {"video_id": video_id, "title": title or "Відео", "published": published, "link": link or f"https://youtu.be/{video_id}", "thumb": thumb}
        except Exception:
            return None

    async def _fetch_twitch_game_icon(self, session: aiohttp.ClientSession, username: str) -> Tuple[Optional[str], Optional[str]]:
        """Повертає (game_name, box_art_64_url) або (None, None) для LIVE."""
        headers = await _get_twitch_headers(session)
        if not headers:
            return None, None
        async with session.get(f"https://api.twitch.tv/helix/streams?user_login={username}", headers=headers) as r:
            jd = await r.json()
        items = jd.get("data", []) if isinstance(jd, dict) else []
        if not items:
            return None, None
        game_id = items[0].get("game_id")
        game_name = items[0].get("game_name")
        if not game_id:
            return game_name, None
        async with session.get(f"https://api.twitch.tv/helix/games?id={game_id}", headers=headers) as r2:
            jd2 = await r2.json()
        items2 = jd2.get("data", []) if isinstance(jd2, dict) else []
        if not items2:
            return game_name, None
        box = items2[0].get("box_art_url")
        icon_url = box.replace("{width}", "64").replace("{height}", "64") if box else None
        return game_name, icon_url

    # ---- slash-команди ----
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.describe(платформа="Платформа", посилання="Посилання на канал або стрім", користувач="Нік з Discord")
    @app_commands.choices(платформа=[
        app_commands.Choice(name="twitch", value="twitch"),
        app_commands.Choice(name="youtube", value="youtube"),
    ])
    @app_commands.command(name="додати_стрімера", description="Додати стрімера Twitch/YouTube")
    async def add_streamer(self, interaction: discord.Interaction,
                           платформа: app_commands.Choice[str], посилання: str, користувач: discord.User):
        try:
            plat = платформа.value
            username = self.extract_username(plat, посилання)
            if not username:
                await interaction.response.send_message("❌ Не вдалося визначити ідентифікатор", ephemeral=True)
                return

            extra: Dict[str, Any] = {}
            # Для YouTube спробуємо відразу резолвнути channel_id (для RSS)
            if plat == "youtube":
                async with aiohttp.ClientSession() as session:
                    ch_id = await self._yt_resolve_channel_id(session, username)
                if ch_id:
                    extra["yt_channel_id"] = ch_id

            # перевірка дубля
            for s in self.streamers:
                if s.get("platform") == plat and s.get("username") == username and s.get("discord_id") == користувач.id:
                    await interaction.response.send_message("⚠️ Цей стрімер уже доданий.", ephemeral=True)
                    return
            # додати і зберегти
            item = {"platform": plat, "username": username, "discord_id": користувач.id}
            item.update(extra)
            self.streamers.append(item)
            try:
                self.save_streamers()
            except Exception as se:
                print(f"[STREAM_COG] save_streamers error: {se}")
            await interaction.response.send_message(
                f"✅ Додано: **{username}** ({користувач.mention}) на **{plat}**",
                ephemeral=True,
            )
        except Exception as e:
            print(f"[STREAM_COG] add_streamer error: {e}")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Сталася помилка під час додавання.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Сталася помилка під час додавання.", ephemeral=True)
            except Exception:
                pass

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.describe(
        канал="Канал для тестового ембеду",
        платформа="Платформа",
        тип="Що тестуємо: live чи відео",
        стрімер="Кого тегнути в анонсі",
    )
    @app_commands.choices(платформа=[
        app_commands.Choice(name="twitch", value="twitch"),
        app_commands.Choice(name="youtube", value="youtube"),
    ])
    @app_commands.choices(тип=[
        app_commands.Choice(name="live", value="live"),
        app_commands.Choice(name="відео", value="video"),
    ])
    @app_commands.command(name="тест_стрім", description="Надіслати тестовий ембед (live або video) у вибраний канал")
    async def test_stream(self, interaction: discord.Interaction,
                          канал: discord.TextChannel,
                          платформа: app_commands.Choice[str],
                          тип: app_commands.Choice[str],
                          стрімер: Optional[discord.Member] = None):
        plat = платформа.value
        mode = тип.value  # live | video
        plat_icon_url, plat_emoji = self.platform_assets(plat)
        color = random.choice(STREAM_COLORS)

        # previews
        if plat == "twitch":
            preview = "https://static-cdn.jtvnw.net/ttv-static/404_preview-640x360.jpg"
            test_url = "https://www.twitch.tv/twitch"
        else:
            preview = "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg"
            test_url = "https://youtu.be/dQw4w9WgXcQ"

        # Рядки опису
        now_utc = datetime.now(timezone.utc)
        date_line = discord_ts(now_utc, 'f')
        platform_title_line = f"{plat_emoji} {('Twitch' if plat == 'twitch' else 'YouTube')}"
        if mode == "live":
            title = "Rick Astley — Never Gonna Give You Up (LIVE)"
            viewers_line = "**Зараз дивляться:** 123"
            status_line = None
        else:
            title = "Rick Astley — Never Gonna Give You Up (ВІДЕО)"
            viewers_line = None
            status_line = None

        title_text = "Стрімери 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲"
        embed = discord.Embed(title=title_text, color=color)
        stream_line = f"[**{title}**]({test_url})"

        parts = [f"**{date_line}**", f"{platform_title_line} • {stream_line}"]
        game_line = f"{GAME_EMOJI or '🎮'} Black Desert"
        if mode == "live":
            parts.append(game_line)
        if viewers_line:
            parts.append(viewers_line)
        if status_line:
            parts.append(status_line)
        embed.description = "\n\n".join(parts)

        # Thumbnail праворуч — аватар стрімера (Discord зробить круглим)
        av_member = (стрімер or interaction.user)
        avatar_url = av_member.display_avatar.replace(size=128, format="png").url if hasattr(av_member.display_avatar, "replace") else av_member.display_avatar.url
        embed.set_thumbnail(url=avatar_url)

        files: list[discord.File] = []
        icon_file: Optional[discord.File] = None
        avatar_file: Optional[discord.File] = None
        async with aiohttp.ClientSession() as session:
            avatar_file = await self._circle_avatar_file(session, avatar_url)
            icon_file = await self._fetch_icon_60(session, plat_icon_url)
        if avatar_file:
            embed.set_thumbnail(url=f"attachment://{avatar_file.filename}")
            files.append(avatar_file)
        bust = str(int(time.time()))
        embed.set_image(url=f"{preview}{'&' if '?' in preview else '?'}t={bust}")
        if icon_file:
            files.append(icon_file)

        embed.set_footer(
            text="Silent Concierge by Myxa | Спостерігаю останнім оком",
            icon_url=self.bot.user.display_avatar.url,
        )

        content = (f"Нове відео на каналі {(стрімер or interaction.user).mention} — дивись [тут]({test_url})!" if mode == "video" else random.choice(ANNOUNCE_LINES).format(mention=(стрімер or interaction.user).mention, url=test_url))
        await канал.send(content=content, embed=embed, files=files)
        await interaction.response.send_message(f"✅ Надіслано у {канал.mention}", ephemeral=True)

    # ---- цикл перевірок ----
    @tasks.loop(minutes=2)
    async def check_streams(self):
        await self.bot.wait_until_ready()
        async with aiohttp.ClientSession() as session:
            for s in self.streamers:
                platform = s.get("platform")
                username = s.get("username")
                discord_id = s.get("discord_id")
                if not platform or not username or not discord_id:
                    continue

                # 1) LIVE-перевірка (як і було)
                try:
                    if platform == "twitch":
                        url_uptime = f"https://decapi.me/twitch/uptime/{username}"
                    else:
                        url_uptime = f"https://decapi.me/youtube/uptime?id={username}"
                    async with session.get(url_uptime) as resp:
                        text = (await resp.text()).lower().strip()
                except Exception:
                    text = "offline"

                if ("offline" in text) or ("not live" in text):
                    self._checked_live.discard((platform, username))
                else:
                    if (platform, username) not in self._checked_live:
                        await self.announce_stream(session, platform, username, discord_id)
                        self._checked_live.add((platform, username))
                    # якщо live — не шукаємо відео в цей цикл
                    continue

                # 2) Перевірка нових ВІДЕО (не live)
                try:
                    if platform == "youtube":
                        # спершу отримати channel_id
                        ch_id = s.get("yt_channel_id")
                        if not ch_id:
                            ch_id = await self._yt_resolve_channel_id(session, username)
                            if ch_id:
                                s["yt_channel_id"] = ch_id
                                self.save_streamers()
                        if ch_id:
                            await self.check_youtube_video(session, ch_id, discord_id)
                    else:  # twitch
                        await self.check_twitch_upload(session, username, discord_id)
                except Exception as e:
                    print(f"[STREAM_COG] video check error for {platform}:{username}: {e}")

    async def check_youtube_video(self, session: aiohttp.ClientSession, channel_id: str, discord_id: int):
        latest = await self._yt_latest_video_from_rss(session, channel_id)
        if not latest:
            return
        vid = latest["video_id"]
        # відітнемо старі відео
        pub_ts = None
        try:
            pub_ts = datetime.fromisoformat(latest["published"].replace("Z", "+00:00"))
        except Exception:
            pass
        if pub_ts and datetime.now(timezone.utc) - pub_ts > timedelta(hours=NEW_VIDEO_MAX_AGE_HOURS):
            return

        last = self.last_seen.get("youtube", {}).get(channel_id)
        if last == vid:
            return
        # оновити кеш і оголосити
        self.last_seen.setdefault("youtube", {})[channel_id] = vid
        self.save_last_seen()
        await self.announce_video(
            platform="youtube",
            title=latest["title"],
            url=latest["link"],
            preview=latest["thumb"],
            discord_id=discord_id,
        )

    async def check_twitch_upload(self, session: aiohttp.ClientSession, login: str, discord_id: int):
        latest = await self._twitch_latest_upload(session, login)
        if not latest:
            return
        vid_id = latest["id"]
        last = self.last_seen.get("twitch", {}).get(login)
        if last == vid_id:
            return
        # «свіжість»: якщо дуже давнє — пропускаємо (created_at у ISO)
        try:
            created = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - created > timedelta(hours=NEW_VIDEO_MAX_AGE_HOURS):
                return
        except Exception:
            pass

        self.last_seen.setdefault("twitch", {})[login] = vid_id
        self.save_last_seen()
        await self.announce_video(
            platform="twitch",
            title=latest["title"],
            url=latest["url"],
            preview=latest["thumbnail_url"],
            discord_id=discord_id,
        )

    async def announce_video(self, platform: str, title: str, url: str, preview: Optional[str], discord_id: int):
        """Анонс ДЛЯ ЗВИЧАЙНОГО ВІДЕО (НЕ стрім)."""
        plat_icon_url, plat_emoji = self.platform_assets(platform)
        now_utc = datetime.now(timezone.utc)
        date_line = discord_ts(now_utc, 'f')
        platform_title_line = f"{plat_emoji} {('Twitch' if platform == 'twitch' else 'YouTube')}"
        stream_line = f"[**{title or 'Відео'}**]({url})"
        color = random.choice(STREAM_COLORS)
        embed = discord.Embed(title="Стрімери 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲", color=color)
        embed.description = "\n\n".join([
            f"**{date_line}**",
            f"{platform_title_line} • {stream_line}",
        ])

        # Аватар автора — беремо з дискорду
        guild = discord.utils.get(self.bot.guilds, id=GUILD_ID)
        member = guild.get_member(discord_id) if guild else None
        avatar_url = (
            member.display_avatar.replace(size=128, format="png").url
            if member and hasattr(member.display_avatar, "replace")
            else (member.display_avatar.url if member else self.bot.user.display_avatar.url)
        )

        files: list[discord.File] = []
        async with aiohttp.ClientSession() as session:
            avatar_file = await self._circle_avatar_file(session, avatar_url)
            icon_file = await self._fetch_icon_60(session, plat_icon_url)
        if avatar_file:
            embed.set_thumbnail(url=f"attachment://{avatar_file.filename}")
            files.append(avatar_file)

        if preview:
            bust = str(int(time.time()))
            embed.set_image(url=f"{preview}{'&' if '?' in preview else '?'}t={bust}")
        if icon_file:
            files.append(icon_file)

        embed.set_footer(
            text="Silent Concierge by Myxa | Спостерігаю останнім оком",
            icon_url=self.bot.user.display_avatar.url,
        )

        channel = discord.utils.get(self.bot.get_all_channels(), name=STREAM_ANNOUNCE_CHANNEL_NAME)
        if channel:
            content = f"Нове відео на каналі <@{discord_id}> — дивись [тут]({url})!"
            await channel.send(content=content, embed=embed, files=files)

    async def announce_stream(self, session: aiohttp.ClientSession, platform: str, username: str, discord_id: int):
        if platform == "twitch":
            stream_url = f"https://www.twitch.tv/{username}"
            viewers_url = f"https://decapi.me/twitch/viewercount/{username}"
            title_url = f"https://decapi.me/twitch/status/{username}"
            preview = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{username}-640x360.jpg"
            plat_emoji = TWITCH_EMOJI
            plat_icon_url = TWITCH_ICON_IMG
            try:
                async with session.get(f"https://decapi.me/twitch/game/{username}") as g:
                    game_name = (await g.text()).strip()
            except Exception:
                game_name = ""
        else:
            stream_url = f"https://youtube.com/watch?v={username}"
            viewers_url = f"https://decapi.me/youtube/viewercount?id={username}"
            title_url = f"https://decapi.me/youtube/title?id={username}"
            preview = f"https://img.youtube.com/vi/{username}/mqdefault.jpg"
            plat_emoji = YOUTUBE_EMOJI
            plat_icon_url = YOUTUBE_ICON_IMG
            game_name = ""

        try:
            async with session.get(viewers_url) as v:
                viewers = (await v.text()).strip() or "0"
        except Exception:
            viewers = "0"
        try:
            async with session.get(title_url) as t:
                title = (await t.text()).strip()
        except Exception:
            title = "🔴 LIVE"

        now_utc = datetime.now(timezone.utc)
        date_line = discord_ts(now_utc, 'f')
        platform_title_line = f"{plat_emoji} {('Twitch' if platform == 'twitch' else 'YouTube')}"
        stream_line = f"[**{title}**]({stream_url})"

        # Гра — пробуємо взяти іконку з локального JSON, інакше просто назву
        game_display = game_name if game_name else ""
        game_line = (f"{GAME_EMOJI or '🎮'} {game_display}" if game_display else "").strip()

        viewers_line = f"**Зараз дивляться:** {viewers}"

        color = random.choice(STREAM_COLORS)
        embed = discord.Embed(title="Стрімери 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲", color=color)

        parts = [f"**{date_line}**", f"{platform_title_line} • {stream_line}"]
        if game_line:
            parts.append(game_line)
        parts.append(viewers_line)
        embed.description = "\n\n".join(parts)

        # Аватар стрімера (thumbnail)
        guild = discord.utils.get(self.bot.guilds, id=GUILD_ID)
        member = guild.get_member(discord_id) if guild else None
        avatar_url = (
            member.display_avatar.replace(size=128, format="png").url
            if member and hasattr(member.display_avatar, "replace")
            else (member.display_avatar.url if member else self.bot.user.display_avatar.url)
        )
        files: list[discord.File] = []
        avatar_file = await self._circle_avatar_file(session, avatar_url)
        if avatar_file:
            # ЄДИНИЙ аватар у ембеді — як круглий thumbnail (attachment)
            embed.set_thumbnail(url=f"attachment://{avatar_file.filename}")
            files.append(avatar_file)
        # Прев'ю без оверлеїв, з cache-bust
        bust = str(int(time.time()))
        embed.set_image(url=f"{preview}{'&' if '?' in preview else '?'}t={bust}")

        # Платформену іконку 60×60 додаємо як файл (thumbnail не чіпаємо)
        async with aiohttp.ClientSession() as tmp:
            icon_file = await self._fetch_icon_60(tmp, plat_icon_url)
        if icon_file:
            files.append(icon_file)

        embed.set_footer(
            text="Silent Concierge by Myxa | Спостерігаю останнім оком",
            icon_url=self.bot.user.display_avatar.url,
        )

        channel = discord.utils.get(self.bot.get_all_channels(), name=STREAM_ANNOUNCE_CHANNEL_NAME)
        if channel:
            content = random.choice(ANNOUNCE_LINES).format(mention=f"<@{discord_id}>", url=stream_url)
            await channel.send(content=content, embed=embed, files=files)

    @check_streams.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    # ---- керування мапою іконок ігор ----
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.describe(гра="Назва гри як у стрімі (точно)", іконка_url="Повний URL офіційної іконки (PNG/WebP)")
    @app_commands.command(name="гра_іконка", description="Додати/оновити URL іконки для гри")
    async def set_game_icon(self, interaction: discord.Interaction, гра: str, іконка_url: str):
        key = гра.strip().lower()
        self.game_icons[key] = іконка_url.strip()
        self.save_game_icons()
        await interaction.response.send_message(f"✅ Іконку для **{гра}** збережено.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StreamCog(bot))
