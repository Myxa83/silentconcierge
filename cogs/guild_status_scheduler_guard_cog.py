# -*- coding: utf-8 -*-
"""Memory-safe scheduler for the Selenium based guild roster audit.

The original GuildStatusCog starts Chrome two minutes after every process boot
and then every six hours. On a small Render worker a browser process can create
an RSS spike large enough to trigger an OOM restart, which then schedules the
same browser job again two minutes later.

This guard keeps the manual /guild_members_check command unchanged, cancels the
aggressive automatic loop, and replaces it with a delayed, configurable daily
check. If the worker restarts, it gets several hours of stable uptime before a
browser is launched again.
"""

from __future__ import annotations

import asyncio
import os

from discord.ext import commands, tasks


TARGET_COG_NAME = "GuildStatusCog"


def _env_hours(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        value = default
    return max(1.0, value)


AUTO_INTERVAL_HOURS = _env_hours("GUILD_AUDIT_INTERVAL_HOURS", 24.0)
AUTO_INITIAL_DELAY_HOURS = _env_hours("GUILD_AUDIT_INITIAL_DELAY_HOURS", 6.0)


class GuildStatusSchedulerGuard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._target = None

    async def cog_load(self) -> None:
        self._target = self.bot.get_cog(TARGET_COG_NAME)
        if self._target is None:
            print("[GUILD_MEMBERSHIP][MEMORY_GUARD] target cog not found")
            return

        original_loop = getattr(self._target, "scheduled_check", None)
        if original_loop is not None and original_loop.is_running():
            original_loop.cancel()
            print("[GUILD_MEMBERSHIP][MEMORY_GUARD] cancelled 6h Selenium loop")

        self.safe_scheduled_check.change_interval(hours=AUTO_INTERVAL_HOURS)
        self.safe_scheduled_check.start()
        print(
            "[GUILD_MEMBERSHIP][MEMORY_GUARD] "
            f"initial_delay={AUTO_INITIAL_DELAY_HOURS}h interval={AUTO_INTERVAL_HOURS}h"
        )

    def cog_unload(self) -> None:
        if self.safe_scheduled_check.is_running():
            self.safe_scheduled_check.cancel()

    @tasks.loop(hours=24)
    async def safe_scheduled_check(self) -> None:
        target = self._target or self.bot.get_cog(TARGET_COG_NAME)
        if target is None:
            return

        guild_id = getattr(__import__("cogs.guild_status_cog_clean", fromlist=["DISCORD_GUILD_ID"]), "DISCORD_GUILD_ID")
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            print(f"[GUILD_MEMBERSHIP][MEMORY_GUARD] guild {guild_id} not found")
            return

        try:
            result = await target.run_membership_check(
                guild,
                apply_guest_roles=True,
                trigger="scheduled_memory_safe",
            )
            print(
                "[GUILD_MEMBERSHIP][MEMORY_GUARD][OK] "
                f"site={result.roster_members} discord={result.discord_members} "
                f"absent={len(result.absent)} guest_added={len(result.guest_added)}"
            )
        except Exception as error:
            print(
                "[GUILD_MEMBERSHIP][MEMORY_GUARD][ERROR] "
                f"{type(error).__name__}: {error}"
            )

    @safe_scheduled_check.before_loop
    async def before_safe_scheduled_check(self) -> None:
        await self.bot.wait_until_ready()
        await asyncio.sleep(AUTO_INITIAL_DELAY_HOURS * 3600)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GuildStatusSchedulerGuard(bot))
