# bot_main.py
import asyncio
import json
import os
import traceback
from datetime import datetime
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from config.loader import DISCORD_TOKEN, GUILD_ID


INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.voice_states = True


LOG_DIR = Path("logs")
RUNTIME_LOG = LOG_DIR / "runtime_logs.json"


def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


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
        RUNTIME_LOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=INTENTS,
            help_command=None,
        )

    async def setup_hook(self):
        # ---------- BOOT DIAGNOSTICS ----------
        print("[BOOT] bot_main.py started")
        print("[BOOT] CWD:", os.getcwd())

        try:
            root_files = sorted(os.listdir("."))
        except Exception as e:
            root_files = [f"[ERR] {type(e).__name__}: {e}"]
        print("[BOOT] ROOT FILES:", root_files)

        cogs_files = []
        if os.path.isdir("cogs"):
            try:
                cogs_files = sorted(os.listdir("cogs"))
                print("[BOOT] COGS FILES:", cogs_files)
            except Exception as e:
                print(f"[BOOT][WARN] cannot list cogs/: {type(e).__name__}: {e}")
        else:
            print("[BOOT][WARN] cogs/ directory NOT FOUND")

        # ---------- AUTO LOAD COGS ----------
        loaded_ext = []
        failed_ext = []

        if os.path.isdir("cogs"):
            for file in sorted(os.listdir("cogs")):
                if not file.endswith(".py"):
                    continue
                if file.startswith("_"):
                    continue
                if file == "__init__.py":
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

        # ---------- SYNC COMMANDS (ЖОРСТКИЙ РЕЖИМ) ----------
        try:
            gid = None
            try:
                gid = int(GUILD_ID) if GUILD_ID else None
            except Exception:
                gid = None

            if gid:
                guild_obj = discord.Object(id=gid)
                # 1. Видаляємо привиди старих команд
                self.tree.clear_commands(guild=guild_obj)
                # 2. Копіюємо нові команди з когів у дерево сервера
                self.tree.copy_global_to(guild=guild_obj)
                # 3. Синхронізуємо
                synced = await self.tree.sync(guild=guild_obj)
                
                print(f"[SYNC] Force synced to guild {gid}. Count: {len(synced)}")
                for c in synced: print(f"  - /{c.name}")
                
                _append_runtime_log({
                    "time": _utc_now(),
                    "event": "sync",
                    "mode": "guild_force",
                    "guild_id": gid,
                    "count": len(synced),
                })
            else:
                synced = await self.tree.sync()
                print(f"[SYNC] Global sync successful. Count: {len(synced)}")
                _append_runtime_log({
                    "time": _utc_now(),
                    "event": "sync",
                    "mode": "global",
                    "count": len(synced),
                })
        except Exception as e:
            print(f"[SYNC][FAIL] {type(e).__name__}: {e}")
            traceback.print_exc()
            _append_runtime_log({
                "time": _utc_now(),
                "event": "sync_fail",
                "error_type": type(e).__name__,
                "error": str(e),
                "traceback": traceback.format_exc(),
            })

        # ---------- GLOBAL APP COMMAND ERROR HANDLER ----------
        @self.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            tb = "".join(traceback.format_exception(type(error), error, error.__traceback__))

            cmd_name = None
            try:
                if interaction.command:
                    cmd_name = interaction.command.qualified_name
            except Exception:
                cmd_name = None

            print(f"[APP_CMD_ERROR] cmd={cmd_name} user={getattr(interaction.user,'id',None)} guild={getattr(interaction.guild,'id',None)}")
            print(tb)

            _append_runtime_log({
                "time": _utc_now(),
                "event": "app_cmd_error",
                "cmd": cmd_name,
                "user_id": getattr(interaction.user, "id", None),
                "guild_id": getattr(interaction.guild, "id", None),
                "error_type": type(error).__name__,
                "error": str(error),
                "traceback": tb,
            })

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(f"❌ Помилка: `{type(error).__name__}`", ephemeral=True)
                else:
                    await interaction.response.send_message(f"❌ Помилка: `{type(error).__name__}`", ephemeral=True)
            except Exception:
                pass

    async def on_ready(self):
        print(f"[READY] Logged in as {self.user} ({self.user.id})")
        _append_runtime_log({
            "time": _utc_now(),
            "event": "ready",
            "user_id": getattr(self.user, "id", None),
        })

    # ---------- ТЕКСТОВА КОМАНДА ДЛЯ ПРИМУСОВОЇ СИНХРОНІЗАЦІЇ ----------
    @commands.command(name="force_sync")
    @commands.is_owner()
    async def force_sync(self, ctx: commands.Context):
        """Текстова команда !force_sync для виправлення слеш-команд"""
        msg = await ctx.send("⏳ Починаю жорстку синхронізацію команд...")
        try:
            gid = int(GUILD_ID) if GUILD_ID else None
            if gid:
                guild_obj = discord.Object(id=gid)
                self.tree.clear_commands(guild=guild_obj)
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                await msg.edit(content=f"✅ Готово! Команди сервера `{gid}` оновлено: **{len(synced)}**.\nПерезавантаж Discord (Ctrl+R).")
            else:
                synced = await self.tree.sync()
                await msg.edit(content=f"🌍 Глобальна синхронізація успішна: **{len(synced)}** команд.\nПерезавантаж Discord (Ctrl+R).")
        except Exception as e:
            await msg.edit(content=f"❌ Помилка при синхронізації: `{e}`")
            traceback.print_exc()


async def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing")

    bot = Bot()
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
    
