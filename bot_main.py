# -*- coding: utf-8 -*-
# bot_main.py
#
# ВАЖЛИВО:
# Для музичного бота НЕ можна ставити DISCORD_DISABLE_VOICE=1.
# Цей прапорець вимикає voice-частину discord.py, тому бот не може зайти у voice.
# Якщо Render/Python падає через audioop, краще використати Python 3.13 або встановити PyNaCl,
# але не вимикати voice.

import asyncio
import json
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

# НЕ ВМИКАТИ ДЛЯ МУЗИКИ:
# os.environ["DISCORD_DISABLE_VOICE"] = "1"

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


def _format_real_error(error: BaseException) -> tuple[str, str]:
    real_error = getattr(error, "original", error)
    err_type = type(real_error).__name__
    err_text = str(real_error) or str(error) or "Unknown error"
    return err_type, err_text


class SilentBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix="!",
            intents=INTENTS,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        print("[BOOT] bot_main.py started")
        print("[BOOT] CWD:", os.getcwd())
        print("[BOOT] DISCORD_DISABLE_VOICE:", os.getenv("DISCORD_DISABLE_VOICE"))

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

        loaded_ext: list[str] = []
        failed_ext: list[dict] = []

        if os.path.isdir("cogs"):
            for file in sorted(os.listdir("cogs")):
