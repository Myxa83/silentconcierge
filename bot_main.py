# -*- coding: utf-8 -*-
# bot_main.py

import asyncio
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from config.loader import DISCORD_TOKEN, GUILD_ID


INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.voice_states = True

# Коги, команди яких синкуються ГЛОБАЛЬНО (для продажу іншим серверам)
GLOBAL_COGS = {"bbf_cog_eng"}

LOG_DIR = Path("logs")
RUNTIME_LOG = LOG_DIR / "runtime_logs.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _append_runtime_log(entry: dict) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        data = []
        if RUNTIME_LOG.exists():
            try:
                data = json.loads(RUNTIME_LOG.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []
        data.append(entry)
        RUNTIME_LOG.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _get_global_cmd_names(bot: commands.Bot) -> set[str]:
    """Повертає імена команд з когів, що синкуються глобально."""
    names: set[str] = set()
    for cog_name in GLOBAL_COGS:
        for cog in bot.cogs.values():
            if cog.__module__ == f"cogs.{cog_name}":
                for cmd in cog.get_app_commands():
                    names.add(cmd.name)
    return names


async def _do_sync(bot: commands.Bot) -> dict:
    """
    Виконує синхронізацію команд:
      - Guild (основний сервер): всі команди КРІМ глобальних (eng-BBF)
      - Global: тільки eng-BBF команди

    Повертає словник з результатами для логування/виводу.
    """
    gid = getattr(bot, "home_guild_id", None)
    global_cmd_names = _get_global_cmd_names(bot)
    print(f"[SYNC] Eng-команди (global): {global_cmd_names}")

    result = {
        "guild_id": gid,
        "guild_count": 0,
        "guild_commands": [],
        "global_count": 0,
        "global_commands": [],
    }

    # ── 1. Guild sync ─────────────────────────────────────────────────────────
    # Копіюємо всі команди на guild, потім прибираємо eng-команди
    if gid:
        guild_obj = discord.Object(id=gid)
        bot.tree.copy_global_to(guild=guild_obj)

        for cmd_name in global_cmd_names:
            bot.tree.remove_command(cmd_name, guild=guild_obj)

        guild_synced = await bot.tree.sync(guild=guild_obj)
        result["guild_count"] = len(guild_synced)
        result["guild_commands"] = [c.name for c in guild_synced]
        print(f"[SYNC] Guild ({gid}): {len(guild_synced)} команд — {result['guild_commands']}")

        _append_runtime_log({
            "time": _utc_now(), "event": "sync", "mode": "guild",
            "guild_id": gid, "count": len(guild_synced),
            "commands": result["guild_commands"],
        })

    # ── 2. Global sync ────────────────────────────────────────────────────────
    # Тимчасово прибираємо з дерева всі НЕ-eng команди, синкуємо, повертаємо назад
    all_cmds = list(bot.tree.get_commands())
    temporarily_removed = []

    for cmd in all_cmds:
        if cmd.name not in global_cmd_names:
            bot.tree.remove_command(cmd.name)
            temporarily_removed.append(cmd)

    global_synced = await bot.tree.sync()
    result["global_count"] = len(global_synced)
    result["global_commands"] = [c.name for c in global_synced]
    print(f"[SYNC] Global: {len(global_synced)} команд — {result['global_commands']}")

    # Повертаємо команди назад у дерево
    for cmd in temporarily_removed:
        bot.tree.add_command(cmd)

    _append_runtime_log({
        "time": _utc_now(), "event": "sync", "mode": "global",
        "count": len(global_synced),
        "commands": result["global_commands"],
    })

    return result


class SilentBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=INTENTS,
            help_command=None,
        )
        self.home_guild_id: int | None = None

    async def setup_hook(self) -> None:
        print("[BOOT] bot_main.py started")
        print("[BOOT] CWD:", os.getcwd())

        # Визначаємо home guild
        try:
            gid_val = int(GUILD_ID)
            self.home_guild_id = gid_val if gid_val != 0 else None
        except Exception:
            self.home_guild_id = None
        print(f"[BOOT] home_guild_id = {self.home_guild_id}")

        # Діагностика файлів
        try:
            print("[BOOT] ROOT FILES:", sorted(os.listdir(".")))
        except Exception as e:
            print(f"[BOOT] ROOT FILES ERROR: {e}")

        if os.path.isdir("cogs"):
            try:
                print("[BOOT] COGS FILES:", sorted(os.listdir("cogs")))
            except Exception as e:
                print(f"[BOOT][WARN] cannot list cogs/: {e}")
        else:
            print("[BOOT][WARN] cogs/ directory NOT FOUND")

        # Завантажуємо коги
        loaded_ext, failed_ext = [], []

        if os.path.isdir("cogs"):
            for file in sorted(os.listdir("cogs")):
                if not file.endswith(".py") or file.startswith("_"):
                    continue
                ext = f"cogs.{file[:-3]}"
                try:
                    await self.load_extension(ext)
                    print(f"[COG][OK] {ext}")
                    loaded_ext.append(ext)
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    print(f"[COG][FAIL] {ext}: {msg}")
                    traceback.print_exc()
                    failed_ext.append({"ext": ext, "error": msg, "traceback": traceback.format_exc()})

        print(f"[BOOT] COG RESULT: ok={len(loaded_ext)}, fail={len(failed_ext)}")
        _append_runtime_log({
            "time": _utc_now(), "event": "cogs_loaded",
            "cwd": os.getcwd(), "loaded": loaded_ext, "failed": failed_ext,
        })

        # Синхронізуємо команди
        await _do_sync(self)
        self.tree.on_error = self.on_app_command_error

    async def on_ready(self) -> None:
        print(f"[READY] {self.user} ({self.user.id})")
        _append_runtime_log({
            "time": _utc_now(), "event": "ready",
            "user_id": getattr(self.user, "id", None),
        })

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        real_error = getattr(error, "original", error)
        err_type = type(real_error).__name__
        err_text = str(real_error) or str(error) or "Unknown error"
        tb = "".join(traceback.format_exception(type(real_error), real_error, real_error.__traceback__))

        cmd_name = None
        try:
            if interaction.command:
                cmd_name = interaction.command.qualified_name
        except Exception:
            pass

        print(
            f"[APP_CMD_ERROR] cmd={cmd_name} "
            f"user={getattr(interaction.user, 'id', None)} "
            f"guild={getattr(interaction.guild, 'id', None)} "
            f"error={err_type}: {err_text}"
        )
        print(tb)

        _append_runtime_log({
            "time": _utc_now(), "event": "app_cmd_error",
            "cmd": cmd_name,
            "user_id": getattr(interaction.user, "id", None),
            "guild_id": getattr(interaction.guild, "id", None),
            "error_type": err_type, "error": err_text, "traceback": tb,
        })

        msg = f"Помилка: `{err_type}`\n```txt\n{err_text[:1500]}\n```"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass


bot = SilentBot()


@bot.command(name="force_sync")
@commands.is_owner()
async def force_sync(ctx: commands.Context) -> None:
    """Примусова синхронізація команд (тільки для власника бота)."""
    msg = await ctx.send("⏳ Починаю синхронізацію команд...")
    try:
        result = await _do_sync(bot)

        _append_runtime_log({
            "time": _utc_now(), "event": "force_sync",
            "author_id": ctx.author.id,
            "guild_count": result["guild_count"],
            "global_count": result["global_count"],
        })

        await msg.edit(content=(
            f"✅ Guild `{result['guild_id']}`: **{result['guild_count']}** команд.\n"
            f"🌍 Global: **{result['global_count']}** команд.\n"
            "Перезавантаж Discord через `Ctrl+R`."
        ))

    except Exception as e:
        await msg.edit(content=f"❌ Помилка: `{type(e).__name__}: {e}`")
        traceback.print_exc()


async def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing")
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
