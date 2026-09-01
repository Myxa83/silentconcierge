from __future__ import annotations

from datetime import datetime
import discord

SLOTS_PER_PAGE = 25
SLOTS_PER_COLUMN = 3
MAX_EMBEDS = 6


def _scheduled(state):
    return sorted(
        [p for p in state.get("packs", []) if p.get("start_ts")],
        key=lambda p: int(p["start_ts"]),
    )


def _date_key(ts, tz):
    return datetime.fromtimestamp(int(ts), tz).date().isoformat()


def _slot_block(league, party):
    count = league.member_count(party)
    waiting = league.waitlist_count(party)
    extra = f" +{waiting}" if waiting else ""
    enabled = party.get("enabled", True)
    prefix = "⏸️ " if not enabled else ""

    lines = [
        f"**{prefix}{party['number']}  {league.discord_time(party['start_ts'])} "
        f"({count}/{league.MAX_MEMBERS}{extra})**"
    ]

    for entry in party.get("members", []):
        lines.append(
            f"{league.role_text(entry.get('role'))} <@{entry['user_id']}>"
        )

    waitlist = party.get("waitlist", [])
    if waitlist:
        lines.append("— лист очікування —")
        for entry in waitlist:
            lines.append(
                f"{league.role_text(entry.get('role'))} <@{entry['user_id']}>"
            )

    pending = party.get("pending", [])
    if pending:
        lines.append(f"📥 Заявки: {len(pending)}")

    if not enabled:
        lines.append("🔒 запис закрито")

    return "\n".join(lines)


def _chunk_column(blocks):
    text = "\n\n".join(blocks)
    if len(text) <= 1024:
        return text or "—"
    return text[:1010].rstrip() + "\n…"


def _schedule_embeds(league, state, bot_user):
    parties = _scheduled(state)
    if not parties:
        embed = discord.Embed(
            description=(
                "Розклад ще не створено.\n"
                "PL: **Дії PL → Створити розклад на день**."
            ),
            color=league.COLOR,
        )
        if bot_user:
            embed.set_footer(
                text=league.FOOTER,
                icon_url=bot_user.display_avatar.url,
            )
        else:
            embed.set_footer(text=league.FOOTER)
        return [embed]

    embeds = []
    group_size = SLOTS_PER_COLUMN * 3
    for start in range(0, len(parties), group_size):
        group = parties[start:start + group_size]
        embed = discord.Embed(color=league.COLOR)
        columns = [
            group[i:i + SLOTS_PER_COLUMN]
            for i in range(0, len(group), SLOTS_PER_COLUMN)
        ]
        while len(columns) < 3:
            columns.append([])

        for column in columns[:3]:
            value = _chunk_column(
                [_slot_block(league, party) for party in column]
            )
            embed.add_field(
                name="\u200b",
                value=value,
                inline=True,
            )

        if start + group_size >= len(parties):
            if bot_user:
                embed.set_footer(
                    text=league.FOOTER,
                    icon_url=bot_user.display_avatar.url,
                )
            else:
                embed.set_footer(text=league.FOOTER)
        embeds.append(embed)

    return embeds[:MAX_EMBEDS]


def _header_embed(league, state):
    parties = _scheduled(state)
    pl = state.get("pl_user_id")
    pl_text = f"<@{pl}>" if pl else "не визначений"

    if not parties:
        return discord.Embed(
            title="Запис на Лігу гільдій",
            description=(
                "Обери **Tank / DPS / Shai**, потім **Записатися**. "
                "PL спочатку створює розклад на один день."
            ),
            color=league.COLOR,
        ).add_field(name="PL", value=pl_text, inline=True)

    first = parties[0]
    last = parties[-1]
    embed = discord.Embed(
        title="Запис на Лігу гільдій",
        description=(
            "Обери **Tank / DPS / Shai**, натисни **Записатися** "
            "і вибери потрібний час."
        ),
        color=league.COLOR,
    )
    embed.add_field(
        name="День",
        value=f"<t:{int(first['start_ts'])}:D>",
        inline=True,
    )
    embed.add_field(
        name="Початок",
        value=league.discord_time(first["start_ts"]),
        inline=True,
    )
    embed.add_field(
        name="Кінець",
        value=league.discord_time(last["start_ts"]),
        inline=True,
    )
    embed.add_field(name="PL", value=pl_text, inline=True)
    embed.add_field(
        name="Склад",
        value=f"{league.MIN_MEMBERS}-{league.MAX_MEMBERS}",
        inline=True,
    )
    embed.add_field(
        name="Інтервал",
        value="кожні 20 хв",
        inline=True,
    )
    return embed


