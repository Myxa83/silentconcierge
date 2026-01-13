# -*- coding: utf-8 -*-
import os
import json
import random
import datetime
import aiohttp
import discord
from discord.ext import commands, tasks
from discord import app_commands


# Працюємо тільки на цьому сервері
ALLOWED_GUILD_ID = 1323454227816906802

# Ротація кожні 15 хв
ROTATE_EVERY_SECONDS = 15 * 60

# Твій пул банерів (raw)
BANNER_URLS = [
    "https://github.com/Myxa83/silentconcierge/raw/main/assets/backgrounds/GeForceNOW_4dqx8ncOfU.jpg",
    "https://github.com/Myxa83/silentconcierge/raw/main/assets/backgrounds/GeForceNOW_V0iuHfoWFi.jpg",
    "https://github.com/Myxa83/silentconcierge/raw/main/assets/backgrounds/GeForceNOW_Ng549cw9KG.png",
    "https://github.com/Myxa83/silentconcierge/raw/main/assets/backgrounds/2023-06-14_1216243605.png",
    "https://github.com/Myxa83/silentconcierge/raw/main/assets/backgrounds/T5G35LTPL6Q3SFFL20250731083005811.400x225.jpg",
    "https://github.com/Myxa83/silentconcierge/raw/main/assets/backgrounds/afee581382c20251211210736366.jpg",
]


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _log_json(event: dict) -> None:
    _ensure_dir("logs")
    day = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    fp = os.path.join("logs", f"banner_changes_{day}.json")

    try:
        if os.path.exists(fp):
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = []
        else:
            data = []

        data.append(event)

        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        # Ніякого спаму в консоль, як ти любиш
        pass


async def _download_bytes(url: str) -> bytes:
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            return await resp.read()


class ServerBannerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_url: str | None = None
        self._busy = False
        self.banner_rotate_loop.start()

    def cog_unload(self):
        self.banner_rotate_loop.cancel()

    def _allowed_guild(self, guild: discord.Guild | None) -> bool:
        return guild is not None and guild.id == ALLOWED_GUILD_ID

    async def _set_banner_from_url(self, guild: discord.Guild, url: str, reason: str, actor: str):
        t0 = datetime.datetime.utcnow().isoformat() + "Z"
        event = {
            "ts_utc": t0,
            "guild_id": guild.id,
            "action": "set_banner",
            "url": url,
            "reason": reason,
            "actor": actor,
            "ok": False,
            "error": None,
        }

        try:
            data = await _download_bytes(url)
            await guild.edit(banner=data, reason=reason)
            event["ok"] = True
            self._last_url = url
        except Exception as e:
            event["error"] = f"{type(e).__name__}: {e}"

        _log_json(event)
        return event

    @tasks.loop(seconds=ROTATE_EVERY_SECONDS)
    async def banner_rotate_loop(self):
        # Не стартуємо поки бот не готовий
        if not self.bot.is_ready():
            return

        guild = self.bot.get_guild(ALLOWED_GUILD_ID)
        if guild is None:
            return

        # Захист від паралельних запусків
        if self._busy:
            return
        self._busy = True
        try:
            # Вибираємо URL, бажано не той самий що був
            urls = list(BANNER_URLS)
            if self._last_url in urls and len(urls) > 1:
                urls.remove(self._last_url)

            url = random.choice(urls)
            await self._set_banner_from_url(
                guild=guild,
                url=url,
                reason="Auto banner rotation (15 min)",
                actor="auto_loop",
            )
        finally:
            self._busy = False

    @banner_rotate_loop.before_loop
    async def before_banner_rotate_loop(self):
        await self.bot.wait_until_ready()

    banner_group = app_commands.Group(
        name="banner",
        description="Керування банером сервера (верхня картинка).",
    )

    @banner_group.command(name="rotate", description="Одразу провернути банер (вручну).")
    async def banner_rotate_now(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self._allowed_guild(interaction.guild):
            return await interaction.followup.send("Ця команда доступна тільки на основному сервері.", ephemeral=True)

        # Доступ: або власник сервера, або людина з Manage Server
        member = interaction.user
        if isinstance(member, discord.Member):
            is_owner = (interaction.guild is not None and member.id == interaction.guild.owner_id)
            has_manage = member.guild_permissions.manage_guild
            if not (is_owner or has_manage):
                return await interaction.followup.send("Нема доступу. Потрібно Manage Server.", ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("Це працює тільки на сервері.", ephemeral=True)

        urls = list(BANNER_URLS)
        if self._last_url in urls and len(urls) > 1:
            urls.remove(self._last_url)
        url = random.choice(urls)

        event = await self._set_banner_from_url(
            guild=guild,
            url=url,
            reason=f"Manual rotate by {interaction.user}",
            actor=str(interaction.user),
        )

        if event["ok"]:
            await interaction.followup.send("Готово. Банер оновлено.", ephemeral=True)
        else:
            await interaction.followup.send(f"Не вийшло: {event['error']}", ephemeral=True)

    @banner_group.command(name="set", description="Встановити банер з URL (PNG/JPG/GIF).")
    @app_commands.describe(url="Пряме посилання на картинку. Для GitHub треба raw.")
    async def banner_set(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=True)

        if not self._allowed_guild(interaction.guild):
            return await interaction.followup.send("Ця команда доступна тільки на основному сервері.", ephemeral=True)

        member = interaction.user
        if isinstance(member, discord.Member):
            is_owner = (interaction.guild is not None and member.id == interaction.guild.owner_id)
            has_manage = member.guild_permissions.manage_guild
            if not (is_owner or has_manage):
                return await interaction.followup.send("Нема доступу. Потрібно Manage Server.", ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("Це працює тільки на сервері.", ephemeral=True)

        event = await self._set_banner_from_url(
            guild=guild,
            url=url,
            reason=f"Manual set by {interaction.user}",
            actor=str(interaction.user),
        )

        if event["ok"]:
            await interaction.followup.send("Готово. Банер встановлено.", ephemeral=True)
        else:
            await interaction.followup.send(f"Не вийшло: {event['error']}", ephemeral=True)

    @banner_group.command(name="clear", description="Прибрати банер сервера.")
    async def banner_clear(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self._allowed_guild(interaction.guild):
            return await interaction.followup.send("Ця команда доступна тільки на основному сервері.", ephemeral=True)

        member = interaction.user
        if isinstance(member, discord.Member):
            is_owner = (interaction.guild is not None and member.id == interaction.guild.owner_id)
            has_manage = member.guild_permissions.manage_guild
            if not (is_owner or has_manage):
                return await interaction.followup.send("Нема доступу. Потрібно Manage Server.", ephemeral=True)

        guild = interaction.guild
        if guild is None:
            return await interaction.followup.send("Це працює тільки на сервері.", ephemeral=True)

        t0 = datetime.datetime.utcnow().isoformat() + "Z"
        event = {
            "ts_utc": t0,
            "guild_id": guild.id,
            "action": "clear_banner",
            "reason": f"Manual clear by {interaction.user}",
            "actor": str(interaction.user),
            "ok": False,
            "error": None,
        }

        try:
            await guild.edit(banner=None, reason=f"Manual clear by {interaction.user}")
            event["ok"] = True
            self._last_url = None
        except Exception as e:
            event["error"] = f"{type(e).__name__}: {e}"

        _log_json(event)

        if event["ok"]:
            await interaction.followup.send("Банер прибрано.", ephemeral=True)
        else:
            await interaction.followup.send(f"Не вийшло: {event['error']}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerBannerCog(bot))
