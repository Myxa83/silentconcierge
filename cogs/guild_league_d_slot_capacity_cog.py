from __future__ import annotations


MAX_DAY_SLOTS = 40


async def setup(bot):
    # Завантажується після guild_league_cog.py, але до management/time guard.
    # Потрібно, щоб JSON не обрізав розклад до старих 3 паті.
    from cogs import guild_league_cog as league

    league.MAX_PARTIES = MAX_DAY_SLOTS
    print(f"[GUILD_LEAGUE] day slot capacity: {MAX_DAY_SLOTS}")