def _summary_embed(league, state, bot_user):
    parties = _scheduled(state)
    embed = discord.Embed(color=league.COLOR)
    if not parties:
        embed.description = "Розклад ще не створено."
    else:
        lines = []
        for party in parties:
            count = league.member_count(party)
            waiting = league.waitlist_count(party)
            extra = f" +{waiting}" if waiting else ""
            mark = "⏸️" if not party.get("enabled", True) else "▫️"
            lines.append(
                f"{mark} **{party['number']}** "
                f"{league.discord_time(party['start_ts'])} "
                f"({count}/{league.MAX_MEMBERS}{extra})"
            )
        embed.description = "\n".join(lines)[:4096]
    if bot_user:
        embed.set_footer(
            text=league.FOOTER,
            icon_url=bot_user.display_avatar.url,
        )
    else:
        embed.set_footer(text=league.FOOTER)
    return embed


class DaySelect(discord.ui.Select):
    def __init__(self, league, cog):
        super().__init__(
            placeholder="Оберіть день розкладу",
            options=league.date_options(),
            min_values=1,
            max_values=1,
        )
        self.league = league
        self.cog = cog

    async def callback(self, interaction):
        await self.cog.create_day_schedule(interaction, self.values[0])


class DaySelectView(discord.ui.View):
    def __init__(self, league, cog):
        super().__init__(timeout=180)
        self.add_item(DaySelect(league, cog))


