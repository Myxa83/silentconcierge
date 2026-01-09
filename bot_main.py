# bot_main.py
import asyncio
import os
import traceback

import discord
from discord.ext import commands

from config.loader import DISCORD_TOKEN, GUILD_ID


INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True
INTENTS.voice_states = True


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
        print("[BOOT] ROOT FILES:", sorted(os.listdir(".")))

        if os.path.isdir("cogs"):
            print("[BOOT] COGS FILES:", sorted(os.listdir("cogs")))
        else:
            print("[BOOT][WARN] cogs/ directory NOT FOUND")

        if os.path.isdir("data"):
            print("[BOOT] DATA FILES:", sorted(os.listdir("data")))
        else:
            print("[BOOT][WARN] data/ directory NOT FOUND")

        # ---------- AUTO LOAD COGS ----------
        loaded = 0
        failed = 0

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
                    loaded += 1
                except Exception as e:
                    print(f"[COG][FAIL] {ext}: {type(e).__name__}: {e}")
                    traceback.print_exc()
                    failed += 1
        else:
            print("[BOOT][FATAL] No cogs directory, nothing to load")

        print(f"[BOOT] COG LOAD RESULT: ok={loaded}, fail={failed}")

        # ---------- SYNC COMMANDS ----------
        try:
            if GUILD_ID:
                await self.tree.sync(guild=discord.Object(id=GUILD_ID))
                print(f"[SYNC] Commands synced to guild {GUILD_ID}")
            else:
                await self.tree.sync()
                print("[SYNC] Commands synced globally")
        except Exception as e:
            print(f"[SYNC][FAIL] {type(e).__name__}: {e}")
            traceback.print_exc()

    async def on_ready(self):
        print(f"[READY] Logged in as {self.user} ({self.user.id})")


async def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing")

    bot = Bot()
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())

