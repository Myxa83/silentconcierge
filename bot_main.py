# -*- coding: utf-8 -*-
import os
import asyncio
import logging
from discord.ext import commands
import discord

# ===================== ЛОГИ =====================
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,  # лише важливі події в консоль
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),  # у консоль — лише INFO/ERROR
        logging.FileHandler("logs/bot_runtime.log", encoding="utf-8")  # усе — у файл
    ]
)

# відключаємо flood від discord.py
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.ERROR)
logging.getLogger("discord.client").setLevel(logging.ERROR)
logging.getLogger("websockets").setLevel(logging.ERROR)

logger = logging.getLogger("SilentConcierge")

# ===================== ЧИТАННЯ .env.main =====================
def load_env_vars(env_path: str = "config/.env.main"):
    if not os.path.exists(env_path):
        raise RuntimeError(f"❌ Файл {env_path} не знайдено!")

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

    logger.info(f"[ENV] ✅ Змінні з {env_path} завантажено")

# ===================== НАСТРОЙКИ =====================
INTENTS = discord.Intents.all()
BOT_PREFIX = "!"
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=INTENTS)

COGS = [
    "cogs.announce_dm_cog",
    "cogs.ban_cog",
    # "cogs.bdo_family_lookup",
    # "cogs.event_watcher_cog",
    "cogs.guild_boss_command",
    #"cogs.guild_status_cog",
    #"cogs.guild_status_cog_clean",
    #"cogs.guild_upload_cog",
    #"cogs.lookup_cog",
    # "cogs.message_report_bot",
    "cogs.post_cog",
    # "cogs.profile_cog",
    # "cogs.raid_cog",
    #"cogs.ruin_cog",
    #"cogs.seaquests_cog",
    #"cogs.server_updates_cog",
    #"cogs.stream_cog",
    "cogs.sync_cog",
    "cogs.timezone_cog",
    # "cogs.toshi_refresh_cog",
    "cogs.vell_cog",
    "cogs.vitalnij_cog",
    "cogs.welcome_cog",
    "cogs.purge_cog",
    "cogs.discord_role_select_cog",
    "cogs.role_panel_post_cog", 
    "cogs.dm_permission_cog",
    "cogs.music_cog",
]

# ===================== EVENTS =====================
@bot.event
async def on_ready():
    logger.info(f"[BOT] Увійшов як {bot.user} (ID: {bot.user.id})")
    logger.info(f"[BOT] Підключено до {len(bot.guilds)} серверів")
    try:
        await bot.tree.sync()
        logger.info("[BOT] Slash-команди синхронізовано глобально")
    except Exception as e:
        logger.error(f"[BOT] ❌ Помилка при авто-синхронізації: {e}")

# ===================== LOAD COGS =====================
async def load_cogs():
    for cog in COGS:
        try:
            await bot.load_extension(cog)
            logger.info(f"[COG] ✅ Завантажено: {cog}")
        except Exception as e:
            logger.error(f"[COG] ❌ Помилка у {cog}: {e}")

# ===================== MAIN =====================
async def main():
    load_env_vars()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_TOKEN не знайдено у .env.main!")

    async with bot:
        await load_cogs()
        logger.info("[BOT] 🚀 Усі коги завантажені, запуск клієнта...")
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
