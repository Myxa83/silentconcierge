# -*- coding: utf-8 -*-
# cogs/music_cog.py

import asyncio
import json
import re
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import discord
from discord.ext import commands
from discord import app_commands

import yt_dlp

TEAL = 0x05B2B4

AUTO_LEAVE_SECONDS = 15 * 60

PLAYLISTS_PATH = Path("data/music_playlists.json")

MUSIC_GIFS = [
    "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/music/muz01.gif",
    "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/music/muz02.gif",
    "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/music/muz03.gif",
    "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/music/muz04.gif",
    "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/music/muz05.gif",
    "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/music/muz08.gif",
    "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/music/muz09.gif",
    "https://raw.githubusercontent.com/Myxa83/silentconcierge/main/assets/music/muz10.gif",
]

YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": False,
    "ignoreerrors": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch",
    "extract_flat": False,
    "source_address": "0.0.0.0",
}

FFMPEG_BEFORE_OPTS = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
FFMPEG_OPTS = "-vn -af loudnorm=I=-16:LRA=11:TP=-1.5"

ytdl = yt_dlp.YoutubeDL(YTDL_OPTS)

URL_RE = re.compile(r"(https?://\S+)", re.IGNORECASE)


@dataclass
class Track:
    title: str
    webpage_url: str
    stream_url: str
    duration: Optional[int] = None
    thumbnail: Optional[str] = None
    requester_id: Optional[int] = None
    source: str = "Unknown"


