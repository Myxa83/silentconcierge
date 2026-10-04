# -*- coding: utf-8 -*-
"""Runtime memory telemetry and conservative memory cleanup for Render/Linux.

The cog logs current RSS every few minutes, runs a soft cleanup when RSS gets
high, and performs one deeper cleanup every night in Europe/London time.
No third-party dependency is required.
"""

from __future__ import annotations

import ctypes
import gc
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

from discord.ext import commands, tasks


CHECK_MINUTES = max(5, int(os.getenv("MEMORY_LOG_INTERVAL_MINUTES", "15") or 15))
# Render worker is 512 MB. Start reclaiming well before the hard limit.
GC_SOFT_LIMIT_MB = max(0, int(os.getenv("MEMORY_GC_SOFT_LIMIT_MB", "360") or 360))
LONDON_TZ = ZoneInfo("Europe/London")
DAILY_CLEAN_TIME = time(hour=3, minute=30, tzinfo=LONDON_TZ)


def _rss_mb() -> float | None:
    try:
        with open("/proc/self/statm", "r", encoding="utf-8") as handle:
            resident_pages = int(handle.read().split()[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
        return resident_pages * page_size / (1024 * 1024)
    except Exception:
        return None


def _trim_process_memory() -> tuple[int, float | None, float | None]:
    """Collect Python garbage and ask glibc to return free heap pages to Linux."""
    before = _rss_mb()
    collected = gc.collect()

    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass

    after = _rss_mb()
    return collected, before, after


class MemoryMonitorCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.memory_report.change_interval(minutes=CHECK_MINUTES)
        self.memory_report.start()
        self.daily_memory_cleanup.start()

    def cog_unload(self) -> None:
        if self.memory_report.is_running():
            self.memory_report.cancel()
        if self.daily_memory_cleanup.is_running():
            self.daily_memory_cleanup.cancel()

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
            collected, before, after = _trim_process_memory()
            before_text = f"{before:.1f}MB" if before is not None else "unknown"
            after_text = f"{after:.1f}MB" if after is not None else "unknown"
            print(
                "[MEMORY][GC] "
                f"threshold={GC_SOFT_LIMIT_MB}MB collected={collected} "
                f"rss_before={before_text} rss_after={after_text}"
            )

    @tasks.loop(time=DAILY_CLEAN_TIME)
    async def daily_memory_cleanup(self) -> None:
        collected, before, after = _trim_process_memory()
        before_text = f"{before:.1f}MB" if before is not None else "unknown"
        after_text = f"{after:.1f}MB" if after is not None else "unknown"
        now = datetime.now(LONDON_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(
            "[MEMORY][DAILY_CLEAN] "
            f"time={now} collected={collected} "
            f"rss_before={before_text} rss_after={after_text}"
        )

    @memory_report.before_loop
    async def before_memory_report(self) -> None:
        await self.bot.wait_until_ready()

    @daily_memory_cleanup.before_loop
    async def before_daily_memory_cleanup(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemoryMonitorCog(bot))
