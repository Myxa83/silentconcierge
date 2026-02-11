# -*- coding: utf-8 -*-
import json
import traceback
import discord
from pathlib import Path
from datetime import datetime
from typing import List
from discord import app_commands
from discord.ext import commands

# ========================= CONFIG =========================
ROLE_ALLOWED = [
    1375070910138028044,  # Leader
    1425974196181270671,  # Officer
    1323454517664157736,  # Moderator
]

LOG_DIR = Path("logs")
SYNC_LOG_FILE = LOG_DIR / "sync_logs.json"

# ========================= HELPERS =========================
def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def _append_sync_log(action: str, user: str, guild: str, status: str, details: str) -> None:
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
        data = []
        if SYNC_LOG_FILE.exists():
            try:
                data = json.loads(SYNC_LOG_FILE.read_text(encoding="utf-8"))
            except:
                data = []
        data.append(entry)
        SYNC_LOG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except:
        pass

def has_sync_perms(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    return any(r.id in ROLE_ALLOWED for r in interaction.user.roles)

# ========================= COG =========================
class SyncCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[COG][OK] SyncCog loaded")

    async def _perform_sync(self, interaction: discord.Interaction, mode: str):
        """Універсальна логіка синхронізації з логами"""
        await interaction.response.defer(ephemeral=True)
        
        if not has_sync_perms(interaction):
            await interaction.followup.send("⛔ Недостатньо прав!", ephemeral=True)
            _append_sync_log("Sync Attempt", str(interaction.user), str(interaction.guild), "Denied", "No roles")
            return

        try:
            if mode == "guild":
                synced = await self.bot.tree.sync(guild=interaction.guild)
                msg = f"✅ Синхронізовано для цієї гільдії: **{len(synced)}** команд."
            elif mode == "global":
                synced = await self.bot.tree.sync()
                msg = f"🌍 Глобальна синхронізація успішна: **{len(synced)}** команд."
            else:
                # Очистити команди гільдії та скопіювати глобальні (найкращий метод для виправлення багів)
                self.bot.tree.copy_global_to(guild=interaction.guild)
                synced = await self.bot.tree.sync(guild=interaction.guild)
                msg = f"🔄 Команди скопійовано та синхронізовано: **{len(synced)}**"

            print(f"[SYNC][{mode.upper()}] Спровоковано {interaction.user}: {len(synced)} команд")
            await interaction.followup.send(msg, ephemeral=True)
            _append_sync_log(f"{mode.capitalize()} Sync", str(interaction.user), str(interaction.guild), "Success", f"{len(synced)} cmds")

        except Exception as e:
            error_msg = f"❌ Помилка: {type(e).__name__}"
            print(f"[SYNC][ERR] {traceback.format_exc()}")
            await interaction.followup.send(error_msg, ephemeral=True)
            _append_sync_log("Sync Error", str(interaction.user), str(interaction.guild), "Fail", str(e))

    @app_commands.command(name="sync_local", description="Синхронізувати команди ТІЛЬКИ для цього сервера")
    async def sync_local(self, interaction: discord.Interaction):
        await self._perform_sync(interaction, "guild")

    @app_commands.command(name="sync_global", description="Синхронізувати команди ГЛОБАЛЬНО (всі сервери)")
    async def sync_global(self, interaction: discord.Interaction):
        await self._perform_sync(interaction, "global")

    @app_commands.command(name="sync_fix", description="Примусово скопіювати глобальні команди на цей сервер")
    async def sync_fix(self, interaction: discord.Interaction):
        await self._perform_sync(interaction, "fix")

async def setup(bot: commands.Bot):
    await bot.add_cog(SyncCog(bot))