class TimeSignupSelect(discord.ui.Select):
    def __init__(self, league, cog, parties):
        options = []
        for party in parties[:SLOTS_PER_PAGE]:
            count = league.member_count(party)
            waiting = league.waitlist_count(party)
            extra = f" +{waiting}" if waiting else ""
            description = (
                "Повне - після схвалення у лист очікування"
                if count >= league.MAX_MEMBERS
                else "Обрати цей час"
            )
            options.append(
                discord.SelectOption(
                    label=(
                        f"{datetime.fromtimestamp(int(party['start_ts']), league.TZ):%H:%M} "
                        f"• {count}/{league.MAX_MEMBERS}{extra}"
                    )[:100],
                    value=str(party["number"]),
                    description=description[:100],
                )
            )
        super().__init__(
            placeholder="Оберіть час",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.cog = cog

    async def callback(self, interaction):
        await self.cog.signup_to(interaction, int(self.values[0]))


class SignupTimeView(discord.ui.View):
    def __init__(self, league, cog, parties, page=0):
        super().__init__(timeout=180)
        self.league = league
        self.cog = cog
        self.parties = parties
        self.page = page

        start = page * SLOTS_PER_PAGE
        chunk = parties[start:start + SLOTS_PER_PAGE]
        if chunk:
            self.add_item(TimeSignupSelect(league, cog, chunk))

        if len(parties) > SLOTS_PER_PAGE:
            prev_btn = discord.ui.Button(
                label="Раніше",
                style=discord.ButtonStyle.secondary,
                disabled=page == 0,
            )
            next_btn = discord.ui.Button(
                label="Пізніше",
                style=discord.ButtonStyle.secondary,
                disabled=(page + 1) * SLOTS_PER_PAGE >= len(parties),
            )

            async def previous(interaction):
                await interaction.response.edit_message(
                    content=self.cog.signup_prompt(self.parties, page - 1),
                    view=SignupTimeView(
                        self.league,
                        self.cog,
                        self.parties,
                        page - 1,
                    ),
                )

            async def next_page(interaction):
                await interaction.response.edit_message(
                    content=self.cog.signup_prompt(self.parties, page + 1),
                    view=SignupTimeView(
                        self.league,
                        self.cog,
                        self.parties,
                        page + 1,
                    ),
                )

            prev_btn.callback = previous
            next_btn.callback = next_page
            self.add_item(prev_btn)
            self.add_item(next_btn)


class SlotToggleSelect(discord.ui.Select):
    def __init__(self, league, cog, parties):
        options = []
        for party in parties[:SLOTS_PER_PAGE]:
            enabled = party.get("enabled", True)
            count = league.member_count(party)
            options.append(
                discord.SelectOption(
                    label=(
                        f"{datetime.fromtimestamp(int(party['start_ts']), league.TZ):%H:%M} "
                        f"• {'відкрито' if enabled else 'закрито'}"
                    )[:100],
                    value=str(party["number"]),
                    description=f"{count}/{league.MAX_MEMBERS} у складі",
                    emoji="🟢" if enabled else "⏸️",
                )
            )
        super().__init__(
            placeholder="Відкрити / закрити час",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.cog = cog

    async def callback(self, interaction):
        await self.cog.toggle_slot_day(interaction, int(self.values[0]))


class SlotToggleView(discord.ui.View):
    def __init__(self, league, cog, parties, page=0):
        super().__init__(timeout=180)
        self.league = league
        self.cog = cog
        self.parties = parties
        self.page = page

        start = page * SLOTS_PER_PAGE
        chunk = parties[start:start + SLOTS_PER_PAGE]
        if chunk:
            self.add_item(SlotToggleSelect(league, cog, chunk))

        if len(parties) > SLOTS_PER_PAGE:
            prev_btn = discord.ui.Button(
                label="Раніше",
                style=discord.ButtonStyle.secondary,
                disabled=page == 0,
            )
            next_btn = discord.ui.Button(
                label="Пізніше",
                style=discord.ButtonStyle.secondary,
                disabled=(page + 1) * SLOTS_PER_PAGE >= len(parties),
            )

            async def previous(interaction):
                await interaction.response.edit_message(
                    content=self.cog.slot_manage_prompt(
                        self.parties,
                        page - 1,
                    ),
                    view=SlotToggleView(
                        self.league,
                        self.cog,
                        self.parties,
                        page - 1,
                    ),
                )

            async def next_page(interaction):
                await interaction.response.edit_message(
                    content=self.cog.slot_manage_prompt(
                        self.parties,
                        page + 1,
                    ),
                    view=SlotToggleView(
                        self.league,
                        self.cog,
                        self.parties,
                        page + 1,
                    ),
                )

            prev_btn.callback = previous
            next_btn.callback = next_page
            self.add_item(prev_btn)
            self.add_item(next_btn)


async def setup(bot):
    from cogs import guild_league_cog as league

    if getattr(league, "_day_schedule_installed", False):
        return
    league._day_schedule_installed = True
    league.MAX_PARTIES = 40

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][DAY] GuildLeagueCog not found")
        return

    league.header_embed = lambda state: _header_embed(league, state)
    league.parties_embed = (
        lambda state, bot_user:
        _summary_embed(league, state, bot_user)
    )

    class DayPLMenu(discord.ui.Select):
        def __init__(self, league_cog):
            actions = [
                ("🔄", "Оновити повідомлення", "refresh"),
                ("💤", "Пінг відсутніх у голосовому", "ping_missing_voice"),
                ("🔔", "Пінг усіх учасників наступного паті", "ping_all_next"),
                ("👋", "Пінг тих, хто не відповів", "ping_no_response"),
                ("📝", "Порядок запису", "signup_order"),
                ("🗓️", "Керування слотами", "slots"),
                ("📆", "Створити розклад на день", "create"),
                ("✅", "Прийняти заявку", "approve"),
                ("❌", "Відхилити заявку", "reject"),
                ("📋", "Переглянути заявки", "pending"),
                ("🗑️", "Видалити учасника", "remove"),
                ("📅", "Змінити день / час слота", "reschedule"),
                ("👑", "Передати PL", "transfer"),
                ("⛔", "Скасувати слот", "cancel"),
            ]
            super().__init__(
                placeholder="Дії PL",
                custom_id="guild_league_pl_actions",
                row=3,
                options=[
                    discord.SelectOption(
                        emoji=emoji,
                        label=label,
                        value=value,
                    )
                    for emoji, label, value in actions
                ],
            )
            self.cog = league_cog

        async def callback(self, interaction):
            await self.cog.pl_action(interaction, self.values[0])

    league.PLMenu = DayPLMenu

    async def refresh_day(self):
        message = await self.panel_message()
        if not message:
            return

        embeds = [_header_embed(league, self.state)]
        embeds.extend(
            _schedule_embeds(
                league,
                self.state,
                self.bot.user,
            )
        )
        await message.edit(
            content=None,
            embeds=embeds[:10],
            view=league.MainView(self),
        )

    league.GuildLeagueCog.refresh = refresh_day

    async def begin_create_day(self, interaction):
        if not self.is_pl(interaction):
            await interaction.response.send_message(
                "Тільки PL може створювати розклад.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            (
                "**Створити розклад на один день**\n"
                "Обери день. Бот одразу створить усі доступні "
                "слоти з інтервалом 20 хв."
            ),
            view=DaySelectView(league, self),
            ephemeral=True,
        )

    league.GuildLeagueCog.begin_create = begin_create_day

    async def create_day_schedule(self, interaction, day_iso):
        if not self.is_pl(interaction):
            await interaction.response.edit_message(
                content="Ти більше не PL.",
                view=None,
            )
            return

        slots = league.time_slots(day_iso)
        if not slots:
            await interaction.response.edit_message(
                content="На цей день уже немає доступних майбутніх слотів.",
                view=None,
            )
            return

        existing_by_ts = {
            int(p["start_ts"]): p
            for p in self.state.get("packs", [])
            if p.get("start_ts")
        }

        old_active = list(self.state.get("packs", []))
        new_ts = {int(ts) for _label, ts in slots}
        history = self.state.setdefault("history", [])

        for old in old_active:
            ts = old.get("start_ts")
            if not ts or int(ts) in new_ts:
                continue
            if (
                old.get("members")
                or old.get("waitlist")
                or old.get("pending")
            ):
                archived = dict(old)
                archived["archived_at"] = int(
                    datetime.now(league.TZ).timestamp()
                )
                history.append(archived)

        new_parties = []
        for number, (_label, ts) in enumerate(slots, 1):
            previous = existing_by_ts.get(int(ts))
            if previous:
                previous = dict(previous)
                previous["number"] = number
                previous.setdefault("enabled", True)
                previous.setdefault("members", [])
                previous.setdefault("waitlist", [])
                previous.setdefault("pending", [])
                new_parties.append(previous)
            else:
                new_parties.append(
                    {
                        "number": number,
                        "start_ts": int(ts),
                        "enabled": True,
                        "members": [],
                        "waitlist": [],
                        "pending": [],
                    }
                )

        self.state["packs"] = new_parties
        self.state["schedule_day"] = day_iso
        self.state["history"] = history[-100:]
        self.state["responses"] = {}
        self.save()
        await self.refresh()

        first = new_parties[0]
        last = new_parties[-1]
        await interaction.response.edit_message(
            content=(
                f"✅ Розклад створено на <t:{int(first['start_ts'])}:D>.\n"
                f"Слоти: **{len(new_parties)}** • "
                f"{league.discord_time(first['start_ts'])} - "
                f"{league.discord_time(last['start_ts'])}\n"
                "Люди тепер натискають **Записатися** і обирають час."
            ),
            view=None,
        )

    league.GuildLeagueCog.create_day_schedule = create_day_schedule

    def signup_prompt(self, parties, page):
        start = page * SLOTS_PER_PAGE
        chunk = parties[start:start + SLOTS_PER_PAGE]
        first = chunk[0]
        last = chunk[-1]
        return (
            "**Обери час:**\n"
            f"{league.discord_date_time(first['start_ts'])} - "
            f"{league.discord_time(last['start_ts'])}\n"
            "Якщо потрібного часу немає на цій сторінці, "
            "натисни **Раніше / Пізніше**."
        )

    league.GuildLeagueCog.signup_prompt = signup_prompt

    async def begin_signup_day(self, interaction):
        if not await self.ok_channel(interaction):
            return

        uid = str(interaction.user.id)
        if not self.state.get("roles", {}).get(uid):
            await interaction.response.send_message(
                "Спочатку обери **Tank**, **DPS** або **Shai**.",
                ephemeral=True,
            )
            return

        parties = [
            p
            for p in _scheduled(self.state)
            if p.get("enabled", True)
        ]
        if not parties:
            await interaction.response.send_message(
                "Зараз немає відкритих слотів для запису.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            self.signup_prompt(parties, 0),
            view=SignupTimeView(league, self, parties, 0),
            ephemeral=True,
        )

    league.GuildLeagueCog.begin_signup = begin_signup_day

    def slot_manage_prompt(self, parties, page):
        start = page * SLOTS_PER_PAGE
        chunk = parties[start:start + SLOTS_PER_PAGE]
        lines = []
        for party in chunk:
            status = (
                "🟢 відкрито"
                if party.get("enabled", True)
                else "⏸️ закрито"
            )
            lines.append(
                f"{league.discord_time(party['start_ts'])} • {status}"
            )
        return (
            "**Керування слотами**\n"
            + "\n".join(lines)
            + "\n\nОбери час, щоб відкрити або закрити запис."
        )

    league.GuildLeagueCog.slot_manage_prompt = slot_manage_prompt

    async def begin_manage_slots_day(self, interaction):
        if not self.is_pl(interaction):
            await interaction.response.send_message(
                "Це меню доступне тільки PL.",
                ephemeral=True,
            )
            return

        parties = _scheduled(self.state)
        if not parties:
            await interaction.response.send_message(
                "Розклад ще не створено.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            self.slot_manage_prompt(parties, 0),
            view=SlotToggleView(league, self, parties, 0),
            ephemeral=True,
        )

    league.GuildLeagueCog.begin_manage_slots = begin_manage_slots_day

    async def toggle_slot_day(self, interaction, number):
        if not self.is_pl(interaction):
            await interaction.response.edit_message(
                content="Ти більше не PL.",
                view=None,
            )
            return

        party = league.get_party(self.state, number)
        if not party:
            await interaction.response.edit_message(
                content="Цього слота вже немає.",
                view=None,
            )
            return

        party["enabled"] = not party.get("enabled", True)
        self.save()
        await self.refresh()

        parties = _scheduled(self.state)
        index = next(
            (
                i
                for i, p in enumerate(parties)
                if int(p["number"]) == int(number)
            ),
            0,
        )
        page = index // SLOTS_PER_PAGE
        await interaction.response.edit_message(
            content=self.slot_manage_prompt(parties, page),
            view=SlotToggleView(
                league,
                self,
                parties,
                page,
            ),
        )

    league.GuildLeagueCog.toggle_slot_day = toggle_slot_day

    previous_pl_action = league.GuildLeagueCog.pl_action

    async def pl_action_day(self, interaction, action):
        if action == "create":
            if not await self.ok_channel(interaction):
                return
            await self.begin_create(interaction)
            return
        if action == "slots":
            if not await self.ok_channel(interaction):
                return
            await self.begin_manage_slots(interaction)
            return
        return await previous_pl_action(self, interaction, action)

    league.GuildLeagueCog.pl_action = pl_action_day

    try:
        await cog.refresh()
    except Exception as exc:
        print(
            f"[GUILD_LEAGUE][DAY][REFRESH] "
            f"{type(exc).__name__}: {exc}"
        )

    print(
        "[GUILD_LEAGUE] day schedule enabled: "
        "full-day 20-minute slots, signup by time"
    )
