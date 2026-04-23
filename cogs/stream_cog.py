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
Stream Cog - ПОВНИЙ КОД

ЩО ВИПРАВЛЕНО:
- Усі JSON-файли лежать у config/
- Канал анонсів тепер через ID, а не по назві
- YouTube більше не шле фейкові live-анонси з 404
- Twitch live лишився
- YouTube нові відео через RSS лишилися
- Twitch uploads лишилися
- Додані debug print-и для шляху до файлів

ВАЖЛИВО:
- YouTube live тут вимкнений свідомо, бо стара логіка була побудована на username як video_id,
  а в тебе зберігається канал / handle. Через це й був 404 Page Not Found.
"""

# ==== НАЛАШТУВАННЯ ====
GUILD_ID = int(os.getenv("GUILD_ID", "1323454227816906802"))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
os.makedirs(CONFIG_DIR, exist_ok=True)

STREAMERS_FILE = os.path.join(CONFIG_DIR, "streamers.json")
GAME_ICONS_FILE = os.path.join(CONFIG_DIR, "game_icons.json")
LAST_SEEN_FILE = os.path.join(CONFIG_DIR, "streams_last_seen.json")

STREAM_ANNOUNCE_CHANNEL_ID = int(os.getenv("STREAM_ANNOUNCE_CHANNEL_ID", "1395410247375655072"))

# Часове вікно "свіжості" відео
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

# Платформені іконки
TWITCH_ICON_IMG = "https://i.imgur.com/5Us8X2r.png"
YOUTUBE_ICON_IMG = "https://i.imgur.com/xD7czCG.png"

# Емодзі для текстових рядків
TWITCH_EMOJI = "<:twitch_icon:1403350256271364268>"
YOUTUBE_EMOJI = "<:youtube_icon:1403350209630699652>"

# Емодзі гри
GAME_EMOJI = os.getenv("GAME_EMOJI", "")

# Twitch Helix
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
_TWITCH_TOKEN: Optional[str] = None
_TWITCH_TOKEN_EXP = 0

# Рандомні фрази для live-анонсів
ANNOUNCE_LINES = [
    "Наш спеціальний агент {mention} працює у [небезпечних умовах]({url})",
    "Агент {mention} уже в ефірі - дивись [тут]({url})",
    "На зв'язку агент {mention}. Приєднуйся [тут]({url})",
    "{mention} виходить на зв'язок зі зони турбулентності - клацай [тут]({url})",
    "{mention} ризикує заради контенту - залітай [тут]({url})",
    "Стрим на місії! Агент {mention} чекає [тут]({url})",
    "Гарячий ефір від агента {mention} - тисни [тут]({url})",
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
    m = _UA_MONTHS_GEN[dt.month]
    return f"{dt.day} {m} {dt.year} р. {dt.hour:02d}:{dt.minute:02d}"


def discord_ts(dt: datetime, style: str = "f") -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ts = int(dt.timestamp())
    return f"<t:{ts}:{style}>"


async def _get_twitch_headers(session: aiohttp.ClientSession) -> Optional[dict]:
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

    return {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {_TWITCH_TOKEN}",
    }


class StreamCog(commands.Cog):
    # ---------- image helpers ----------
    async def _circle_avatar_file(
        self,
        session: aiohttp.ClientSession,
        avatar_url: str,
        size: int = 96
    ) -> Optional[discord.File]:
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

    async def _fetch_icon_60(
        self,
        session: aiohttp.ClientSession,
        url: str,
        size: int = 60
    ) -> Optional[discord.File]:
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
        print(f"[STREAM_COG] loading streamers from: {STREAMERS_FILE}")
        print(f"[STREAM_COG] absolute streamers path: {os.path.abspath(STREAMERS_FILE)}")

        if os.path.exists(STREAMERS_FILE):
            with open(STREAMERS_FILE, "r", encoding="utf-8") as f:
                try:
                    self.streamers = json.load(f)
                    if not isinstance(self.streamers, list):
                        self.streamers = []
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
                    self.game_icons = {
                        str(k).strip().lower(): str(v).strip()
                        for k, v in data.items()
                        if v
                    }
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
                    if not isinstance(self.last_seen, dict):
                        self.last_seen = {"youtube": {}, "twitch": {}}
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

    def get_announce_channel(self) -> Optional[discord.abc.Messageable]:
        channel = self.bot.get_channel(STREAM_ANNOUNCE_CHANNEL_ID)
        if channel is None:
            print(f"[STREAM_COG] ❌ Канал анонсів не знайдено: {STREAM_ANNOUNCE_CHANNEL_ID}")
        return channel

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
        try:
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

    async def _yt_latest_video_from_rss(
        self,
        session: aiohttp.ClientSession,
        channel_id: str
    ) -> Optional[Dict[str, Any]]:
        try:
            rss = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            async with session.get(rss) as r:
                text = await r.text()

            root = ET.fromstring(text)
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "yt": "http://www.youtube.com/xml/schemas/2015",
            }

            entry = root.find("atom:entry", ns)
            if entry is None:
                return None

            title_el = entry.find("atom:title", ns)
            title = (title_el.text or "").strip() if title_el is not None else "Відео"

            link_el = entry.find("atom:link", ns)
            link = link_el.get("href") if link_el is not None else ""

            vid_el = entry.find("yt:videoId", ns)
            video_id = vid_el.text if vid_el is not None else None

            pub_el = entry.find("atom:published", ns)
            published = pub_el.text if pub_el is not None else None

            if not video_id:
                return None

            thumb = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"

            return {
                "video_id": video_id,
                "title": title or "Відео",
                "published": published,
                "link": link or f"https://youtu.be/{video_id}",
                "thumb": thumb,
            }
        except Exception:
            return None

    # ---- slash-команди ----
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.describe(
        платформа="Платформа",
        посилання="Посилання на канал або стрім",
        користувач="Нік з Discord"
    )
    @app_commands.choices(платформа=[
        app_commands.Choice(name="twitch", value="twitch"),
        app_commands.Choice(name="youtube", value="youtube"),
    ])
    @app_commands.command(name="додати_стрімера", description="Додати стрімера Twitch/YouTube")
    async def add_streamer(
        self,
        interaction: discord.Interaction,
        платформа: app_commands.Choice[str],
        посилання: str,
        користувач: discord.User
    ):
        try:
            plat = платформа.value
            username = self.extract_username(plat, посилання)

            if not username:
                await interaction.response.send_message("❌ Не вдалося визначити ідентифікатор", ephemeral=True)
                return

            extra: Dict[str, Any] = {}

            if plat == "youtube":
                async with aiohttp.ClientSession() as session:
                    ch_id = await self._yt_resolve_channel_id(session, username)
                if ch_id:
                    extra["yt_channel_id"] = ch_id

            for s in self.streamers:
                if (
                    s.get("platform") == plat
                    and s.get("username") == username
                    and s.get("discord_id") == користувач.id
                ):
                    await interaction.response.send_message("⚠️ Цей стрімер уже доданий.", ephemeral=True)
                    return

            item = {
                "platform": plat,
                "username": username,
                "discord_id": користувач.id,
            }
            item.update(extra)

            self.streamers.append(item)
            self.save_streamers()

            print(f"[STREAM_COG] saved item: {item}")
            print(f"[STREAM_COG] streamers file: {STREAMERS_FILE}")
            print(f"[STREAM_COG] absolute path: {os.path.abspath(STREAMERS_FILE)}")
            print(f"[STREAM_COG] current streamers: {self.streamers}")

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
    async def test_stream(
        self,
        interaction: discord.Interaction,
        канал: discord.TextChannel,
        платформа: app_commands.Choice[str],
        тип: app_commands.Choice[str],
        стрімер: Optional[discord.Member] = None
    ):
        plat = платформа.value
        mode = тип.value
        plat_icon_url, plat_emoji = self.platform_assets(plat)
        color = random.choice(STREAM_COLORS)

        if plat == "twitch":
            preview = "https://static-cdn.jtvnw.net/ttv-static/404_preview-640x360.jpg"
            test_url = "https://www.twitch.tv/twitch"
        else:
            preview = "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg"
            test_url = "https://youtu.be/dQw4w9WgXcQ"

        now_utc = datetime.now(timezone.utc)
        date_line = discord_ts(now_utc, "f")
        platform_title_line = f"{plat_emoji} {('Twitch' if plat == 'twitch' else 'YouTube')}"

        if mode == "live":
            title = "Rick Astley - Never Gonna Give You Up (LIVE)"
            viewers_line = "**Зараз дивляться:** 123"
        else:
            title = "Rick Astley - Never Gonna Give You Up (ВІДЕО)"
            viewers_line = None

        embed = discord.Embed(title="Стрімери 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲", color=color)
        stream_line = f"[**{title}**]({test_url})"

        parts = [f"**{date_line}**", f"{platform_title_line} • {stream_line}"]
        if mode == "live":
            parts.append(f"{GAME_EMOJI or '🎮'} Black Desert")
        if viewers_line:
            parts.append(viewers_line)

        embed.description = "\n\n".join(parts)

        av_member = (стрімер or interaction.user)
        avatar_url = (
            av_member.display_avatar.replace(size=128, format="png").url
            if hasattr(av_member.display_avatar, "replace")
            else av_member.display_avatar.url
        )

        files: list[discord.File] = []

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

        content = (
            f"Нове відео на каналі {(стрімер or interaction.user).mention} - дивись [тут]({test_url})!"
            if mode == "video"
            else random.choice(ANNOUNCE_LINES).format(
                mention=(стрімер or interaction.user).mention,
                url=test_url
            )
        )

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

                # 1) LIVE-перевірка тільки для Twitch
                if platform == "twitch":
                    try:
                        url_uptime = f"https://decapi.me/twitch/uptime/{username}"
                        async with session.get(url_uptime) as resp:
                            text = (await resp.text()).lower().strip()
                    except Exception:
                        text = "offline"

                    if (
                        "offline" in text
                        or "not live" in text
                        or "404" in text
                        or "page not found" in text
                        or "error" in text
                        or "not found" in text
                    ):
                        self._checked_live.discard((platform, username))
                    else:
                        if (platform, username) not in self._checked_live:
                            await self.announce_stream(session, platform, username, discord_id)
                            self._checked_live.add((platform, username))
                        continue

                # 2) Перевірка нових відео
                try:
                    if platform == "youtube":
                        ch_id = s.get("yt_channel_id")

                        if not ch_id:
                            ch_id = await self._yt_resolve_channel_id(session, username)
                            if ch_id:
                                s["yt_channel_id"] = ch_id
                                self.save_streamers()

                        if ch_id:
                            await self.check_youtube_video(session, ch_id, discord_id)
                    else:
                        await self.check_twitch_upload(session, username, discord_id)
                except Exception as e:
                    print(f"[STREAM_COG] video check error for {platform}:{username}: {e}")

    async def check_youtube_video(self, session: aiohttp.ClientSession, channel_id: str, discord_id: int):
        latest = await self._yt_latest_video_from_rss(session, channel_id)
        if not latest:
            return

        vid = latest["video_id"]

        pub_ts = None
        try:
            if latest["published"]:
                pub_ts = datetime.fromisoformat(latest["published"].replace("Z", "+00:00"))
        except Exception:
            pass

        if pub_ts and datetime.now(timezone.utc) - pub_ts > timedelta(hours=NEW_VIDEO_MAX_AGE_HOURS):
            return

        last = self.last_seen.get("youtube", {}).get(channel_id)
        if last == vid:
            return

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
        plat_icon_url, plat_emoji = self.platform_assets(platform)
        now_utc = datetime.now(timezone.utc)
        date_line = discord_ts(now_utc, "f")
        platform_title_line = f"{plat_emoji} {('Twitch' if platform == 'twitch' else 'YouTube')}"
        stream_line = f"[**{title or 'Відео'}**]({url})"
        color = random.choice(STREAM_COLORS)

        embed = discord.Embed(title="Стрімери 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲", color=color)
        embed.description = "\n\n".join([
            f"**{date_line}**",
            f"{platform_title_line} • {stream_line}",
        ])

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

        channel = self.get_announce_channel()
        if channel:
            await channel.send(
                content=f"Нове відео на каналі <@{discord_id}> - дивись [тут]({url})!",
                embed=embed,
                files=files
            )

    async def announce_stream(self, session: aiohttp.ClientSession, platform: str, username: str, discord_id: int):
        if platform != "twitch":
            return

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
        date_line = discord_ts(now_utc, "f")
        platform_title_line = f"{plat_emoji} Twitch"
        stream_line = f"[**{title}**]({stream_url})"

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
            embed.set_thumbnail(url=f"attachment://{avatar_file.filename}")
            files.append(avatar_file)

        bust = str(int(time.time()))
        embed.set_image(url=f"{preview}{'&' if '?' in preview else '?'}t={bust}")

        icon_file = await self._fetch_icon_60(session, plat_icon_url)
        if icon_file:
            files.append(icon_file)

        embed.set_footer(
            text="Silent Concierge by Myxa | Спостерігаю останнім оком",
            icon_url=self.bot.user.display_avatar.url,
        )

        channel = self.get_announce_channel()
        if channel:
            await channel.send(
                content=random.choice(ANNOUNCE_LINES).format(
                    mention=f"<@{discord_id}>",
                    url=stream_url
                ),
                embed=embed,
                files=files
            )

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
