from __future__ import annotations

from datetime import datetime

import discord


async def setup(bot):
    """Спрощений запис без підтвердження PL."""
    from cogs import guild_league_cog as league
    from cogs import guild_league_zz_day_schedule_cog as day

    if getattr(league, "_direct_signup_installed", False):
        return
    league._direct_signup_installed = True

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][DIRECT] GuildLeagueCog not found")
        return

    # Старі заявки більше не потребують схвалення.
    migrated = 0
    for party in cog.state.get("packs", []):
        pending = list(party.get("pending", []))
        if not pending:
            continue
        party["pending"] = []
        for entry in pending:
            if league.member_count(party) < league.MAX_MEMBERS:
                party.setdefault("members", []).append(entry)
            else:
                party.setdefault("waitlist", []).append(entry)
            migrated += 1
    if migrated:
        cog.save()

    def direct_slot_block(module, party):
        count = module.member_count(party)
        waiting = module.waitlist_count(party)
        extra = f" +{waiting}" if waiting else ""
        enabled = party.get("enabled", True)
        prefix = "⏸️ " if not enabled else ""

        lines = [
            f"**{prefix}{party['number']}  {module.discord_time(party['start_ts'])} "
            f"({count}/{module.MAX_MEMBERS}{extra})**"
        ]
        for entry in party.get("members", []):
            lines.append(
                f"{module.role_text(entry.get('role'))} <@{entry['user_id']}>"
            )

        waitlist = party.get("waitlist", [])
        if waitlist:
            lines.append("— лист очікування —")
            for entry in waitlist:
                lines.append(
                    f"{module.role_text(entry.get('role'))} <@{entry['user_id']}>"
                )

        if not enabled:
            lines.append("🔒 запис закрито")
        return "\n".join(lines)

    day._slot_block = direct_slot_block

    original_header = day._header_embed

    def direct_header(module, state):
        embed = original_header(module, state)
        if day._scheduled(state):
            embed.description = (
                "Обери **Tank / DPS / Shai**, натисни **Записатися** "
                "і вибери потрібний час. **Підтвердження PL не потрібне.** "
                "Перші 10 людей потрапляють у склад, далі - у лист очікування."
            )
        else:
            embed.description = (
                "PL створює розклад на день. Потім люди обирають "
                "**Tank / DPS / Shai**, натискають **Записатися** і час. "
                "Підтвердження PL не потрібне."
            )
        return embed

    day._header_embed = direct_header
    league.header_embed = lambda state: direct_header(league, state)

    class DirectTimeSignupSelect(discord.ui.Select):
        def __init__(self, module, league_cog, parties):
            options = []
            for party in parties[: day.SLOTS_PER_PAGE]:
                count = module.member_count(party)
                waiting = module.waitlist_count(party)
                extra = f" +{waiting}" if waiting else ""
                description = (
                    "Повне - одразу в лист очікування"
                    if count >= module.MAX_MEMBERS
                    else "Записатися на цей час"
                )
                options.append(
                    discord.SelectOption(
                        label=(
                            f"{datetime.fromtimestamp(int(party['start_ts']), module.TZ):%H:%M} "
                            f"• {count}/{module.MAX_MEMBERS}{extra}"
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
            self.cog = league_cog

        async def callback(self, interaction):
            await self.cog.signup_to(interaction, int(self.values[0]))

    day.TimeSignupSelect = DirectTimeSignupSelect

    class DirectPLMenu(discord.ui.Select):
        def __init__(self, league_cog):
            actions = [
                ("🔄", "Оновити повідомлення", "refresh"),
                ("💤", "Пінг відсутніх у голосовому", "ping_missing_voice"),
                ("🔔", "Пінг усіх учасників наступного паті", "ping_all_next"),
                ("👋", "Пінг тих, хто не відповів", "ping_no_response"),
                ("📝", "Порядок запису", "signup_order"),
                ("🗓️", "Керування слотами", "slots"),
                ("📆", "Створити розклад на день", "create"),
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
                    discord.SelectOption(emoji=e, label=l, value=v)
                    for e, l, v in actions
                ],
            )
            self.cog = league_cog

        async def callback(self, interaction):
            await self.cog.pl_action(interaction, self.values[0])

    league.PLMenu = DirectPLMenu

    async def signup_to_direct(self, interaction, number):
        async with self.lock:
            party = league.get_party(self.state, number)
            uid = str(interaction.user.id)
            role_key = self.state.get("roles", {}).get(uid)

            if not party or not party.get("start_ts"):
                await interaction.response.edit_message(
                    content="Цей час уже недоступний.",
                    view=None,
                )
                return
            if not party.get("enabled", True):
                await interaction.response.edit_message(
                    content="Запис на цей час закритий PL.",
                    view=None,
                )
                return
            if not role_key:
                await interaction.response.edit_message(
                    content="Спочатку обери **Tank**, **DPS** або **Shai**.",
                    view=None,
                )
                return

            current_party, current_kind = league.find_user(self.state, uid)
            if current_party is party:
                status = (
                    "в основному складі"
                    if current_kind == "members"
                    else "у листі очікування"
                )
                await interaction.response.edit_message(
                    content=(
                        f"Ти вже {status} на "
                        f"{league.discord_date_time(party['start_ts'])}."
                    ),
                    view=None,
                )
                return

            promoted = None
            if current_party:
                _removed, promoted = league.remove_user_from_party(
                    current_party,
                    uid,
                )

            entry = {
                "user_id": uid,
                "role": role_key,
                "signed_at": int(datetime.now(league.TZ).timestamp()),
            }

            for kind in ("members", "waitlist", "pending"):
                party[kind] = [
                    item
                    for item in party.get(kind, [])
                    if str(item.get("user_id")) != uid
                ]

            if league.member_count(party) < league.MAX_MEMBERS:
                party.setdefault("members", []).append(entry)
                destination = "склад"
                text = (
                    f"✅ Записано в **основний склад** "
                    f"({league.member_count(party)}/{league.MAX_MEMBERS})."
                )
            else:
                party.setdefault("waitlist", []).append(entry)
                destination = "лист очікування"
                text = (
                    f"✅ Основний склад уже 10/10. Тебе додано в "
                    f"**лист очікування** (+{league.waitlist_count(party)})."
                )

            self.state.setdefault("responses", {})[uid] = "signup"
            self.save()
            await self.refresh()

            if promoted and current_party:
                await self.send_promotion_notice(current_party, promoted)

        await interaction.response.edit_message(
            content=(
                f"{text}\n"
                f"🕒 {league.discord_date_time(party['start_ts'])}\n"
                f"Роль: **{league.role_text(role_key)}**"
            ),
            view=None,
        )
        print(
            f"[GUILD_LEAGUE][DIRECT] {uid} -> slot {number} -> {destination}"
        )

    league.GuildLeagueCog.signup_to = signup_to_direct

    async def help_direct(self, interaction):
        if not await self.ok_channel(interaction):
            return
        await interaction.response.send_message(
            (
                "**Як записатися:**\n"
                "1. Обери **Tank**, **DPS** або **Shai**.\n"
                "2. Натисни **Записатися**.\n"
                "3. Обери потрібний час.\n\n"
                "Все. **PL нічого не підтверджує.** До 10 людей "
                "записуються одразу в основний склад. Якщо вже 10/10, "
                "наступні автоматично потрапляють у **лист очікування**.\n"
                "Коли місце звільняється, перший у листі очікування "
                "автоматично переходить у склад.\n\n"
                "**Не можу** скасовує твій запис."
            ),
            ephemeral=True,
        )

    league.GuildLeagueCog.help = help_direct

    previous_pl_action = league.GuildLeagueCog.pl_action

    async def pl_action_direct(self, interaction, action):
        if action in {"approve", "reject", "pending"}:
            if not await self.ok_channel(interaction):
                return
            await interaction.response.send_message(
                "Підтвердження заявок вимкнено. Люди записуються одразу.",
                ephemeral=True,
            )
            return
        return await previous_pl_action(self, interaction, action)

    league.GuildLeagueCog.pl_action = pl_action_direct

    try:
        await cog.refresh()
    except Exception as exc:
        print(
            f"[GUILD_LEAGUE][DIRECT][REFRESH] "
            f"{type(exc).__name__}: {exc}"
        )

    print(
        "[GUILD_LEAGUE] direct signup enabled: "
        "role + time -> members, then waitlist; no PL approval"
    )
