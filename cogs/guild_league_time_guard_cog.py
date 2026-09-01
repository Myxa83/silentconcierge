from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


TZ = ZoneInfo("Europe/Berlin")
HISTORY_LIMIT = 100


def _league_day(dt: datetime):
    local = dt.astimezone(TZ)
    # Слоти 00:00-01:00 належать попередньому ігровому дню Ліги.
    if local.hour < 2:
        local -= timedelta(days=1)
    return local.date()


def _cleanup_previous_days(module, cog) -> int:
    state = cog.state
    today = _league_day(datetime.now(TZ))
    active = []
    history = list(state.get("history", []))
    moved = 0

    for party in state.get("packs", []):
        ts = party.get("start_ts")
        if ts:
            party_day = _league_day(
                datetime.fromtimestamp(int(ts), TZ)
            )
            if party_day < today:
                archived = dict(party)
                archived["archived_at"] = int(
                    datetime.now(TZ).timestamp()
                )
                history.append(archived)
                moved += 1
                continue
        active.append(party)

    if moved:
        # На новий актуальний список нумерація знову компактна: 1 -> 2 -> 3.
        for index, party in enumerate(active, 1):
            party["number"] = index

        state["packs"] = active[: module.MAX_PARTIES]
        state["history"] = history[-HISTORY_LIMIT:]

        # Відповідь "Не можу" стосується конкретного ігрового дня.
        # На новий день її треба скинути. Ті, хто вже записаний
        # у майбутні паті, все одно визначаються як такі, що відповіли,
        # за самим складом / заявками.
        state["responses"] = {}

        module.save_state(state)

    return moved


async def setup(bot):
    # Цей guard завантажується після guild_league_cog.py через сортування cogs.
    from cogs import guild_league_cog as league

    if getattr(league, "_time_guard_installed", False):
        return

    league._time_guard_installed = True

    original_time_slots = league.time_slots

    def future_time_slots(day_iso: str):
        # Не показуємо PL слоти, які вже минули на момент відкриття меню.
        now = datetime.now(TZ)
        return [
            (label, ts)
            for label, ts in original_time_slots(day_iso)
            if datetime.fromtimestamp(int(ts), TZ) >= now
        ]

    league.time_slots = future_time_slots

    original_reload = league.GuildLeagueCog.reload_from_json

    def reload_from_json(self):
        original_reload(self)
        _cleanup_previous_days(league, self)

    league.GuildLeagueCog.reload_from_json = reload_from_json

    original_ok_channel = league.GuildLeagueCog.ok_channel

    async def ok_channel(self, interaction):
        # Старі паті не повинні оживати з JSON при взаємодії наступного дня.
        _cleanup_previous_days(league, self)
        return await original_ok_channel(self, interaction)

    league.GuildLeagueCog.ok_channel = ok_channel

    print(
        "[GUILD_LEAGUE] time guard enabled: "
        "past slots hidden, previous days archived"
    )
