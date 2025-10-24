# -*- coding: utf-8 -*-
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import logging
import traceback

logger = logging.getLogger("SilentConcierge")


class SyncCog(commands.Cog):
    """Команди для оновлення slash-команд Silent Concierge"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ============================================================
    # 🌍 /sync — глобальна синхронізація (оновлює у всіх гільдіях)
    # ============================================================
    @app_commands.command(
        name="sync",
        description="🌍 Синхронізувати всі slash-команди глобально (оновлення може тривати до 1 години)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_global(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            await asyncio.sleep(0.5)

            synced = await self.bot.tree.sync()
            msg = f"🌍 Глобально синхронізовано **{len(synced)}** команд у Discord."
            logger.info(f"[SYNC] {msg}")
            await interaction.followup.send(msg, ephemeral=True)

        except discord.NotFound:
            logger.warning("[SYNC] 404 Not Found (Unknown interaction)")
            await interaction.followup.send("⚠️ Discord повернув 404 — interaction не знайдено.", ephemeral=True)

        except discord.HTTPException as e:
            logger.error(f"[SYNC] HTTPException: {e}")
            await interaction.followup.send(f"⚠️ HTTP помилка ({e.status})", ephemeral=True)

        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"[SYNC] ❌ {e}\n{tb}")
            await interaction.followup.send(f"❌ Помилка синхронізації: {e}", ephemeral=True)

    # ============================================================
    # 🏠 /synclocal — миттєва локальна синхронізація для поточного сервера
    # ============================================================
    @app_commands.command(
        name="synclocal",
        description="🏠 Синхронізувати команди лише для цього сервера (миттєво)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_local(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
            await asyncio.sleep(0.5)

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("⚠️ Ця команда працює лише всередині сервера.", ephemeral=True)
                return

            synced = await self.bot.tree.sync(guild=guild)
            msg = f"🏠 Локально синхронізовано **{len(synced)}** команд для сервера **{guild.name}**."
            logger.info(f"[SYNC] {msg}")
            await interaction.followup.send(msg, ephemeral=True)

        except discord.NotFound:
            logger.warning("[SYNC] 404 Not Found (Unknown interaction)")
            await interaction.followup.send("⚠️ Discord повернув 404 — interaction не знайдено.", ephemeral=True)

        except discord.HTTPException as e:
            logger.error(f"[SYNC] HTTPException: {e}")
            await interaction.followup.send(f"⚠️ HTTP помилка ({e.status})", ephemeral=True)

        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"[SYNC] ❌ {e}\n{tb}")
            await interaction.followup.send(f"❌ Помилка локальної синхронізації: {e}", ephemeral=True)


# ============================================================
# ⚙️ SETUP
# ============================================================
async def setup(bot: commands.Bot):
    await bot.add_cog(SyncCog(bot))
    logger.info("[SYNC] ✅ Cog /sync та /synclocal підвантажено успішно")