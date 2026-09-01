from __future__ import annotations

from datetime import datetime


BLACKOUT_START_HOUR = 20
BLACKOUT_END_HOUR = 22


def _blocked(ts: int, tz) -> bool:
    """20:00 <= local Berlin time < 22:00 is unavailable for Guild League."""
    local = datetime.fromtimestamp(int(ts), tz)
    minutes = local.hour * 60 + local.minute
    return BLACKOUT_START_HOUR * 60 <= minutes < BLACKOUT_END_HOUR * 60


def _filter_pairs(slots, tz):
    return [(label, ts) for label, ts in slots if not _blocked(ts, tz)]


def _filter_parties(parties, tz):
    kept = [p for p in parties if not p.get("start_ts") or not _blocked(p["start_ts"], tz)]
    for number, party in enumerate(kept, 1):
        party["number"] = number
    return kept


def _filter_dated_slots(slots, tz):
    kept = [s for s in slots if not s.get("start_ts") or not _blocked(s["start_ts"], tz)]
    for number, slot in enumerate(kept, 1):
        slot["number"] = number
    return kept


async def setup(bot):
    """Прибирає з усіх розкладів слоти 20:00-21:40 CEST/Europe-Berlin."""
    from cogs import guild_league_cog as league

    if getattr(league, "_blackout_20_22_installed", False):
        return
    league._blackout_20_22_installed = True

    # Усі нові звичайні денні розклади.
    previous_time_slots = league.time_slots

    def time_slots_without_blackout(day_iso: str):
        return _filter_pairs(previous_time_slots(day_iso), league.TZ)

    league.time_slots = time_slots_without_blackout

    main_cog = bot.get_cog("GuildLeagueCog")
    if main_cog is not None:
        before = len(main_cog.state.get("packs", []))
        main_cog.state["packs"] = _filter_parties(
            main_cog.state.get("packs", []),
            league.TZ,
        )
        after = len(main_cog.state.get("packs", []))
        if after != before:
            main_cog.save()
        try:
            await main_cog.refresh()
        except Exception as exc:
            print(
                f"[GUILD_LEAGUE][BLACKOUT][MAIN_REFRESH] "
                f"{type(exc).__name__}: {exc}"
            )

    # Реєстрації, які публікуються наперед по датах.
    try:
        from cogs import guild_league_zzzzzzzzz_dated_posts_cog as dated
    except Exception as exc:
        print(
            f"[GUILD_LEAGUE][BLACKOUT][DATED_IMPORT] "
            f"{type(exc).__name__}: {exc}"
        )
        dated = None

    dated_cog = bot.get_cog("GuildLeagueDatedPosts")
    if dated is not None:
        previous_make_slots = dated.make_slots

        def make_slots_without_blackout(day_iso: str, tz):
            return _filter_dated_slots(previous_make_slots(day_iso, tz), tz)

        dated.make_slots = make_slots_without_blackout

    if dated_cog is not None:
        changed_days = []
        for day_iso, event in dated_cog.data.get("events", {}).items():
            slots = event.get("slots", [])
            filtered = _filter_dated_slots(slots, league.TZ)
            if len(filtered) != len(slots):
                event["slots"] = filtered
                changed_days.append(day_iso)

        if changed_days:
            dated_cog.save()

        for day_iso in changed_days:
            try:
                await dated_cog.refresh_date(day_iso)
            except Exception as exc:
                print(
                    f"[GUILD_LEAGUE][BLACKOUT][DATED_REFRESH] {day_iso} "
                    f"{type(exc).__name__}: {exc}"
                )

    print(
        "[GUILD_LEAGUE] blackout enabled: 20:00-21:40 Europe/Berlin removed; next slot 22:00"
    )
