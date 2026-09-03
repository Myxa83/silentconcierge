from __future__ import annotations

from discord.ext import commands


class GuildLeagueCompactTableCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    """Keep empty Guild League cells to one line instead of two."""
    from cogs import guild_league_zzzzzzzzzzzz_three_party_time_cog as three

    original = three._party_block

    def compact_party_block(league, slot, party):
        text = original(league, slot, party)
        # The old formatter added a second line containing just '-' for every
        # empty party. With 3 columns and many time slots that doubled the
        # vertical height of otherwise empty rows.
        if text.endswith("\n-"):
            return text[:-2]
        return text

    three._party_block = compact_party_block

    dated_cog = bot.get_cog("GuildLeagueDatedPosts")
    if dated_cog is not None:
        for day_iso, event in list(dated_cog.data.get("events", {}).items()):
            if not isinstance(event, dict) or not event.get("message_id"):
                continue
            try:
                await dated_cog.refresh_date(day_iso)
            except Exception as exc:
                print(
                    f"[GUILD_LEAGUE][COMPACT_TABLE][REFRESH] {day_iso}: "
                    f"{type(exc).__name__}: {exc}"
                )

    await bot.add_cog(GuildLeagueCompactTableCog(bot))
    print("[GUILD_LEAGUE] compact table rows enabled")
