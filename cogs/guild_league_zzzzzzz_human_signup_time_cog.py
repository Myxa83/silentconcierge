from __future__ import annotations

from datetime import datetime

import discord


async def setup(bot):
    """Показує у меню запису звичайний час замість сирих Discord timestamp-тегів."""
    from cogs import guild_league_cog as league
    from cogs import guild_league_zz_day_schedule_cog as day

    if getattr(league, "_human_signup_time_installed", False):
        return
    league._human_signup_time_installed = True

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][HUMAN_TIME] GuildLeagueCog not found")
        return

    def clock(party):
        return datetime.fromtimestamp(
            int(party["start_ts"]), league.TZ
        ).strftime("%H:%M")

    class HumanTimeSelect(discord.ui.Select):
        def __init__(self, league_cog, parties):
            options = []
            for party in parties[:25]:
                count = league.member_count(party)
                waiting = league.waitlist_count(party)
                extra = f" +{waiting} очікує" if waiting else ""
                free = max(0, league.MAX_MEMBERS - count)

                if count >= league.MAX_MEMBERS:
                    description = (
                        f"Склад 10/10{extra}. Запис у лист очікування"
                    )
                else:
                    description = (
                        f"У складі {count}/10. Вільно {free} місць{extra}"
                    )

                options.append(
                    discord.SelectOption(
                        label=f"{clock(party)}  •  {count}/10",
                        value=str(party["number"]),
                        description=description[:100],
                    )
                )

            super().__init__(
                placeholder="Обери всі часи, коли можеш грати",
                options=options,
                min_values=1,
                max_values=max(1, len(options)),
            )
            self.cog = league_cog

        async def callback(self, interaction):
            await self.cog.add_to_slots(interaction, self.values)

    class HumanTimeView(discord.ui.View):
        def __init__(self, league_cog, parties, page=0):
            super().__init__(timeout=180)
            self.cog = league_cog
            self.parties = parties
            self.page = page

            start = page * 25
            chunk = parties[start:start + 25]
            if chunk:
                self.add_item(HumanTimeSelect(league_cog, chunk))

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

            if len(parties) > 25:
                previous = discord.ui.Button(
                    label="Раніше",
                    style=discord.ButtonStyle.secondary,
                    disabled=page == 0,
                    row=2,
                )
                next_page = discord.ui.Button(
                    label="Пізніше",
                    style=discord.ButtonStyle.secondary,
                    disabled=(page + 1) * 25 >= len(parties),
                    row=2,
                )

                async def go_previous(interaction):
                    new_page = max(0, page - 1)
                    await interaction.response.edit_message(
                        content=signup_text(self.parties, new_page),
                        view=HumanTimeView(self.cog, self.parties, new_page),
                    )

                async def go_next(interaction):
                    new_page = page + 1
                    await interaction.response.edit_message(
                        content=signup_text(self.parties, new_page),
                        view=HumanTimeView(self.cog, self.parties, new_page),
                    )

                previous.callback = go_previous
                next_page.callback = go_next
                self.add_item(previous)
                self.add_item(next_page)

    def signup_text(parties, page=0):
        start = page * 25
        chunk = parties[start:start + 25]
        if not chunk:
            return "Немає доступних часів."

        first_dt = datetime.fromtimestamp(int(chunk[0]["start_ts"]), league.TZ)
        last_dt = datetime.fromtimestamp(int(chunk[-1]["start_ts"]), league.TZ)
        date_text = first_dt.strftime("%d.%m.%Y")
        return (
            f"**Запис на {date_text}**\n"
            f"Доступні часи на цій сторінці: **{first_dt:%H:%M} - {last_dt:%H:%M}**\n\n"
            "**Обери ВСІ часи, коли можеш грати.** "
            "Можна вибрати кілька рядків одразу. "
            "Якщо можеш весь вечір, натисни **Записатися на всі часи**."
        )

    async def begin_signup_human(self, interaction):
        if not await self.ok_channel(interaction):
            return

        if hasattr(self, "ensure_today_schedule"):
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
                "На сьогодні вже немає доступних часів для запису.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            signup_text(parties, 0),
            view=HumanTimeView(self, parties, 0),
            ephemeral=True,
        )

    league.GuildLeagueCog.begin_signup = begin_signup_human

    print(
        "[GUILD_LEAGUE] human signup time enabled: select menu uses HH:MM"
    )
