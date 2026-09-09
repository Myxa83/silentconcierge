# -*- coding: utf-8 -*-
"""Lightweight memory telemetry for Render/Linux.

No third-party dependency is required. The cog prints current RSS, Discord
message cache size and persistent-view count so future memory growth is visible
in Render logs before the worker is killed.
"""

from __future__ import annotations

import gc
import os

from discord.ext import commands, tasks


CHECK_MINUTES = max(5, int(os.getenv("MEMORY_LOG_INTERVAL_MINUTES", "15") or 15))
GC_SOFT_LIMIT_MB = max(0, int(os.getenv("MEMORY_GC_SOFT_LIMIT_MB", "0") or 0))


def _rss_mb() -> float | None:
    try:
        with open("/proc/self/statm", "r", encoding="utf-8") as handle:
            resident_pages = int(handle.read().split()[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
        return resident_pages * page_size / (1024 * 1024)
    except Exception:
        return None


class MemoryMonitorCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.memory_report.change_interval(minutes=CHECK_MINUTES)
        self.memory_report.start()

    def cog_unload(self) -> None:
        if self.memory_report.is_running():
            self.memory_report.cancel()

    @tasks.loop(minutes=15)
    async def memory_report(self) -> None:
        rss = _rss_mb()
        cached_messages = len(getattr(self.bot, "cached_messages", ()) or ())
        persistent_views = len(getattr(self.bot, "persistent_views", ()) or ())

        rss_text = f"{rss:.1f}MB" if rss is not None else "unknown"
        print(
            "[MEMORY] "
            f"rss={rss_text} cached_messages={cached_messages} "
            f"persistent_views={persistent_views} cogs={len(self.bot.cogs)}"
        )

        if GC_SOFT_LIMIT_MB and rss is not None and rss >= GC_SOFT_LIMIT_MB:
            collected = gc.collect()
            after = _rss_mb()
            after_text = f"{after:.1f}MB" if after is not None else "unknown"
            print(
                "[MEMORY][GC] "
                f"threshold={GC_SOFT_LIMIT_MB}MB collected={collected} "
                f"rss_after={after_text}"
            )

    @memory_report.before_loop
    async def before_memory_report(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemoryMonitorCog(bot))
