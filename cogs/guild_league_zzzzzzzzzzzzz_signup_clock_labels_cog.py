from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord


async def setup(bot):
    """Показує реальний час у dropdown запису на Лігу.

    Discord не рендерить <t:...:t> всередині SelectOption, тому для приватного
    меню беремо таймзону користувача з timezone_cog і форматуємо HH:MM вручну.
    """
    from cogs import guild_league_zzzzzzzzz_dated_posts_cog as dated
    from cogs import guild_league_zzzzzzzzzzzz_three_party_time_cog as three

    cog = bot.get_cog("GuildLeagueDatedPosts")
    if cog is None:
        print("[GUILD_LEAGUE][SIGNUP_CLOCK] GuildLeagueDatedPosts not found")
        return

    try:
        from cogs.timezone_cog import load_data as load_timezones
    except Exception:
        load_timezones = None

    def user_timezone(user_id: int | str) -> str:
        if load_timezones is not None:
            try:
                data = load_timezones()
                row = data.get(str(user_id), {}) if isinstance(data, dict) else {}
                tz_name = row.get("timezone") if isinstance(row, dict) else None
                if tz_name:
                    ZoneInfo(tz_name)
                    return tz_name
            except Exception:
                pass
        # Без збереженої таймзони неможливо отримати часовий пояс клієнта Discord.
        # Базовий ігровий час BDO EU лишається Europe/Berlin.
        return "Europe/Berlin"

    def local_clock(ts: int, tz_name: str) -> str:
        return datetime.fromtimestamp(int(ts), ZoneInfo(tz_name)).strftime("%H:%M")

    class ClockTimeSelect(discord.ui.Select):
        def __init__(self, league_cog, day_iso, slots, tz_name, page=0):
            options = []
            start = page * three.SLOTS_PER_PAGE
            for index, slot in enumerate(slots[:three.SLOTS_PER_PAGE], start=start + 1):
                members = three._slot_members(slot)
                waiting = three._slot_waiting(slot)
                extra = f" +{waiting}" if waiting else ""
                clock = local_clock(slot["start_ts"], tz_name)
                options.append(
                    discord.SelectOption(
                        label=f"{clock} • {members}/30{extra}",
                        value=str(slot["number"]),
                        description=(
                            "3 паті заповнені, далі лист очікування"
                            if members >= three.PARTIES_PER_TIME * three.MAX_MEMBERS
                            else f"Вільно {three.PARTIES_PER_TIME * three.MAX_MEMBERS - members} місць"
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
            self.day_iso = day_iso

        async def callback(self, interaction):
            await self.cog.add_times(interaction, self.day_iso, self.values)

    class ClockTimeView(discord.ui.View):
        def __init__(self, league_cog, day_iso, slots, tz_name, page=0):
            super().__init__(timeout=180)
            self.cog = league_cog
            self.day_iso = day_iso
            self.slots = slots
            self.tz_name = tz_name
            self.page = page

            start = page * three.SLOTS_PER_PAGE
            chunk = slots[start:start + three.SLOTS_PER_PAGE]
            if chunk:
                self.add_item(ClockTimeSelect(league_cog, day_iso, chunk, tz_name, page))

            all_btn = discord.ui.Button(
                label="Усі часи",
                emoji="✅",
                style=discord.ButtonStyle.success,
                row=1,
            )

            async def all_times(interaction):
                values = [str(x["number"]) for x in self.slots if x.get("enabled", True)]
                await self.cog.add_times(interaction, self.day_iso, values)

            all_btn.callback = all_times
            self.add_item(all_btn)

            if len(slots) > three.SLOTS_PER_PAGE:
                previous = discord.ui.Button(
                    label="Раніше",
                    style=discord.ButtonStyle.secondary,
                    disabled=page == 0,
                    row=2,
                )
                later = discord.ui.Button(
                    label="Пізніше",
                    style=discord.ButtonStyle.secondary,
                    disabled=(page + 1) * three.SLOTS_PER_PAGE >= len(slots),
                    row=2,
                )

                async def go_previous(interaction):
                    new_page = max(0, page - 1)
                    await interaction.response.edit_message(
                        content=self.cog.signup_text(self.day_iso, self.slots, new_page),
                        view=ClockTimeView(
                            self.cog,
                            self.day_iso,
                            self.slots,
                            self.tz_name,
                            new_page,
                        ),
                    )

                async def go_later(interaction):
                    new_page = page + 1
                    await interaction.response.edit_message(
                        content=self.cog.signup_text(self.day_iso, self.slots, new_page),
                        view=ClockTimeView(
                            self.cog,
                            self.day_iso,
                            self.slots,
                            self.tz_name,
                            new_page,
                        ),
                    )

                previous.callback = go_previous
                later.callback = go_later
                self.add_item(previous)
                self.add_item(later)

    async def begin_date_signup_with_clock(self, interaction, day_iso):
        event = self.event(day_iso)
        if not event:
            await interaction.response.send_message(
                "Ця реєстрація вже недоступна.", ephemeral=True
            )
            return

        uid = str(interaction.user.id)
        if not event.get("roles", {}).get(uid):
            await interaction.response.send_message(
                "Спочатку обери **Tank**, **DPS** або **Shai**.", ephemeral=True
            )
            return

        slots = [
            three._normalize_slot(slot)
            for slot in event.get("slots", [])
            if slot.get("enabled", True)
        ]
        if not slots:
            await interaction.response.send_message(
                "На цю дату немає доступних часів.", ephemeral=True
            )
            return

        tz_name = user_timezone(interaction.user.id)
        await interaction.response.send_message(
            self.signup_text(day_iso, slots, 0),
            view=ClockTimeView(self, day_iso, slots, tz_name, 0),
            ephemeral=True,
        )

    dated.GuildLeagueDatedPosts.begin_date_signup = begin_date_signup_with_clock

    # Також підміняємо глобальні класи у three-party модулі, щоб наступні
    # внутрішні виклики не повертали старе меню з №1, №2, №3 без часу.
    three.LocalTimeSelect = ClockTimeSelect
    three.LocalTimeView = ClockTimeView

    print("[GUILD_LEAGUE] signup dropdown now shows HH:MM in the user's saved timezone")
