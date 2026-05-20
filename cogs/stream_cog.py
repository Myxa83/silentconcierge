# -*- coding: utf-8 -*-
# stream_cog.py — MongoDB версія

import os
import re
import json
import time
import random
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

import aiohttp
import discord
from discord.ext import commands, tasks
from discord import app_commands
from pymongo import MongoClient

try:
    from PIL import Image, ImageDraw
    from io import BytesIO
    _PIL_OK = True
except Exception:
    _PIL_OK = False

# ─── Налаштування ────────────────────────────────────────────────────────────

GUILD_ID = int(os.getenv("GUILD_ID", "1323454227816906802"))
STREAM_ANNOUNCE_CHANNEL_ID = int(os.getenv("STREAM_ANNOUNCE_CHANNEL_ID", "1395410247375655072"))
NEW_VIDEO_MAX_AGE_HOURS = int(os.getenv("NEW_VIDEO_MAX_AGE_HOURS", "48"))

STREAM_COLORS = [0xFF4000, 0xFFFF00, 0x00FF00, 0x00FF80, 0x00BFFF, 0x4000FF, 0x8000FF, 0xFF0040]

TWITCH_ICON_IMG  = "https://i.imgur.com/5Us8X2r.png"
YOUTUBE_ICON_IMG = "https://i.imgur.com/xD7czCG.png"
TWITCH_EMOJI     = "<:twitch_icon:1403350256271364268>"
YOUTUBE_EMOJI    = "<:youtube_icon:1403350209630699652>"
GAME_EMOJI       = os.getenv("GAME_EMOJI", "")

TWITCH_CLIENT_ID     = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
_TWITCH_TOKEN        = None
_TWITCH_TOKEN_EXP    = 0

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

# ─── MongoDB ─────────────────────────────────────────────────────────────────

_mongo_client = None
_mongo_db     = None

def _get_db():
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        url = os.environ.get("MONGODB_URL", "")
        _mongo_client = MongoClient(url, serverSelectionTimeoutMS=10000)
        _mongo_db = _mongo_client["silentconcierge"]
        print(f"[STREAM] MongoDB підключено: {_mongo_db.name}")
    return _mongo_db


def _load_streamers() -> list:
    try:
        db  = _get_db()
        doc = db["streamers"].find_one({"_id": "main"})
        if doc:
            return doc.get("list", [])
    except Exception as e:
        print(f"[STREAM][ERROR] load streamers: {e}")
    return []


def _save_streamers(streamers: list) -> None:
    try:
        db = _get_db()
        db["streamers"].replace_one(
            {"_id": "main"},
            {"_id": "main", "list": streamers},
            upsert=True,
        )
    except Exception as e:
        print(f"[STREAM][ERROR] save streamers: {e}")


def _load_last_seen() -> dict:
    try:
        db  = _get_db()
        doc = db["stream_last_seen"].find_one({"_id": "main"})
        if doc:
            doc.pop("_id", None)
            return doc
    except Exception as e:
        print(f"[STREAM][ERROR] load last_seen: {e}")
    return {"youtube": {}, "twitch": {}}


def _save_last_seen(last_seen: dict) -> None:
    try:
        db = _get_db()
        db["stream_last_seen"].replace_one(
            {"_id": "main"},
            {"_id": "main", **last_seen},
            upsert=True,
        )
    except Exception as e:
        print(f"[STREAM][ERROR] save last_seen: {e}")


def _load_game_icons() -> dict:
    try:
        db  = _get_db()
        doc = db["game_icons"].find_one({"_id": "main"})
        if doc:
            return doc.get("icons", {})
    except Exception as e:
        print(f"[STREAM][ERROR] load game_icons: {e}")
    return {}


def _save_game_icons(icons: dict) -> None:
    try:
        db = _get_db()
        db["game_icons"].replace_one(
            {"_id": "main"},
            {"_id": "main", "icons": icons},
            upsert=True,
        )
    except Exception as e:
        print(f"[STREAM][ERROR] save game_icons: {e}")

