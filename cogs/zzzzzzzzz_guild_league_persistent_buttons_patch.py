from __future__ import annotations

from discord.ext import commands


class GuildLeaguePersistentButtonsPatch(commands.Cog):
    """Compatibility shim for the old Guild League persistent-view patch.

    The dated-post cog already restores persistent views for active dates.
    The previous implementation scanned the entire Discord channel history
    with limit=None and registered another persistent view for every old post.
    That could retain a growing number of View objects in memory after restarts.

    This cog intentionally does no extra registration. It is kept as a shim so
    deployments that still expect the extension name continue to load cleanly.
    """

    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(GuildLeaguePersistentButtonsPatch(bot))
    print("[GUILD_LEAGUE][PERSISTENT] compatibility shim active; history scan disabled")
