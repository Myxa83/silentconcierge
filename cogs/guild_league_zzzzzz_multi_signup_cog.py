from __future__ import annotations

from datetime import datetime

import discord


async def setup(bot):
    """Дозволяє одному гравцю записуватися одразу на кілька слотів."""
    from cogs import guild_league_cog as league
    from cogs import guild_league_zz_day_schedule_cog as day

    if getattr(league, "_multi_signup_installed", False):
        return
    league._multi_signup_installed = True

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][MULTI] GuildLeagueCog not found")
        return

    def user_kind_in_party(party, uid):
        uid = str(uid)
        for kind in ("members", "waitlist", "pending"):
            if any(str(x.get("user_id")) == uid for x in party.get(kind, [])):
                return kind
        return None

    def all_user_parties(state, uid):
        result = []
        for party in state.get("packs", []):
            kind = user_kind_in_party(party, uid)
            if kind:
                result.append((party, kind))
        return result

    async def add_to_slots(self, interaction, numbers):
        uid = str(interaction.user.id)
        role_key = self.state.get("roles", {}).get(uid)
        if not role_key:
            await interaction.response.edit_message(
                content="Спочатку обери **Tank**, **DPS** або **Shai**.",
                view=None,
            )
            return

        # Зберігаємо порядок за часом і прибираємо дублікати.
        wanted = []
        seen = set()
        for number in numbers:
            try:
                number = int(number)
            except (TypeError, ValueError):
                continue
            if number not in seen:
                wanted.append(number)
                seen.add(number)

        added = []
        already = []
        unavailable = []
        signed_at = int(datetime.now(league.TZ).timestamp())

        async with self.lock:
            parties = []
            for number in wanted:
                party = league.get_party(self.state, number)
                if party and party.get("start_ts"):
                    parties.append(party)
            parties.sort(key=lambda p: int(p["start_ts"]))

            for party in parties:
                number = int(party["number"])
                if not party.get("enabled", True):
                    unavailable.append(party)
                    continue

                current_kind = user_kind_in_party(party, uid)
                if current_kind:
                    already.append((party, current_kind))
                    continue

                entry = {
                    "user_id": uid,
                    "role": role_key,
                    "signed_at": signed_at,
                }

                if league.member_count(party) < league.MAX_MEMBERS:
                    party.setdefault("members", []).append(entry)
                    added.append((party, "members"))
                else:
                    party.setdefault("waitlist", []).append(entry)
                    added.append((party, "waitlist"))

            if added:
                self.state.setdefault("responses", {})[uid] = "signup"
                self.save()
                await self.refresh()

        lines = []
        for party, kind in added:
            if kind == "members":
                status = f"склад {league.member_count(party)}/{league.MAX_MEMBERS}"
            else:
                status = f"лист очікування +{league.waitlist_count(party)}"
            lines.append(
                f"✅ {league.discord_time(party['start_ts'])} - **{status}**"
            )

        for party, kind in already:
            status = "у складі" if kind == "members" else "у листі очікування"
            lines.append(
                f"▫️ {league.discord_time(party['start_ts'])} - вже {status}"
            )

        for party in unavailable:
            lines.append(
                f"🔒 {league.discord_time(party['start_ts'])} - запис закрито"
            )

        if not lines:
            lines.append("Нічого не змінено.")

        await interaction.response.edit_message(
            content=(
                "**Твій запис:**\n"
                + "\n".join(lines)[:3800]
                + f"\n\nРоль: **{league.role_text(role_key)}**"
            ),
            view=None,
        )

    league.GuildLeagueCog.add_to_slots = add_to_slots

    async def signup_to_multi(self, interaction, number):
        await self.add_to_slots(interaction, [number])

    league.GuildLeagueCog.signup_to = signup_to_multi

    class MultiTimeSignupSelect(discord.ui.Select):
        def __init__(self, module, league_cog, parties):
            options = []
            for party in parties[: day.SLOTS_PER_PAGE]:
                count = module.member_count(party)
                waiting = module.waitlist_count(party)
                extra = f" +{waiting}" if waiting else ""
                options.append(
                    discord.SelectOption(
                        label=(
                            f"{datetime.fromtimestamp(int(party['start_ts']), module.TZ):%H:%M} "
                            f"• {count}/{module.MAX_MEMBERS}{extra}"
                        )[:100],
                        value=str(party["number"]),
                        description=(
                            "10/10 - запис піде в лист очікування"
                            if count >= module.MAX_MEMBERS
                            else "Можна обрати разом з іншими часами"
                        )[:100],
                    )
                )
            super().__init__(
                placeholder="Обери один або кілька часів",
                options=options,
                min_values=1,
                max_values=max(1, len(options)),
            )
            self.cog = league_cog

        async def callback(self, interaction):
            await self.cog.add_to_slots(interaction, self.values)

    day.TimeSignupSelect = MultiTimeSignupSelect

    # Перебудовуємо view, щоб була окрема кнопка "Усі часи".
    class MultiSignupTimeView(discord.ui.View):
        def __init__(self, module, league_cog, parties, page=0):
            super().__init__(timeout=180)
            self.league = module
            self.cog = league_cog
            self.parties = parties
            self.page = page

            start = page * day.SLOTS_PER_PAGE
            chunk = parties[start:start + day.SLOTS_PER_PAGE]
            if chunk:
                self.add_item(MultiTimeSignupSelect(module, league_cog, chunk))

            all_button = discord.ui.Button(
                label="Записатися на всі часи",
                emoji="✅",
                style=discord.ButtonStyle.success,
                row=1,
            )

            async def all_times(interaction):
                numbers = [
                    int(p["number"])
                    for p in self.parties
                    if p.get("enabled", True)
                ]
                await self.cog.add_to_slots(interaction, numbers)

            all_button.callback = all_times
            self.add_item(all_button)

            if len(parties) > day.SLOTS_PER_PAGE:
                prev_btn = discord.ui.Button(
                    label="Раніше",
                    style=discord.ButtonStyle.secondary,
                    disabled=page == 0,
                    row=2,
                )
                next_btn = discord.ui.Button(
                    label="Пізніше",
                    style=discord.ButtonStyle.secondary,
                    disabled=(page + 1) * day.SLOTS_PER_PAGE >= len(parties),
                    row=2,
                )

                async def previous(interaction):
                    new_page = max(0, page - 1)
                    await interaction.response.edit_message(
                        content=self.cog.signup_prompt(self.parties, new_page),
                        view=MultiSignupTimeView(
                            self.league,
                            self.cog,
                            self.parties,
                            new_page,
                        ),
                    )

                async def next_page(interaction):
                    new_page = page + 1
                    await interaction.response.edit_message(
                        content=self.cog.signup_prompt(self.parties, new_page),
                        view=MultiSignupTimeView(
                            self.league,
                            self.cog,
                            self.parties,
                            new_page,
                        ),
                    )

                prev_btn.callback = previous
                next_btn.callback = next_page
                self.add_item(prev_btn)
                self.add_item(next_btn)

    day.SignupTimeView = MultiSignupTimeView

    original_signup_prompt = getattr(league.GuildLeagueCog, "signup_prompt", None)

    def multi_signup_prompt(self, parties, page):
        start = page * day.SLOTS_PER_PAGE
        chunk = parties[start:start + day.SLOTS_PER_PAGE]
        if not chunk:
            return "Немає доступних часів."
        first = chunk[0]
        last = chunk[-1]
        return (
            "**Обери один або кілька часів:**\n"
            f"{league.discord_date_time(first['start_ts'])} - "
            f"{league.discord_time(last['start_ts'])}\n"
            "Одна людина може записатися **на кілька або на всі паті**. "
            "Для всіх слотів одразу натисни **Записатися на всі часи**."
        )

    league.GuildLeagueCog.signup_prompt = multi_signup_prompt

    async def leave_all(self, interaction):
        if not await self.ok_channel(interaction):
            return

        uid = str(interaction.user.id)
        registrations = all_user_parties(self.state, uid)
        if not registrations:
            await interaction.response.send_message(
                "Ти не записаний у жодне паті.",
                ephemeral=True,
            )
            return

        promoted = []
        removed_times = []
        async with self.lock:
            for party, _kind in list(registrations):
                removed_kind, moved = league.remove_user_from_party(party, uid)
                if removed_kind:
                    removed_times.append(int(party["start_ts"]))
                if moved:
                    promoted.append((party, moved))

            self.state.setdefault("responses", {})[uid] = "cant"
            self.save()
            await self.refresh()

        for party, moved in promoted:
            await self.send_promotion_notice(party, moved)

        times = ", ".join(league.discord_time(ts) for ts in sorted(removed_times))
        await interaction.response.send_message(
            (
                "Твої записи на цей день скасовано."
                + (f"\nЧаси: {times}" if times else "")
            ),
            ephemeral=True,
        )

    league.GuildLeagueCog.leave = leave_all

    async def help_multi(self, interaction):
        if not await self.ok_channel(interaction):
            return
        await interaction.response.send_message(
            (
                "**Як записатися:**\n"
                "1. Обери **Tank**, **DPS** або **Shai**.\n"
                "2. Натисни **Записатися**.\n"
                "3. Вибери **один, кілька або всі часи**.\n\n"
                "Одна людина може бути записана одразу в кілька паті. "
                "У кожному паті окремо максимум **10 людей у складі**. "
                "Після 10/10 наступні йдуть у **лист очікування**.\n\n"
                "**Не можу** скасовує всі твої записи на цей день."
            ),
            ephemeral=True,
        )

    league.GuildLeagueCog.help = help_multi

    # Оновлюємо текст шапки.
    previous_header = day._header_embed

    def multi_header(module, state):
        embed = previous_header(module, state)
        if day._scheduled(state):
            embed.description = (
                "Обери **Tank / DPS / Shai**, натисни **Записатися** і "
                "вибери **один, кілька або всі часи**. Одна людина може "
                "бути записана в кілька паті. У кожному паті максимум 10, "
                "далі - лист очікування."
            )
        return embed

    day._header_embed = multi_header
    league.header_embed = lambda state: multi_header(league, state)

    try:
        await cog.refresh()
    except Exception as exc:
        print(
            f"[GUILD_LEAGUE][MULTI][REFRESH] {type(exc).__name__}: {exc}"
        )

    print(
        "[GUILD_LEAGUE] multi signup enabled: one player can join many/all slots"
    )
