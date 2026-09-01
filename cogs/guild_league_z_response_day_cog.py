from __future__ import annotations

import json
from datetime import datetime, timedelta


def _league_day_key(league) -> str:
    local = datetime.now(league.TZ)
    # 00:00-01:59 належать попередньому ігровому дню Ліги.
    if local.hour < 2:
        local -= timedelta(days=1)
    return local.date().isoformat()


def _saved_response_day(league):
    try:
        raw = json.loads(
            league.DATA_FILE.read_text(encoding="utf-8")
        )
        if isinstance(raw, dict):
            value = raw.get("response_day")
            return str(value) if value else None
    except Exception:
        pass
    return None


def _ensure_response_day(league, cog):
    today = _league_day_key(league)
    current = cog.state.get("response_day")
    if not current:
        current = _saved_response_day(league)

    if current != today:
        cog.state["responses"] = {}

    cog.state["response_day"] = today
    league.save_state(cog.state)


async def setup(bot):
    from cogs import guild_league_cog as league

    if getattr(league, "_response_day_guard_installed", False):
        return
    league._response_day_guard_installed = True

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][RESPONSE_DAY] GuildLeagueCog not found")
        return

    original_reload = league.GuildLeagueCog.reload_from_json

    def reload_from_json(self):
        saved_day = _saved_response_day(league)
        original_reload(self)
        if saved_day and not self.state.get("response_day"):
            self.state["response_day"] = saved_day

    league.GuildLeagueCog.reload_from_json = reload_from_json

    original_ok_channel = league.GuildLeagueCog.ok_channel

    async def ok_channel(self, interaction):
        allowed = await original_ok_channel(self, interaction)
        if allowed:
            _ensure_response_day(league, self)
        return allowed

    league.GuildLeagueCog.ok_channel = ok_channel

    _ensure_response_day(league, cog)

    print(
        "[GUILD_LEAGUE] response-day guard enabled: "
        "responses reset once per league day"
    )