# ─── Twitch token ─────────────────────────────────────────────────────────────

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
            _TWITCH_TOKEN     = data.get("access_token")
            _TWITCH_TOKEN_EXP = now + int(data.get("expires_in", 3600)) - 60
    if not _TWITCH_TOKEN:
        return None
    return {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {_TWITCH_TOKEN}"}

# ─── Cog ──────────────────────────────────────────────────────────────────────

class StreamCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot        = bot
        self.streamers  = _load_streamers()
        self.game_icons = _load_game_icons()
        self.last_seen  = _load_last_seen()
        self._checked_live: set[tuple[str, str]] = set()
        self.check_streams.start()
        print(f"[STREAM] Завантажено стрімерів: {len(self.streamers)}")

    def cog_unload(self):
        self.check_streams.cancel()

    # ── Image helpers ────────────────────────────────────────────────────────

    async def _circle_avatar_file(self, session, avatar_url, size=96):
        if not _PIL_OK:
            return None
        try:
            async with session.get(avatar_url) as av:
                av_bytes = await av.read()
            avatar = Image.open(BytesIO(av_bytes)).convert("RGBA").resize((size, size), Image.LANCZOS)
            mask   = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            avatar.putalpha(mask)
            out = BytesIO()
            avatar.save(out, format="PNG")
            out.seek(0)
            return discord.File(out, filename="avatar_circle.png")
        except Exception:
            return None

    async def _fetch_icon_60(self, session, url, size=60):
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

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def extract_username(platform: str, value: str) -> Optional[str]:
        value = value.strip()
        if platform == "twitch":
            if value.startswith("http"):
                m = re.search(r"twitch\.tv/([-\w]+)", value)
                return m.group(1) if m else None
            return value
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

    def get_announce_channel(self):
        return self.bot.get_channel(STREAM_ANNOUNCE_CHANNEL_ID)

    async def _yt_resolve_channel_id(self, session, identifier: str) -> Optional[str]:
        # Спробуємо через decapi
        try:
            async with session.get(f"https://decapi.me/youtube/channelid?search={identifier}") as r:
                cid = (await r.text()).strip()
                if cid.startswith("UC") and len(cid) > 10:
                    return cid
        except Exception:
            pass
        # Якщо identifier вже є channel_id
        if identifier.startswith("UC") and len(identifier) > 10:
            return identifier
        # Спробуємо через RSS напряму з @handle
        try:
            handle = identifier.lstrip("@")
            async with session.get(
                f"https://www.youtube.com/@{handle}",
                headers={"User-Agent": "Mozilla/5.0"},
            ) as r:
                text = await r.text()
            m = re.search(r'"channelId":"(UC[\w-]+)"', text)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    async def _yt_latest_video_from_rss(self, session, channel_id: str) -> Optional[dict]:
        try:
            rss = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
            async with session.get(rss) as r:
                text = await r.text()
            root = ET.fromstring(text)
            ns   = {
                "atom": "http://www.w3.org/2005/Atom",
                "yt":   "http://www.youtube.com/xml/schemas/2015",
            }
            entry = root.find("atom:entry", ns)
            if entry is None:
                return None
            title_el = entry.find("atom:title", ns)
            title    = (title_el.text or "").strip() if title_el is not None else "Відео"
            link_el  = entry.find("atom:link", ns)
            link     = link_el.get("href") if link_el is not None else ""
            vid_el   = entry.find("yt:videoId", ns)
            video_id = vid_el.text if vid_el is not None else None
            pub_el   = entry.find("atom:published", ns)
            published = pub_el.text if pub_el is not None else None
            if not video_id:
                return None
            return {
                "video_id":  video_id,
                "title":     title or "Відео",
                "published": published,
                "link":      link or f"https://youtu.be/{video_id}",
                "thumb":     f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            }
        except Exception as e:
            print(f"[STREAM] RSS error for {channel_id}: {e}")
            return None

    async def _twitch_user_id(self, session, login: str) -> Optional[str]:
        headers = await _get_twitch_headers(session)
        if not headers:
            return None
        async with session.get(f"https://api.twitch.tv/helix/users?login={login}", headers=headers) as r:
            jd = await r.json()
        if isinstance(jd, dict) and jd.get("data"):
            return jd["data"][0].get("id")
        return None

    async def _twitch_latest_upload(self, session, login: str) -> Optional[dict]:
        headers = await _get_twitch_headers(session)
        if not headers:
            return None
        uid = await self._twitch_user_id(session, login)
        if not uid:
            return None
        async with session.get(
            f"https://api.twitch.tv/helix/videos?user_id={uid}&type=upload&first=1",
            headers=headers,
        ) as r:
            jd = await r.json()
        data = jd.get("data", []) if isinstance(jd, dict) else []
        if not data:
            return None
        v = data[0]
        return {
            "id":            v.get("id"),
            "title":         v.get("title") or "Відео",
            "url":           v.get("url"),
            "thumbnail_url": (v.get("thumbnail_url") or "").replace("%{width}", "640").replace("%{height}", "360"),
            "created_at":    v.get("created_at"),
        }

    # ── Перевірка стрімів ────────────────────────────────────────────────────

    @tasks.loop(minutes=2)
    async def check_streams(self):
        # Перезавантажуємо з MongoDB кожен цикл
        self.streamers  = _load_streamers()
        self.last_seen  = _load_last_seen()
        self.game_icons = _load_game_icons()

        async with aiohttp.ClientSession() as session:
            for s in self.streamers:
                platform   = s.get("platform")
                username   = s.get("username")
                discord_id = s.get("discord_id")
                if not platform or not username or not discord_id:
                    continue

                # Twitch live
                if platform == "twitch":
                    try:
                        async with session.get(f"https://decapi.me/twitch/uptime/{username}") as resp:
                            text = (await resp.text()).lower().strip()
                    except Exception:
                        text = "offline"

                    is_live = not any(w in text for w in ["offline", "not live", "404", "error", "not found"])

                    if is_live:
                        if (platform, username) not in self._checked_live:
                            print(f"[STREAM] {username} live on Twitch!")
                            await self.announce_stream(session, platform, username, discord_id)
                            self._checked_live.add((platform, username))
                        continue
                    else:
                        self._checked_live.discard((platform, username))

                # Нові відео
                try:
                    if platform == "youtube":
                        ch_id = s.get("yt_channel_id")
                        if not ch_id:
                            print(f"[STREAM] Resolving channel_id for {username}...")
                            ch_id = await self._yt_resolve_channel_id(session, username)
                            if ch_id:
                                s["yt_channel_id"] = ch_id
                                _save_streamers(self.streamers)
                                print(f"[STREAM] Resolved: {username} → {ch_id}")
                            else:
                                print(f"[STREAM] Could not resolve channel_id for {username}")
                        if ch_id:
                            await self.check_youtube_video(session, ch_id, discord_id)
                    elif platform == "twitch":
                        await self.check_twitch_upload(session, username, discord_id)
                except Exception as e:
                    print(f"[STREAM] video check error {platform}:{username}: {e}")

    @check_streams.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    async def check_youtube_video(self, session, channel_id: str, discord_id: int):
        latest = await self._yt_latest_video_from_rss(session, channel_id)
        if not latest:
            return
        vid = latest["video_id"]
        # Перевірка свіжості
        if latest["published"]:
            try:
                pub_ts = datetime.fromisoformat(latest["published"].replace("Z", "+00:00"))
                if datetime.now(timezone.utc) - pub_ts > timedelta(hours=NEW_VIDEO_MAX_AGE_HOURS):
                    return
            except Exception:
                pass
        last = self.last_seen.get("youtube", {}).get(channel_id)
        if last == vid:
            return
        print(f"[STREAM] New YouTube video: {latest['title']}")
        self.last_seen.setdefault("youtube", {})[channel_id] = vid
        _save_last_seen(self.last_seen)
        await self.announce_video("youtube", latest["title"], latest["link"], latest["thumb"], discord_id)

    async def check_twitch_upload(self, session, login: str, discord_id: int):
        latest = await self._twitch_latest_upload(session, login)
        if not latest:
            return
        vid_id = latest["id"]
        try:
            created = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - created > timedelta(hours=NEW_VIDEO_MAX_AGE_HOURS):
                return
        except Exception:
            pass
        last = self.last_seen.get("twitch", {}).get(login)
        if last == vid_id:
            return
        print(f"[STREAM] New Twitch upload: {latest['title']}")
        self.last_seen.setdefault("twitch", {})[login] = vid_id
        _save_last_seen(self.last_seen)
        await self.announce_video("twitch", latest["title"], latest["url"], latest["thumbnail_url"], discord_id)

    # ── Анонси ───────────────────────────────────────────────────────────────

    async def _build_embed_files(self, session, avatar_url: str, platform: str, preview: Optional[str]):
        plat_icon_url, _ = self.platform_assets(platform)
        files = []
        embed_kwargs = {}

        avatar_file = await self._circle_avatar_file(session, avatar_url)
        if avatar_file:
            embed_kwargs["thumbnail"] = f"attachment://{avatar_file.filename}"
            files.append(avatar_file)

        if preview:
            bust = str(int(time.time()))
            embed_kwargs["image"] = f"{preview}{'&' if '?' in preview else '?'}t={bust}"

        icon_file = await self._fetch_icon_60(session, plat_icon_url)
        if icon_file:
            files.append(icon_file)

        return files, embed_kwargs

    def _get_member_avatar(self, discord_id: int) -> str:
        guild  = discord.utils.get(self.bot.guilds, id=GUILD_ID)
        member = guild.get_member(discord_id) if guild else None
        if member and hasattr(member.display_avatar, "replace"):
            return member.display_avatar.replace(size=128, format="png").url
        if member:
            return member.display_avatar.url
        return self.bot.user.display_avatar.url

    def _discord_ts(self, dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return f"<t:{int(dt.timestamp())}:f>"

    async def announce_video(self, platform: str, title: str, url: str, preview: Optional[str], discord_id: int):
        _, plat_emoji    = self.platform_assets(platform)
        plat_name        = "Twitch" if platform == "twitch" else "YouTube"
        now_utc          = datetime.now(timezone.utc)
        color            = random.choice(STREAM_COLORS)

        embed = discord.Embed(title="Стрімери 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲", color=color)
        embed.description = "\n\n".join([
            f"**{self._discord_ts(now_utc)}**",
            f"{plat_emoji} {plat_name} • [**{title or 'Відео'}**]({url})",
        ])
        embed.set_footer(
            text="Silent Concierge by Myxa | Спостерігаю останнім оком",
            icon_url=self.bot.user.display_avatar.url,
        )

        avatar_url = self._get_member_avatar(discord_id)
        channel    = self.get_announce_channel()
        if not channel:
            return

        async with aiohttp.ClientSession() as session:
            files, ekw = await self._build_embed_files(session, avatar_url, platform, preview)

        if "thumbnail" in ekw:
            embed.set_thumbnail(url=ekw["thumbnail"])
        if "image" in ekw:
            embed.set_image(url=ekw["image"])

        await channel.send(
            content=f"Нове відео на каналі <@{discord_id}> - дивись [тут]({url})!",
            embed=embed,
            files=files,
        )

    async def announce_stream(self, session, platform: str, username: str, discord_id: int):
        if platform != "twitch":
            return

        stream_url = f"https://www.twitch.tv/{username}"
        preview    = f"https://static-cdn.jtvnw.net/previews-ttv/live_user_{username}-640x360.jpg"
        _, plat_emoji = self.platform_assets(platform)

        try:
            async with session.get(f"https://decapi.me/twitch/game/{username}") as g:
                game_name = (await g.text()).strip()
        except Exception:
            game_name = ""

        try:
            async with session.get(f"https://decapi.me/twitch/viewercount/{username}") as v:
                viewers = (await v.text()).strip() or "0"
        except Exception:
            viewers = "0"

        try:
            async with session.get(f"https://decapi.me/twitch/status/{username}") as t:
                title = (await t.text()).strip()
        except Exception:
            title = "🔴 LIVE"

        now_utc = datetime.now(timezone.utc)
        color   = random.choice(STREAM_COLORS)
        embed   = discord.Embed(title="Стрімери 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲", color=color)

        parts = [
            f"**{self._discord_ts(now_utc)}**",
            f"{plat_emoji} Twitch • [**{title}**]({stream_url})",
        ]
        if game_name:
            parts.append(f"{GAME_EMOJI or '🎮'} {game_name}")
        parts.append(f"**Зараз дивляться:** {viewers}")
        embed.description = "\n\n".join(parts)
        embed.set_footer(
            text="Silent Concierge by Myxa | Спостерігаю останнім оком",
            icon_url=self.bot.user.display_avatar.url,
        )

        avatar_url = self._get_member_avatar(discord_id)
        channel    = self.get_announce_channel()
        if not channel:
            return

        files, ekw = await self._build_embed_files(session, avatar_url, platform, preview)
        if "thumbnail" in ekw:
            embed.set_thumbnail(url=ekw["thumbnail"])
        if "image" in ekw:
            embed.set_image(url=ekw["image"])

        await channel.send(
            content=random.choice(ANNOUNCE_LINES).format(
                mention=f"<@{discord_id}>", url=stream_url
            ),
            embed=embed,
            files=files,
        )

    # ── Slash команди ────────────────────────────────────────────────────────

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.describe(
        платформа="Платформа",
        посилання="Посилання на канал або нік",
        користувач="Нік з Discord",
    )
    @app_commands.choices(платформа=[
        app_commands.Choice(name="twitch",  value="twitch"),
        app_commands.Choice(name="youtube", value="youtube"),
    ])
    @app_commands.command(name="додати_стрімера", description="Додати стрімера Twitch/YouTube")
    async def add_streamer(
        self,
        interaction: discord.Interaction,
        платформа: app_commands.Choice[str],
        посилання: str,
        користувач: discord.User,
    ):
        await interaction.response.defer(ephemeral=True)
        plat     = платформа.value
        username = self.extract_username(plat, посилання)

        if not username:
            await interaction.followup.send("❌ Не вдалося визначити ідентифікатор", ephemeral=True)
            return

        self.streamers = _load_streamers()
        for s in self.streamers:
            if s.get("platform") == plat and s.get("username") == username and s.get("discord_id") == користувач.id:
                await interaction.followup.send("⚠️ Цей стрімер уже доданий.", ephemeral=True)
                return

        item: dict = {"platform": plat, "username": username, "discord_id": користувач.id}

        # Для YouTube одразу резолвимо channel_id
        if plat == "youtube":
            async with aiohttp.ClientSession() as session:
                ch_id = await self._yt_resolve_channel_id(session, username)
            if ch_id:
                item["yt_channel_id"] = ch_id
                print(f"[STREAM] YouTube channel_id resolved: {username} → {ch_id}")
            else:
                print(f"[STREAM] WARNING: Could not resolve YouTube channel_id for {username}")

        self.streamers.append(item)
        _save_streamers(self.streamers)

        await interaction.followup.send(
            f"✅ Додано: **{username}** ({користувач.mention}) на **{plat}**",
            ephemeral=True,
        )

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.describe(платформа="Платформа", нік="Нік стрімера")
    @app_commands.choices(платформа=[
        app_commands.Choice(name="twitch",  value="twitch"),
        app_commands.Choice(name="youtube", value="youtube"),
    ])
    @app_commands.command(name="видалити_стрімера", description="Видалити стрімера")
    async def remove_streamer(
        self,
        interaction: discord.Interaction,
        платформа: app_commands.Choice[str],
        нік: str,
    ):
        self.streamers = _load_streamers()
        before = len(self.streamers)
        self.streamers = [
            s for s in self.streamers
            if not (s.get("platform") == платформа.value and s.get("username") == нік)
        ]
        if len(self.streamers) < before:
            _save_streamers(self.streamers)
            await interaction.response.send_message(f"✅ Стрімера **{нік}** видалено.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Стрімера **{нік}** не знайдено.", ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.command(name="список_стрімерів", description="Показати всіх стрімерів")
    async def list_streamers(self, interaction: discord.Interaction):
        self.streamers = _load_streamers()
        if not self.streamers:
            await interaction.response.send_message("ℹ️ Стрімерів немає.", ephemeral=True)
            return
        lines = []
        for s in self.streamers:
            ch_id = f" `({s.get('yt_channel_id', '—')})`" if s.get("platform") == "youtube" else ""
            lines.append(f"**{s['platform']}** — `{s['username']}`{ch_id} — <@{s['discord_id']}>")
        embed = discord.Embed(title="📋 Стрімери", description="\n".join(lines), color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.describe(гра="Назва гри", іконка_url="URL іконки")
    @app_commands.command(name="гра_іконка", description="Додати/оновити іконку для гри")
    async def set_game_icon(self, interaction: discord.Interaction, гра: str, іконка_url: str):
        self.game_icons = _load_game_icons()
        self.game_icons[гра.strip().lower()] = іконка_url.strip()
        _save_game_icons(self.game_icons)
        await interaction.response.send_message(f"✅ Іконку для **{гра}** збережено.", ephemeral=True)

    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.describe(
        канал="Канал для тестового ембеду",
        платформа="Платформа",
        тип="live чи відео",
        стрімер="Кого тегнути",
    )
    @app_commands.choices(
        платформа=[
            app_commands.Choice(name="twitch",  value="twitch"),
            app_commands.Choice(name="youtube", value="youtube"),
        ],
        тип=[
            app_commands.Choice(name="live",   value="live"),
            app_commands.Choice(name="відео",  value="video"),
        ],
    )
    @app_commands.command(name="тест_стрім", description="Надіслати тестовий ембед")
    async def test_stream(
        self,
        interaction: discord.Interaction,
        канал: discord.TextChannel,
        платформа: app_commands.Choice[str],
        тип: app_commands.Choice[str],
        стрімер: Optional[discord.Member] = None,
    ):
        plat  = платформа.value
        mode  = тип.value
        color = random.choice(STREAM_COLORS)
        _, plat_emoji = self.platform_assets(plat)
        plat_name     = "Twitch" if plat == "twitch" else "YouTube"

        test_url = "https://www.twitch.tv/twitch" if plat == "twitch" else "https://youtu.be/dQw4w9WgXcQ"
        preview  = (
            "https://static-cdn.jtvnw.net/ttv-static/404_preview-640x360.jpg"
            if plat == "twitch"
            else "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg"
        )

        title     = f"Rick Astley - Never Gonna Give You Up ({'LIVE' if mode == 'live' else 'ВІДЕО'})"
        now_utc   = datetime.now(timezone.utc)
        embed     = discord.Embed(title="Стрімери 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲", color=color)
        parts     = [
            f"**{self._discord_ts(now_utc)}**",
            f"{plat_emoji} {plat_name} • [**{title}**]({test_url})",
        ]
        if mode == "live":
            parts += [f"{GAME_EMOJI or '🎮'} Black Desert", "**Зараз дивляться:** 123"]
        embed.description = "\n\n".join(parts)
        embed.set_footer(
            text="Silent Concierge by Myxa | Спостерігаю останнім оком",
            icon_url=self.bot.user.display_avatar.url,
        )

        av_member  = стрімер or interaction.user
        avatar_url = (
            av_member.display_avatar.replace(size=128, format="png").url
            if hasattr(av_member.display_avatar, "replace")
            else av_member.display_avatar.url
        )

        async with aiohttp.ClientSession() as session:
            files, ekw = await self._build_embed_files(session, avatar_url, plat, preview)

        if "thumbnail" in ekw:
            embed.set_thumbnail(url=ekw["thumbnail"])
        if "image" in ekw:
            embed.set_image(url=ekw["image"])

        content = (
            f"Нове відео на каналі {av_member.mention} - дивись [тут]({test_url})!"
            if mode == "video"
            else random.choice(ANNOUNCE_LINES).format(mention=av_member.mention, url=test_url)
        )

        await канал.send(content=content, embed=embed, files=files)
        await interaction.response.send_message(f"✅ Надіслано у {канал.mention}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StreamCog(bot))
    print("[COG] StreamCog завантажено")