def _ensure_playlists_file() -> None:
    PLAYLISTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not PLAYLISTS_PATH.exists():
        PLAYLISTS_PATH.write_text(
            json.dumps({"users": {}}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )


def _load_playlists() -> Dict[str, Any]:
    _ensure_playlists_file()
    try:
        return json.loads(PLAYLISTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"users": {}}


def _save_playlists(data: Dict[str, Any]) -> None:
    _ensure_playlists_file()
    PLAYLISTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt_dur(sec: Optional[int]) -> str:
    if not sec:
        return ""
    sec = int(sec)
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def pick_music_gif(track_url: str) -> str:
    if not MUSIC_GIFS:
        return ""
    h = hashlib.md5(track_url.encode("utf-8", errors="ignore")).hexdigest()
    idx = int(h[:8], 16) % len(MUSIC_GIFS)
    return MUSIC_GIFS[idx]


def detect_link_type(url: str) -> Optional[str]:
    u = (url or "").lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "soundcloud.com" in u:
        return "soundcloud"
    return None


def extract_urls(text: str) -> List[str]:
    if not text:
        return []
    return [m.group(1).strip().rstrip(")") for m in URL_RE.finditer(text)]


async def ytdl_extract(url_or_query: str) -> Tuple[List[Track], bool, str]:
    loop = asyncio.get_running_loop()

    def _extract():
        return ytdl.extract_info(url_or_query, download=False)

    info = await loop.run_in_executor(None, _extract)

    def detect_source(webpage: str) -> str:
        w = (webpage or "").lower()
        if "soundcloud.com" in w:
            return "SoundCloud"
        if "youtube.com" in w or "youtu.be" in w:
            return "YouTube"
        return "Search"

    tracks: List[Track] = []
    is_playlist = False

    if isinstance(info, dict) and "entries" in info and isinstance(info["entries"], list):
        is_playlist = True
        for entry in info["entries"]:
            if not entry:
                continue

            stream_url = entry.get("url")
            webpage = entry.get("webpage_url") or entry.get("original_url") or url_or_query

            if entry.get("_type") in ("url", "url_transparent") and entry.get("url") and not entry.get("formats"):
                try:
                    def _resolve():
                        return ytdl.extract_info(entry["url"], download=False)
                    resolved = await loop.run_in_executor(None, _resolve)
                    entry = resolved
                    stream_url = entry.get("url")
                    webpage = entry.get("webpage_url") or entry.get("original_url") or url_or_query
                except Exception:
                    continue

            if not stream_url and entry.get("formats"):
                stream_url = entry["formats"][-1].get("url")

            if not stream_url:
                continue

            src_label = detect_source(webpage)
            tracks.append(
                Track(
                    title=entry.get("title", "Unknown title"),
                    webpage_url=webpage,
                    stream_url=stream_url,
                    duration=entry.get("duration"),
                    thumbnail=entry.get("thumbnail"),
                    source=src_label,
                )
            )

        src_label = detect_source(info.get("webpage_url") or url_or_query)
        return tracks, True, src_label

    if not isinstance(info, dict):
        return [], False, "Unknown"

    webpage = info.get("webpage_url") or info.get("original_url") or url_or_query
    stream_url = info.get("url")
    if not stream_url and info.get("formats"):
        stream_url = info["formats"][-1].get("url")

    if stream_url:
        src_label = detect_source(webpage)
        tracks.append(
            Track(
                title=info.get("title", "Unknown title"),
                webpage_url=webpage,
                stream_url=stream_url,
                duration=info.get("duration"),
                thumbnail=info.get("thumbnail"),
                source=src_label,
            )
        )

    return tracks, False, detect_source(webpage)


class GuildPlayer:
    def __init__(self):
        self.queue: asyncio.Queue[Track] = asyncio.Queue()
        self.current: Optional[Track] = None
        self.history: List[Track] = []
        self.volume: float = 0.8
        self.nowplaying_message_id: Optional[int] = None
        self.queue_page: int = 0
        self._task: Optional[asyncio.Task] = None

    def ensure_task(self, bot: commands.Bot, guild_id: int):
        if self._task is None or self._task.done():
            self._task = bot.loop.create_task(self._player_loop(bot, guild_id))

    async def _player_loop(self, bot: commands.Bot, guild_id: int):
        while True:
            track = await self.queue.get()
            self.current = track

            guild = bot.get_guild(guild_id)
            if not guild:
                self.current = None
                continue

            vc: Optional[discord.VoiceClient] = guild.voice_client
            if not vc or not vc.is_connected():
                self.current = None
                continue

            self.history.append(track)

            src = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(
                    track.stream_url,
                    before_options=FFMPEG_BEFORE_OPTS,
                    options=FFMPEG_OPTS,
                ),
                volume=self.volume,
            )

            done = asyncio.Event()

            def _after(_: Optional[Exception]):
                bot.loop.call_soon_threadsafe(done.set)

            vc.play(src, after=_after)

            cog = bot.get_cog("MusicCog")
            if cog:
                try:
                    await cog._post_or_update_nowplaying(guild)
                except Exception:
                    pass

            await done.wait()
            self.current = None

            await asyncio.sleep(0.3)
            if self.queue.empty():
                break


