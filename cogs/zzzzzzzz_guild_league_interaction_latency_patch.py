from __future__ import annotations

import asyncio

from discord.ext import commands


_PATCH_MARK = "_guild_league_background_refresh_patch"


def _backgroundize_refresh(cls, method_name: str) -> None:
    """Make slow panel refreshes non-blocking for Discord component callbacks.

    Discord expects the interaction to be acknowledged within a few seconds.
    The Guild League callbacks used to await fetch_message/edit before sending
    the ephemeral response, so users could see "application did not respond"
    even though their click had actually been processed.
    """
    original = getattr(cls, method_name, None)
    if original is None or getattr(original, _PATCH_MARK, False):
        return

    async def fast_refresh(self, *args, **kwargs):
        async def runner():
            try:
                await original(self, *args, **kwargs)
            except Exception as exc:
                print(
                    f"[GUILD_LEAGUE][BACKGROUND_REFRESH] "
                    f"{cls.__name__}.{method_name}: "
                    f"{type(exc).__name__}: {exc}"
                )

        asyncio.create_task(runner())
        # Yield once, then return immediately so the component callback can
        # acknowledge the Discord interaction before the 3-second deadline.
        await asyncio.sleep(0)

    setattr(fast_refresh, _PATCH_MARK, True)
    setattr(cls, method_name, fast_refresh)


class GuildLeagueInteractionLatencyPatch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    # Patch both the main Guild League panel and the per-date registration
    # panel. Importing the modules is safe even if their cogs are loaded later:
    # the class methods remain patched when the instances are created.
    from cogs import guild_league_cog as league
    from cogs import guild_league_zzzzzzzzz_dated_posts_cog as dated

    _backgroundize_refresh(league.GuildLeagueCog, "refresh")
    _backgroundize_refresh(dated.GuildLeagueDatedPosts, "refresh_date")

    await bot.add_cog(GuildLeagueInteractionLatencyPatch(bot))
