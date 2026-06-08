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

# Коги які синкуються ГЛОБАЛЬНО (для всіх серверів)
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

        # ── Визначаємо home guild ID ДО завантаження когів ──────────────────
        try:
            gid_val = int(GUILD_ID)
            self.home_guild_id = gid_val if gid_val != 0 else None
        except Exception:
            self.home_guild_id = None
        print(f"[BOOT] home_guild_id = {self.home_guild_id}")

        try:
            root_files = sorted(os.listdir("."))
        except Exception as e:
            root_files = [f"[ERR] {type(e).__name__}: {e}"]
        print("[BOOT] ROOT FILES:", root_files)

        if os.path.isdir("cogs"):
            try:
                cogs_files = sorted(os.listdir("cogs"))
                print("[BOOT] COGS FILES:", cogs_files)
            except Exception as e:
                print(f"[BOOT][WARN] cannot list cogs/: {type(e).__name__}: {e}")
        else:
            print("[BOOT][WARN] cogs/ directory NOT FOUND")

        loaded_ext = []
        failed_ext = []

        if os.path.isdir("cogs"):
            for file in sorted(os.listdir("cogs")):
                if not file.endswith(".py"):
                    continue
                if file.startswith("_") or file == "__init__.py":
                    continue

                ext = f"cogs.{file[:-3]}"
                try:
                    await self.load_extension(ext)
                    print(f"[COG][OK] Loaded {ext}")
                    loaded_ext.append(ext)
                except Exception as e:
                    msg = f"{type(e).__name__}: {e}"
                    print(f"[COG][FAIL] {ext}: {msg}")
                    traceback.print_exc()
                    failed_ext.append({"ext": ext, "error": msg, "traceback": traceback.format_exc()})

        print(f"[BOOT] COG LOAD RESULT: ok={len(loaded_ext)}, fail={len(failed_ext)}")

        _append_runtime_log({
            "time": _utc_now(),
            "event": "cogs_loaded",
            "cwd": os.getcwd(),
            "loaded": loaded_ext,
            "failed": failed_ext,
        })

        await self._sync_application_commands()
        self.tree.on_error = self.on_app_command_error

    async def _sync_application_commands(self) -> None:
        try:
            gid = self.home_guild_id

            # ── 1. Guild sync (тільки команди НЕ з глобальних когів) ─────────
            if gid:
                guild_obj = discord.Object(id=gid)

                # Збираємо імена команд з глобальних (eng) когів
                global_cmd_names: set[str] = set()
                for cog_name in GLOBAL_COGS:
                    for name, c in self.cogs.items():
                        if c.__module__ == f"cogs.{cog_name}":
                            for cmd in c.get_app_commands():
                                global_cmd_names.add(cmd.name)
                                # Видаляємо їх з guild-дерева щоб не потрапили у guild sync
                                try:
                                    self.tree.remove_command(cmd.name, guild=guild_obj)
                                    print(f"[SYNC] Removed eng cmd from guild tree: /{cmd.name}")
                                except Exception:
                                    pass

                print(f"[SYNC] Eng commands excluded from guild sync: {global_cmd_names}")

                synced = await self.tree.sync(guild=guild_obj)
                print(f"[SYNC] Guild sync: {gid}. Count: {len(synced)}")
                for command in synced:
                    print(f"  - /{command.name}")

                _append_runtime_log({
                    "time": _utc_now(), "event": "sync", "mode": "guild",
                    "guild_id": gid, "count": len(synced),
                    "commands": [c.name for c in synced],
                })

            # ── 2. Global sync (тільки команди з eng cog) ────────────────────
            global_tree_commands = []
            for cog_name in GLOBAL_COGS:
                for name, c in self.cogs.items():
                    if c.__module__ == f"cogs.{cog_name}":
                        for cmd in c.get_app_commands():
                            global_tree_commands.append(cmd)
                            print(f"[SYNC] Adding to global tree: /{cmd.name}")

            if global_tree_commands:
                # Очищаємо глобальне дерево від всього зайвого
                global_cmd_names_set = {cmd.name for cmd in global_tree_commands}
                for cmd in list(self.tree.get_commands()):
                    if cmd.name not in global_cmd_names_set:
                        try:
                            self.tree.remove_command(cmd.name)
                        except Exception:
                            pass

                # Додаємо eng команди в глобальне дерево
                for cmd in global_tree_commands:
                    try:
                        self.tree.add_command(cmd)
                    except Exception:
                        pass

                global_synced = await self.tree.sync()
                print(f"[SYNC] Global sync: Count: {len(global_synced)}")
                for command in global_synced:
                    print(f"  - /{command.name} (global)")

                _append_runtime_log({
                    "time": _utc_now(), "event": "sync", "mode": "global",
                    "count": len(global_synced),
                    "commands": [c.name for c in global_synced],
                })
            else:
                print("[SYNC] No global cogs found, skipping global sync")

        except Exception as e:
            print(f"[SYNC][FAIL] {type(e).__name__}: {e}")
            traceback.print_exc()
            _append_runtime_log({
                "time": _utc_now(), "event": "sync_fail",
                "error_type": type(e).__name__, "error": str(e),
                "traceback": traceback.format_exc(),
            })

    async def on_ready(self) -> None:
        print(f"[READY] Logged in as {self.user} ({self.user.id})")
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
    msg = await ctx.send("Починаю синхронізацію команд...")
    try:
        gid = bot.home_guild_id
        guild_count = 0

        if gid:
            guild_obj = discord.Object(id=gid)

            # Видаляємо eng команди з guild tree перед sync
            for cog_name in GLOBAL_COGS:
                for name, c in bot.cogs.items():
                    if c.__module__ == f"cogs.{cog_name}":
                        for cmd in c.get_app_commands():
                            try:
                                bot.tree.remove_command(cmd.name, guild=guild_obj)
                            except Exception:
                                pass

            synced = await bot.tree.sync(guild=guild_obj)
            guild_count = len(synced)

        global_synced = await bot.tree.sync()
        await msg.edit(content=(
            f"Guild `{gid}`: **{guild_count}** команд.\n"
            f"Global: **{len(global_synced)}** команд.\n"
            "Перезавантаж Discord через Ctrl+R."
        ))

        _append_runtime_log({
            "time": _utc_now(), "event": "force_sync",
            "author_id": ctx.author.id,
            "guild_count": guild_count,
            "global_count": len(global_synced),
        })
    except Exception as e:
        await msg.edit(content=f"Помилка: `{type(e).__name__}: {e}`")
        traceback.print_exc()


async def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing")
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
