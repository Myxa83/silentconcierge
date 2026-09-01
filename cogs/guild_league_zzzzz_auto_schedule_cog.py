from __future__ import annotations

from datetime import datetime, timedelta


async def setup(bot):
    """Автоматично тримає активний розклад на поточний день Ліги."""
    from cogs import guild_league_cog as league
    from cogs import guild_league_zz_day_schedule_cog as day

    if getattr(league, "_auto_schedule_installed", False):
        return
    league._auto_schedule_installed = True

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][AUTO] GuildLeagueCog not found")
        return

    def league_day(dt: datetime):
        local = dt.astimezone(league.TZ)
        if local.hour < 2:
            local -= timedelta(days=1)
        return local.date()

    def party_day(party):
        ts = party.get("start_ts")
        if not ts:
            return None
        return league_day(datetime.fromtimestamp(int(ts), league.TZ))

    def ensure_today_schedule(self) -> bool:
        now = datetime.now(league.TZ)
        target_day = league_day(now)

        active = [
            p for p in self.state.get("packs", [])
            if p.get("start_ts") and party_day(p) == target_day
        ]
        if active:
            return False

        slots = league.time_slots(target_day.isoformat())
        if not slots:
            # Після завершення попереднього ігрового дня готуємо найближчий день.
            target_day = now.date()
            slots = league.time_slots(target_day.isoformat())
        if not slots:
            return False

        old_parties = list(self.state.get("packs", []))
        existing_by_ts = {
            int(p["start_ts"]): p
            for p in old_parties
            if p.get("start_ts")
        }
        new_ts = {int(ts) for _label, ts in slots}

        history = self.state.setdefault("history", [])
        for old in old_parties:
            ts = old.get("start_ts")
            if not ts or int(ts) in new_ts:
                continue
            if old.get("members") or old.get("waitlist") or old.get("pending"):
                archived = dict(old)
                archived["archived_at"] = int(now.timestamp())
                history.append(archived)

        new_parties = []
        for number, (_label, ts) in enumerate(slots, 1):
            previous = existing_by_ts.get(int(ts))
            if previous:
                party = dict(previous)
                party["number"] = number
                party.setdefault("enabled", True)
                party.setdefault("members", [])
                party.setdefault("waitlist", [])
                party.setdefault("pending", [])
            else:
                party = {
                    "number": number,
                    "start_ts": int(ts),
                    "enabled": True,
                    "members": [],
                    "waitlist": [],
                    "pending": [],
                }
            new_parties.append(party)

        self.state["packs"] = new_parties
        self.state["schedule_day"] = target_day.isoformat()
        self.state["history"] = history[-100:]
        self.state["responses"] = {}
        self.save()
        print(
            f"[GUILD_LEAGUE][AUTO] schedule ready: "
            f"{target_day.isoformat()} slots={len(new_parties)}"
        )
        return True

    league.GuildLeagueCog.ensure_today_schedule = ensure_today_schedule

    previous_reload = league.GuildLeagueCog.reload_from_json

    def reload_with_schedule(self):
        previous_reload(self)
        self.ensure_today_schedule()

    league.GuildLeagueCog.reload_from_json = reload_with_schedule

    async def begin_signup_auto(self, interaction):
        if not await self.ok_channel(interaction):
            return

        self.ensure_today_schedule()

        uid = str(interaction.user.id)
        if not self.state.get("roles", {}).get(uid):
            await interaction.response.send_message(
                "Спочатку обери **Tank**, **DPS** або **Shai**.",
                ephemeral=True,
            )
            return

        parties = [
            p for p in day._scheduled(self.state)
            if p.get("enabled", True)
        ]
        if not parties:
            await interaction.response.send_message(
                "На сьогодні вже немає доступних майбутніх часів.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            self.signup_prompt(parties, 0),
            view=day.SignupTimeView(league, self, parties, 0),
            ephemeral=True,
        )

    league.GuildLeagueCog.begin_signup = begin_signup_auto

    # На старті теж створюємо розклад, щоб /guild_league_panel одразу його показав.
    try:
        changed = cog.ensure_today_schedule()
        if changed:
            await cog.refresh()
    except Exception as exc:
        print(
            f"[GUILD_LEAGUE][AUTO][INIT] "
            f"{type(exc).__name__}: {exc}"
        )

    print("[GUILD_LEAGUE] auto schedule enabled")