class QueueView(discord.ui.View):
    def __init__(self, cog: "MusicCog", guild_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild_id = guild_id

    @discord.ui.button(label="Назад", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        p = self.cog.get_player(self.guild_id)
        p.queue_page = max(0, p.queue_page - 1)
        embed = self.cog.build_queue_embed(interaction.guild, p)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Вперед", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, _: discord.ui.Button):
        p = self.cog.get_player(self.guild_id)
        p.queue_page += 1
        embed = self.cog.build_queue_embed(interaction.guild, p)
        await interaction.response.edit_message(embed=embed, view=self)


class NowPlayingView(discord.ui.View):
    def __init__(self, cog: "MusicCog", guild_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id

    def _player(self) -> GuildPlayer:
        return self.cog.get_player(self.guild_id)

    async def _vc(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        if not interaction.guild:
            return None
        return interaction.guild.voice_client

    @discord.ui.button(label="Назад", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        vc = await self._vc(interaction)
        p = self._player()
        if len(p.history) < 2:
            await interaction.response.send_message("Нема попереднього треку.", ephemeral=True)
            return

        _cur = p.history.pop()
        prev = p.history.pop()

        try:
            p.queue._queue.appendleft(prev)  # type: ignore[attr-defined]
        except Exception:
            items = list(p.queue._queue)
            p.queue._queue.clear()
            p.queue._queue.append(prev)
            for t in items:
                p.queue._queue.append(t)

        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

        await interaction.response.send_message("Ок.", ephemeral=True)

    @discord.ui.button(label="Пауза", style=discord.ButtonStyle.secondary)
    async def pause_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = await self._vc(interaction)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("Я не в voice.", ephemeral=True)
            return

        if vc.is_playing():
            vc.pause()
            button.label = "Продовжити"
        elif vc.is_paused():
            vc.resume()
            button.label = "Пауза"

        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Вперед", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        vc = await self._vc(interaction)
        if not vc or not vc.is_connected() or (not vc.is_playing() and not vc.is_paused()):
            await interaction.response.send_message("Нічого не грає.", ephemeral=True)
            return
        vc.stop()
        await interaction.response.send_message("Ок.", ephemeral=True)

    @discord.ui.button(label="Звук -", style=discord.ButtonStyle.secondary)
    async def vol_down(self, interaction: discord.Interaction, _: discord.ui.Button):
        p = self._player()
        p.volume = max(0.05, round(p.volume - 0.05, 2))
        vc = await self._vc(interaction)
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = p.volume
        await interaction.response.send_message(f"Гучність: {int(p.volume * 100)}%", ephemeral=True)

    @discord.ui.button(label="Стоп", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        vc = await self._vc(interaction)
        p = self._player()

        while not p.queue.empty():
            try:
                p.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        p.current = None
        if vc and vc.is_connected():
            vc.stop()
            await vc.disconnect()

        await interaction.response.send_message("Зупинено.", ephemeral=True)

    @discord.ui.button(label="Звук +", style=discord.ButtonStyle.secondary)
    async def vol_up(self, interaction: discord.Interaction, _: discord.ui.Button):
        p = self._player()
        p.volume = min(2.0, round(p.volume + 0.05, 2))
        vc = await self._vc(interaction)
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = p.volume
        await interaction.response.send_message(f"Гучність: {int(p.volume * 100)}%", ephemeral=True)

    @discord.ui.button(label="Черга", style=discord.ButtonStyle.primary)
    async def queue_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._send_queue(interaction, self.guild_id)


class MusicCog(commands.Cog, name="MusicCog"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.players: Dict[int, GuildPlayer] = {}
        self.autoleave_tasks: Dict[int, asyncio.Task] = {}
        _ensure_playlists_file()

    def get_player(self, guild_id: int) -> GuildPlayer:
        if guild_id not in self.players:
            self.players[guild_id] = GuildPlayer()
        return self.players[guild_id]

    def footer_kwargs(self) -> Dict[str, str]:
        user = self.bot.user
        icon = user.display_avatar.url if user else None
        text = user.name if user else "Music"
        return {"text": text, "icon_url": icon} if icon else {"text": text}

    async def ensure_voice(self, interaction: discord.Interaction) -> discord.VoiceClient:
        if not interaction.guild:
            raise app_commands.AppCommandError("Тільки на сервері.")

        member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if not member or not member.voice or not member.voice.channel:
            raise app_commands.AppCommandError("Зайди в voice канал.")

        vc = interaction.guild.voice_client
        if vc and vc.is_connected():
            return vc
        return await member.voice.channel.connect()

    def _humans_in_vc(self, vc: discord.VoiceClient) -> int:
        if not vc or not vc.channel:
            return 0
        return sum(1 for m in vc.channel.members if not m.bot)

    def _cancel_autoleave(self, guild_id: int):
        t = self.autoleave_tasks.get(guild_id)
        if t and not t.done():
            t.cancel()
        self.autoleave_tasks.pop(guild_id, None)

    def _schedule_autoleave(self, guild: discord.Guild):
        gid = guild.id
        self._cancel_autoleave(gid)
        self.autoleave_tasks[gid] = self.bot.loop.create_task(self._autoleave_worker(gid))

    async def _autoleave_worker(self, guild_id: int):
        await asyncio.sleep(AUTO_LEAVE_SECONDS)
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        vc = guild.voice_client
        if not vc or not vc.is_connected():
            return
        if self._humans_in_vc(vc) > 0:
            return

        player = self.players.get(guild_id)
        if player:
            while not player.queue.empty():
                try:
                    player.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            player.current = None

        try:
            vc.stop()
        except Exception:
            pass
        try:
            await vc.disconnect()
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        guild = member.guild
        vc = guild.voice_client
        if not vc or not vc.is_connected() or not vc.channel:
            self._cancel_autoleave(guild.id)
            return
        humans = self._humans_in_vc(vc)
        if humans == 0:
            self._schedule_autoleave(guild)
        else:
            self._cancel_autoleave(guild.id)

    def build_nowplaying_embed(self, guild: discord.Guild, player: GuildPlayer) -> discord.Embed:
        t = player.current
        if not t:
            e = discord.Embed(title="Зараз грає", description="Нічого не грає.", color=TEAL)
            e.set_footer(**self.footer_kwargs())
            return e

        dur = _fmt_dur(t.duration)
        vol = f"{int(player.volume * 100)}%"

        desc = f"[{t.title}]({t.webpage_url})"
        if dur:
            desc += f"\nТривалість: {dur}"
        desc += f"\nГучність: {vol}"
        desc += f"\nДжерело: {t.source}"

        e = discord.Embed(title="Зараз грає", description=desc, color=TEAL)
        if t.thumbnail:
            e.set_thumbnail(url=t.thumbnail)

        gif = pick_music_gif(t.webpage_url)
        if gif:
            e.set_image(url=gif)

        e.set_footer(**self.footer_kwargs())
        return e

    def build_queue_embed(self, guild: discord.Guild, player: GuildPlayer) -> discord.Embed:
        items = list(player.queue._queue)
        per_page = 10
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        if player.queue_page >= total_pages:
            player.queue_page = max(0, total_pages - 1)

        start = player.queue_page * per_page
        page_items = items[start:start + per_page]

        lines: List[str] = []
        if player.current:
            cur = player.current
            cur_d = _fmt_dur(cur.duration)
            lines.append("Зараз грає:")
            lines.append(f"{cur.title} {f'[{cur_d}]' if cur_d else ''}")
            lines.append("")

        if page_items:
            lines.append("У черзі:")
            for i, t in enumerate(page_items, start=start + 1):
                d = _fmt_dur(t.duration)
                lines.append(f"{i}. {t.title} {f'[{d}]' if d else ''}")
        else:
            lines.append("Черга порожня.")

        e = discord.Embed(description="\n".join(lines), color=TEAL)

        gif = ""
        if player.current:
            gif = pick_music_gif(player.current.webpage_url)
        elif MUSIC_GIFS:
            gif = MUSIC_GIFS[0]
        if gif:
            e.set_image(url=gif)

        footer_line = f"Сторінка: {player.queue_page + 1}/{total_pages} | Треків: {len(items)}"
        e.set_footer(text=footer_line, icon_url=self.bot.user.display_avatar.url if self.bot.user else None)
        return e

    async def _post_or_update_nowplaying(self, guild: discord.Guild):
        player = self.get_player(guild.id)
        embed = self.build_nowplaying_embed(guild, player)
        view = NowPlayingView(self, guild.id)

        if player.nowplaying_message_id:
            for ch in guild.text_channels:
                try:
                    msg = await ch.fetch_message(player.nowplaying_message_id)
                    await msg.edit(embed=embed, view=view)
                    return
                except Exception:
                    continue

        channel = guild.system_channel
        if not channel or not channel.permissions_for(guild.me).send_messages:
            channel = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
        if not channel:
            return

        msg = await channel.send(embed=embed, view=view)
        player.nowplaying_message_id = msg.id

    async def _send_queue(self, interaction: discord.Interaction, guild_id: int):
        if not interaction.guild:
            return
        player = self.get_player(guild_id)
        embed = self.build_queue_embed(interaction.guild, player)
        view = QueueView(self, guild_id)
        await interaction.response.send_message(embed=embed, view=view)

    async def _add_to_queue(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(thinking=True)

        vc = await self.ensure_voice(interaction)
        if self._humans_in_vc(vc) > 0:
            self._cancel_autoleave(interaction.guild_id)

        player = self.get_player(interaction.guild_id)

        try:
            tracks, _is_playlist, _src = await ytdl_extract(query)
        except yt_dlp.utils.DownloadError:
            await interaction.followup.send("Не вдалося додати. Посилання недоступне.", ephemeral=True)
            return
        except Exception:
            await interaction.followup.send("Не вдалося додати. Спробуй інше посилання.", ephemeral=True)
            return

        if not tracks:
            await interaction.followup.send("Нема доступних треків за цим запитом.", ephemeral=True)
            return

        for t in tracks:
            t.requester_id = interaction.user.id
            await player.queue.put(t)

        player.ensure_task(self.bot, interaction.guild_id)

        await interaction.followup.send("Додано.", ephemeral=True)

        if interaction.guild:
            await self._post_or_update_nowplaying(interaction.guild)

    def _get_user_playlists(self, user_id: int) -> Dict[str, Any]:
        data = _load_playlists()
        uid = str(user_id)
        data.setdefault("users", {})
        data["users"].setdefault(uid, {"playlists": {}})
        pls = data["users"][uid].get("playlists", {})
        if not isinstance(pls, dict):
            data["users"][uid]["playlists"] = {}
            pls = {}
        return pls

    def _save_user_playlists(self, user_id: int, playlists: Dict[str, Any]) -> None:
        data = _load_playlists()
        uid = str(user_id)
        data.setdefault("users", {})
        data["users"].setdefault(uid, {})
        data["users"][uid]["playlists"] = playlists
        _save_playlists(data)

    def _playlist_limit_ok(self, playlists: Dict[str, Any]) -> bool:
        return len(playlists.keys()) < 2

    # Commands: only 3
    class HraiMode(app_commands.Transform, str):
        pass

    @app_commands.command(name="hrai", description="Грай. Можна програвати, створювати плейлисти і додавати в них.")
    @app_commands.describe(
        query="Посилання або назва треку. Для плейлиста можна вставити кілька лінків через пробіл або новий рядок.",
        mode="Режим: play, pl_create, pl_add, pl_play",
        playlist="Назва плейлиста (для режимів плейлистів)"
    )
    @app_commands.choices(mode=[
        app_commands.Choice(name="play", value="play"),
        app_commands.Choice(name="pl_create", value="pl_create"),
        app_commands.Choice(name="pl_add", value="pl_add"),
        app_commands.Choice(name="pl_play", value="pl_play"),
    ])
    async def cmd_hrai(
        self,
        interaction: discord.Interaction,
        query: str,
        mode: app_commands.Choice[str],
        playlist: Optional[str] = None,
    ):
        m = mode.value

        # normal play
        if m == "play":
            await self._add_to_queue(interaction, query)
            return

        # playlist modes need name
        if not playlist or not playlist.strip():
            await interaction.response.send_message("Потрібна назва плейлиста.", ephemeral=True)
            return
        pl_name = playlist.strip()

        playlists = self._get_user_playlists(interaction.user.id)

        if m == "pl_play":
            if pl_name not in playlists:
                await interaction.response.send_message("Плейлист не знайдено.", ephemeral=True)
                return
            items = playlists[pl_name].get("items", [])
            if not items:
                await interaction.response.send_message("Плейлист порожній.", ephemeral=True)
                return

            # play each url (adds to queue)
            await interaction.response.defer(thinking=True)
            for u in items:
                # reuse internal add without deferring again
                try:
                    tracks, _ispl, _src = await ytdl_extract(u)
                except Exception:
                    continue
                if not tracks:
                    continue
                player = self.get_player(interaction.guild_id)
                for t in tracks:
                    t.requester_id = interaction.user.id
                    await player.queue.put(t)

            vc = await self.ensure_voice(interaction)
            if self._humans_in_vc(vc) > 0:
                self._cancel_autoleave(interaction.guild_id)
            self.get_player(interaction.guild_id).ensure_task(self.bot, interaction.guild_id)

            await interaction.followup.send("Плейлист додано в чергу.", ephemeral=True)
            if interaction.guild:
                await self._post_or_update_nowplaying(interaction.guild)
            return

        # create or add need urls
        urls = extract_urls(query)
        if not urls:
            await interaction.response.send_message("Не бачу посилань. Встав лінки YouTube або SoundCloud.", ephemeral=True)
            return

        # enforce type not mixed
        types = [detect_link_type(u) for u in urls]
        types = [t for t in types if t is not None]
        if len(types) != len(urls):
            await interaction.response.send_message("Дозволені тільки YouTube або SoundCloud посилання.", ephemeral=True)
            return

        only_type = types[0]
        if any(t != only_type for t in types):
            await interaction.response.send_message("Не можна змішувати YouTube і SoundCloud в одному плейлисті.", ephemeral=True)
            return

        # create
        if m == "pl_create":
            if pl_name in playlists:
                await interaction.response.send_message("Такий плейлист вже існує.", ephemeral=True)
                return
            if not self._playlist_limit_ok(playlists):
                await interaction.response.send_message("Ліміт: максимум 2 плейлисти на людину.", ephemeral=True)
                return

            playlists[pl_name] = {"type": only_type, "items": urls}
            self._save_user_playlists(interaction.user.id, playlists)
            await interaction.response.send_message(f"Створено плейлист '{pl_name}'. Тип: {only_type}. Треків: {len(urls)}", ephemeral=True)
            return

        # add
        if m == "pl_add":
            if pl_name not in playlists:
                await interaction.response.send_message("Плейлист не знайдено.", ephemeral=True)
                return
            pl = playlists[pl_name]
            pl_type = pl.get("type")
            if pl_type != only_type:
                await interaction.response.send_message("Тип плейлиста інший. Не можна змішувати джерела.", ephemeral=True)
                return

            pl.setdefault("items", [])
            pl["items"].extend(urls)
            playlists[pl_name] = pl
            self._save_user_playlists(interaction.user.id, playlists)
            await interaction.response.send_message(f"Додано в '{pl_name}': {len(urls)}", ephemeral=True)
            return

        await interaction.response.send_message("Невідомий режим.", ephemeral=True)

    @app_commands.command(name="cherha", description="Показати чергу.")
    async def cmd_cherha(self, interaction: discord.Interaction):
        await self._send_queue(interaction, interaction.guild_id)

    @app_commands.command(name="poshuk", description="Пошук: YouTube, SoundCloud або по твоїх плейлистах.")
    @app_commands.describe(
        text="Текст пошуку або частина назви плейлиста",
        where="Де шукати: yt, sc, playlists"
    )
    @app_commands.choices(where=[
        app_commands.Choice(name="yt", value="yt"),
        app_commands.Choice(name="sc", value="sc"),
        app_commands.Choice(name="playlists", value="playlists"),
    ])
    async def cmd_poshuk(
        self,
        interaction: discord.Interaction,
        text: str,
        where: app_commands.Choice[str],
    ):
        w = where.value

        if w == "playlists":
            playlists = self._get_user_playlists(interaction.user.id)
            if not playlists:
                await interaction.response.send_message("У тебе нема плейлистів.", ephemeral=True)
                return

            q = text.strip().lower()
            hits = []
            for name, meta in playlists.items():
                if q in name.lower():
                    hits.append(f"{name} (тип: {meta.get('type')}, треків: {len(meta.get('items', []))})")

            if not hits:
                await interaction.response.send_message("Збігів не знайдено.", ephemeral=True)
                return

            e = discord.Embed(title="Плейлисти", description="\n".join(hits[:25]), color=TEAL)
            e.set_footer(**self.footer_kwargs())
            await interaction.response.send_message(embed=e, ephemeral=True)
            return

        # yt or sc search, add first result to queue
        prefix = "ytsearch:" if w == "yt" else "scsearch:"
        await self._add_to_queue(interaction, f"{prefix}{text}")


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
