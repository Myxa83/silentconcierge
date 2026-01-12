# -*- coding: utf-8 -*-
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import commands


ROLE_ALLOWED = [
    1375070910138028044,  # Leader
    1425974196181270671,  # Officer
    1323454517664157736,  # Moderator
]

LOG_DIR = Path("logs")
SYNC_LOG_FILE = LOG_DIR / "sync_logs.json"


def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _safe_name(obj) -> str:
    try:
        return str(obj)
    except Exception:
        return "<unknown>"


def _append_sync_log(action: str, user: str, guild: str, status: str, details: str) -> None:
    """
    Append запис у logs/sync_logs.json.
    Формат сумісний з твоїм старим файлом.
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "time": _utc_now(),
            "action": action,
            "user": user,
            "guild": guild,
            "status": status,
            "details": details,
        }

        data: List[dict] = []
        if SYNC_LOG_FILE.exists():
            try:
                data = json.loads(SYNC_LOG_FILE.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []

        data.append(entry)
        SYNC_LOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # логер не має валити бота
        pass


def _has_access(member: discord.Member) -> bool:
    return any(r.id in ROLE_ALLOWED for r in getattr(member, "roles", []))


async def _defer_ephemeral(interaction: discord.Interaction) -> None:
    """
    Defer тільки якщо ще не ack.
    """
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
    except Exception:
        pass


async def _reply_ephemeral(interaction: discord.Interaction, content: str) -> None:
    """
    Відповісти без double-ack: якщо response вже зроблено, то followup, інакше response.
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)
    except Exception:
        # якщо interaction вже протух, ми хоча б залогуємо вище
        pass


class SyncCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[COG][OK] Loaded cogs.sync_cog")

    async def _sync_guild(self, guild: discord.Guild) -> int:
        synced = await self.bot.tree.sync(guild=guild)
        return len(synced)

    async def _sync_global(self) -> int:
        synced = await self.bot.tree.sync()
        return len(synced)

    def _user_str(self, interaction: discord.Interaction) -> str:
        u = interaction.user
        return f"{_safe_name(u)} ({getattr(u, 'id', None)})"

    def _guild_str(self, interaction: discord.Interaction) -> str:
        g = interaction.guild
        if g is None:
            return "Global"
        return f"{_safe_name(g)} ({getattr(g, 'id', None)})"

    async def _run_sync(
        self,
        interaction: discord.Interaction,
        mode: str,
        *,
        force_global: bool = False
    ) -> None:
        await _defer_ephemeral(interaction)

        # perms
        if not isinstance(interaction.user, discord.Member) or not _has_access(interaction.user):
            await _reply_ephemeral(interaction, "⛔ У вас немає прав для синхронізації команд.")
            _append_sync_log(
                action=f"{mode} Sync",
                user=self._user_str(interaction),
                guild=self._guild_str(interaction),
                status="Denied",
                details="No allowed role",
            )
            return

        try:
            if force_global:
                count = await self._sync_global()
                action = "Full Global Sync"
                guild_name = "Global"
            else:
                if interaction.guild is None:
                    # якщо команду викликали не в гільдії, робимо глобальний sync
                    count = await self._sync_global()
                    action = "Full Global Sync"
                    guild_name = "Global"
                else:
                    count = await self._sync_guild(interaction.guild)
                    action = "Guild Sync"
                    guild_name = self._guild_str(interaction)

            await _reply_ephemeral(interaction, f"✅ Sync успішний. Синхронізовано команд: {count}")
            _append_sync_log(
                action=action,
                user=self._user_str(interaction),
                guild=guild_name,
                status="Success",
                details=f"{count} commands synced",
            )

        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            # коротко в консоль
            print(f"[SYNC][ERR] {type(e).__name__}: {e}")
            # повністю в файл
            _append_sync_log(
                action="Sync Error",
                user=self._user_str(interaction),
                guild=self._guild_str(interaction),
                status="Error",
                details=f"{type(e).__name__}: {e}\n{tb}",
            )
            await _reply_ephemeral(interaction, f"❌ Sync впав: `{type(e).__name__}: {e}`")

    # Команда 1: універсальна
    @app_commands.command(name="sync", description="Синхронізувати slash-команди (в гільдії або глобально)")
    async def sync_cmd(self, interaction: discord.Interaction):
        await self._run_sync(interaction, "Auto", force_global=False)

    # Команда 2: тільки локально для поточної гільдії
    @app_commands.command(name="synclocal", description="Синхронізувати команди тільки для цієї гільдії")
    async def synclocal_cmd(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await _defer_ephemeral(interaction)
            await _reply_ephemeral(interaction, "❌ synclocal можна запускати тільки на сервері (не в DM).")
            return
        await self._run_sync(interaction, "Local", force_global=False)

    # Команда 3: глобально
    @app_commands.command(name="syncall", description="Глобальна синхронізація команд (може зайняти час)")
    async def syncall_cmd(self, interaction: discord.Interaction):
        await self._run_sync(interaction, "Global", force_global=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SyncCog(bot))
