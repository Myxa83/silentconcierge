from __future__ import annotations

import json
from datetime import datetime

import discord


VALID_RESPONSE_STATES = {"signup", "cant"}


def _clean_entry(item, roles):
    if not isinstance(item, dict):
        return None
    uid = str(item.get("user_id") or "")
    if not uid:
        return None
    role = item.get("role")
    if role not in roles:
        role = None
    signed_at = item.get("signed_at")
    try:
        signed_at = int(signed_at) if signed_at is not None else None
    except (TypeError, ValueError):
        signed_at = None
    return {
        "user_id": uid,
        "role": role,
        "signed_at": signed_at,
    }


def _clean_entries(value, roles):
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        entry = _clean_entry(item, roles)
        if not entry or entry["user_id"] in seen:
            continue
        result.append(entry)
        seen.add(entry["user_id"])
    return result


def _normalize_state(league, raw):
    if not isinstance(raw, dict):
        raw = {}

    state = league.fresh_state()
    state["channel_id"] = raw.get("channel_id", league.CHANNEL_ID)
    state["message_id"] = raw.get("message_id")
    state["pl_user_id"] = raw.get("pl_user_id")
    state["history"] = raw.get("history", []) if isinstance(raw.get("history"), list) else []

    if not state["pl_user_id"]:
        for old_party in raw.get("packs", []):
            if isinstance(old_party, dict) and old_party.get("leader_id"):
                state["pl_user_id"] = str(old_party["leader_id"])
                break
    elif state["pl_user_id"] is not None:
        state["pl_user_id"] = str(state["pl_user_id"])

    clean_roles = {}
    for uid, role in (raw.get("roles") or {}).items():
        if role in league.ROLES:
            clean_roles[str(uid)] = role
    state["roles"] = clean_roles

    responses = {}
    for uid, response in (raw.get("responses") or {}).items():
        if response in VALID_RESPONSE_STATES:
            responses[str(uid)] = response

    parties = []
    raw_parties = raw.get("packs", [])
    if not isinstance(raw_parties, list):
        raw_parties = []

    for index, raw_party in enumerate(raw_parties[: league.MAX_PARTIES], 1):
        if not isinstance(raw_party, dict):
            continue

        members = _clean_entries(raw_party.get("members"), league.ROLES)[: league.MAX_MEMBERS]
        member_ids = {x["user_id"] for x in members}

        waitlist = [
            x
            for x in _clean_entries(raw_party.get("waitlist"), league.ROLES)
            if x["user_id"] not in member_ids
        ]
        occupied = member_ids | {x["user_id"] for x in waitlist}

        pending = [
            x
            for x in _clean_entries(raw_party.get("pending"), league.ROLES)
            if x["user_id"] not in occupied
        ]

        for entry in members + waitlist + pending:
            responses.setdefault(entry["user_id"], "signup")

        parties.append(
            {
                "number": index,
                "start_ts": raw_party.get("start_ts"),
                "enabled": bool(raw_party.get("enabled", True)),
                "members": members,
                "waitlist": waitlist,
                "pending": pending,
            }
        )

    state["packs"] = parties
    state["responses"] = responses
    return state


def _slot_lines(league, state):
    lines = []
    for party in state.get("packs", []):
        if not party.get("start_ts"):
            continue
        status = "🟢 відкрито" if party.get("enabled", True) else "⏸️ закрито"
        lines.append(
            f"**Паті {party['number']}** • "
            f"{league.discord_date_time(party['start_ts'])} • {status}"
        )
    return lines


def _slot_options(league, state):
    options = []
    for party in state.get("packs", []):
        if not party.get("start_ts"):
            continue
        enabled = party.get("enabled", True)
        options.append(
            discord.SelectOption(
                label=(
                    f"Паті {party['number']} • "
                    f"{'відкрито' if enabled else 'закрито'}"
                )[:100],
                value=str(party["number"]),
                description=(
                    "Закрити запис у цей слот"
                    if enabled
                    else "Відкрити запис у цей слот"
                ),
                emoji="🟢" if enabled else "⏸️",
            )
        )
    return options


def _signup_order_lines(league, party):
    entries = []
    labels = (
        ("members", "у складі"),
        ("waitlist", "лист очікування"),
        ("pending", "заявка"),
    )
    seq = 0
    for kind, label in labels:
        for entry in party.get(kind, []):
            seq += 1
            signed_at = entry.get("signed_at")
            try:
                signed_at = int(signed_at) if signed_at is not None else None
            except (TypeError, ValueError):
                signed_at = None
            entries.append(
                (
                    signed_at if signed_at is not None else 10**20,
                    seq,
                    entry,
                    label,
                )
            )

    entries.sort(key=lambda item: (item[0], item[1]))

    lines = []
    for index, (_, _, entry, label) in enumerate(entries, 1):
        signed_at = entry.get("signed_at")
        time_text = (
            f"<t:{int(signed_at)}:T>"
            if signed_at is not None
            else "час невідомий"
        )
        lines.append(
            f"**{index:02}.** {time_text} • "
            f"{league.role_text(entry.get('role'))} "
            f"<@{entry['user_id']}> • {label}"
        )
    return lines


async def setup(bot):
    from cogs import guild_league_cog as league

    if getattr(league, "_management_installed", False):
        return
    league._management_installed = True

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][MANAGEMENT] GuildLeagueCog not found")
        return

    original_load_state = league.load_state

    def load_state_v2():
        league.DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not league.DATA_FILE.exists():
            state = league.fresh_state()
            state["responses"] = {}
            return state

        try:
            raw = json.loads(league.DATA_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            print(
                f"[GUILD_LEAGUE][MANAGEMENT][LOAD] "
                f"{type(exc).__name__}: {exc}"
            )
            raw = original_load_state()

        return _normalize_state(league, raw)

    league.load_state = load_state_v2
    cog.state = load_state_v2()
    league.save_state(cog.state)

    def party_field_ua(party, number):
        if not party:
            return f"Паті {number}  Не створено", "-"

        ts = party.get("start_ts")
        members = league.member_count(party)
        waiting = league.waitlist_count(party)
        extra = f" +{waiting}" if waiting else ""
        enabled = party.get("enabled", True)

        if ts:
            prefix = "⏸️ " if not enabled else ""
            name = (
                f"{prefix}{number}  {league.discord_time(ts)} "
                f"({members}/{league.MAX_MEMBERS}{extra})"
            )
        else:
            name = (
                f"{number}  Час не обраний "
                f"({members}/{league.MAX_MEMBERS}{extra})"
            )

        lines = [
            f"{league.role_text(member.get('role'))} <@{member['user_id']}>"
            for member in party.get("members", [])
        ]

        waitlist = party.get("waitlist", [])
        if waitlist:
            lines.append("- лист очікування -")
            lines.extend(
                f"{league.role_text(member.get('role'))} <@{member['user_id']}>"
                for member in waitlist
            )

        pending_count = len(party.get("pending", []))
        if pending_count:
            lines.append(f"📥 Заявки: {pending_count}")

        if not lines:
            lines.append("- порожньо -")

        if not enabled and ts:
            lines.append("🔒 Запис у цей слот закрито PL")

        if ts:
            icon = "⏸️" if not enabled else league.status_icon(party)
            lines.append(
                f"\n{icon} {league.discord_date_time(ts)}"
            )

        return name[:256], "\n".join(lines)[:1024]

    league.party_field = party_field_ua

    original_select_callback = league.Select.callback

    async def select_callback(self, interaction):
        value = self.values[0]
        if self.kind == "slot_toggle":
            await self.cog.toggle_slot(interaction, int(value))
            return
        if self.kind == "signup_order_party":
            await self.cog.show_signup_order(
                interaction,
                int(value),
                edit=True,
            )
            return
        await original_select_callback(self, interaction)

    league.Select.callback = select_callback

    class ManagementPLMenu(discord.ui.Select):
        def __init__(self, league_cog):
            actions = [
                ("🔄", "Оновити повідомлення", "refresh"),
                ("👋", "Пінг тих, хто не відповів", "ping_no_response"),
                ("📝", "Порядок запису", "signup_order"),
                ("🗓️", "Керування слотами", "slots"),
                ("➕", "Створити наступне паті", "create"),
                ("✅", "Прийняти заявку", "approve"),
                ("❌", "Відхилити заявку", "reject"),
                ("📋", "Переглянути заявки", "pending"),
                ("🗑️", "Видалити учасника", "remove"),
                ("📅", "Змінити день / час", "reschedule"),
                ("👑", "Передати PL", "transfer"),
                ("⛔", "Скасувати паті", "cancel"),
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

    league.PLMenu = ManagementPLMenu

    async def send_promotion_notice_ua(self, party, promoted):
        if not promoted or not party.get("start_ts"):
            return
        channel = (
            self.bot.get_channel(league.CHANNEL_ID)
            or await self.bot.fetch_channel(league.CHANNEL_ID)
        )
        await channel.send(
            (
                f"<@{promoted['user_id']}> місце звільнилося в "
                f"**Паті {party['number']}**. "
                "Тебе автоматично перенесено з листа очікування "
                "в основний склад.\n"
                f"🕒 {league.discord_date_time(party['start_ts'])}"
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )

    league.GuildLeagueCog.send_promotion_notice = send_promotion_notice_ua

    async def begin_signup(self, interaction):
        if not await self.ok_channel(interaction):
            return

        uid = str(interaction.user.id)
        role_key = self.state["roles"].get(uid)
        if not role_key:
            await interaction.response.send_message(
                "Спочатку обери **Tank**, **DPS** або **Shai**.",
                ephemeral=True,
            )
            return

        current_party, _ = league.find_user(self.state, uid)
        scheduled = [
            p for p in self.state.get("packs", [])
            if p.get("start_ts")
        ]
        available = [
            p for p in scheduled
            if p.get("enabled", True)
        ]

        if not available:
            text = (
                "Усі створені слоти зараз закриті PL."
                if scheduled
                else "Зараз немає створеного паті з обраним часом."
            )
            await interaction.response.send_message(
                text,
                ephemeral=True,
            )
            return

        lines = []
        options = []
        for party in available:
            number = party["number"]
            count = league.member_count(party)
            waiting = league.waitlist_count(party)
            marker = " • зараз тут" if current_party is party else ""
            full = count >= league.MAX_MEMBERS
            extra = f" +{waiting}" if waiting else ""
            lines.append(
                f"**{number}.** "
                f"{league.discord_date_time(party['start_ts'])} "
                f"• {count}/{league.MAX_MEMBERS}{extra}{marker}"
            )
            options.append(
                discord.SelectOption(
                    label=(
                        f"Паті {number} • "
                        f"{count}/{league.MAX_MEMBERS}{extra}"
                    ),
                    value=str(number),
                    description=(
                        "Повне - після схвалення в лист очікування"
                        if full
                        else "Обрати це паті"
                    ),
                )
            )

        await interaction.response.send_message(
            "\n".join(lines) + "\n\n**Обери паті:**",
            view=league.OneSelectView(
                league.Select(
                    self,
                    "party_signup",
                    options,
                    placeholder="Паті",
                )
            ),
            ephemeral=True,
        )

    league.GuildLeagueCog.begin_signup = begin_signup

    async def signup_to(self, interaction, number):
        async with self.lock:
            party = league.get_party(self.state, number)
            uid = str(interaction.user.id)
            role_key = self.state["roles"].get(uid)

            if not party or not party.get("start_ts"):
                await interaction.response.edit_message(
                    content="Це паті вже недоступне.",
                    view=None,
                )
                return
            if not party.get("enabled", True):
                await interaction.response.edit_message(
                    content=(
                        f"Запис у **Паті {number}** зараз закритий PL."
                    ),
                    view=None,
                )
                return
            if not role_key:
                await interaction.response.edit_message(
                    content="Спочатку обери роль.",
                    view=None,
                )
                return

            current_party, current_kind = league.find_user(
                self.state,
                uid,
            )
            if current_party is party:
                status = {
                    "members": "у складі",
                    "waitlist": "у листі очікування",
                    "pending": "подав заявку",
                }.get(current_kind, "записаний")
                await interaction.response.edit_message(
                    content=(
                        f"Ти вже {status} **Паті {number}**.\n"
                        f"🕒 "
                        f"{league.discord_date_time(party['start_ts'])}"
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

            party["pending"] = [
                x
                for x in party.get("pending", [])
                if str(x.get("user_id")) != uid
            ]
            party["pending"].append(
                {
                    "user_id": uid,
                    "role": role_key,
                    "signed_at": int(
                        datetime.now(league.TZ).timestamp()
                    ),
                }
            )

            self.state.setdefault("responses", {})[uid] = "signup"
            self.save()
            await self.refresh()

            if promoted:
                await self.send_promotion_notice(
                    current_party,
                    promoted,
                )

            channel = (
                self.bot.get_channel(league.CHANNEL_ID)
                or await self.bot.fetch_channel(league.CHANNEL_ID)
            )
            pl = self.state.get("pl_user_id")
            if pl:
                await channel.send(
                    (
                        f"<@{pl}> нова заявка в **Паті {number}**\n"
                        f"{league.role_text(role_key)} <@{uid}> • "
                        f"{league.discord_date_time(party['start_ts'])}"
                    ),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )

        await interaction.response.edit_message(
            content=(
                f"✅ Заявку в **Паті {number}** надіслано.\n"
                f"🕒 {league.discord_date_time(party['start_ts'])}\n"
                f"Роль: **{league.role_text(role_key)}**"
            ),
            view=None,
        )

    league.GuildLeagueCog.signup_to = signup_to

    async def leave_or_cant(self, interaction):
        if not await self.ok_channel(interaction):
            return

        uid = str(interaction.user.id)
        party, kind = league.find_user(self.state, uid)
        promoted = None

        if party:
            number = party["number"]
            removed_kind, promoted = league.remove_user_from_party(
                party,
                uid,
            )
            self.state.setdefault("responses", {})[uid] = "cant"
            self.save()
            await self.refresh()

            if promoted:
                await self.send_promotion_notice(party, promoted)

            if removed_kind == "waitlist":
                text = (
                    f"Позначено **Не можу**. "
                    f"Тебе прибрано з листа очікування "
                    f"**Паті {number}**."
                )
            elif removed_kind == "pending":
                text = (
                    f"Позначено **Не можу**. "
                    f"Твою заявку в **Паті {number}** скасовано."
                )
            else:
                text = (
                    f"Позначено **Не можу**. "
                    f"Тебе прибрано зі складу **Паті {number}**."
                )
        else:
            self.state.setdefault("responses", {})[uid] = "cant"
            self.save()
            text = (
                "Позначено **Не можу**. "
                "PL бачитиме, що ти вже відповів."
            )

        await interaction.response.send_message(
            text,
            ephemeral=True,
        )

    league.GuildLeagueCog.leave = leave_or_cant

    async def help_ua(self, interaction):
        if not await self.ok_channel(interaction):
            return
        await interaction.response.send_message(
            (
                "**Як записатися:**\n"
                "1. Обери **Tank**, **DPS** або **Shai**.\n"
                "2. Натисни **Записатися**.\n"
                "3. Обери паті з потрібним часом.\n\n"
                "PL підтверджує заявку. Якщо склад уже 10/10, "
                "підтверджена заявка переходить у **лист очікування**. "
                "Коли місце звільняється, перший у листі очікування "
                "автоматично переходить у склад.\n\n"
                "**Не можу** скасовує заявку або участь і одночасно "
                "позначає, що ти вже відповів щодо Ліги.\n"
                "Закритий PL слот лишається видимим, але нові заявки "
                "в нього не приймаються.\n"
                "Час Discord автоматично показується у твоєму "
                "часовому поясі."
            ),
            ephemeral=True,
        )

    league.GuildLeagueCog.help = help_ua

    async def begin_manage_slots(self, interaction):
        if not self.is_pl(interaction):
            await interaction.response.send_message(
                "Це меню доступне тільки PL.",
                ephemeral=True,
            )
            return

        options = _slot_options(league, self.state)
        lines = _slot_lines(league, self.state)
        if not options:
            await interaction.response.send_message(
                "Ще немає створених слотів із часом.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            (
                "**Керування слотами**\n"
                + "\n".join(lines)
                + "\n\nОбери паті, щоб **закрити або відкрити запис**."
            ),
            view=league.OneSelectView(
                league.Select(
                    self,
                    "slot_toggle",
                    options,
                    placeholder="Змінити стан слота",
                )
            ),
            ephemeral=True,
        )

    league.GuildLeagueCog.begin_manage_slots = begin_manage_slots

    async def toggle_slot(self, interaction, number):
        if not self.is_pl(interaction):
            await interaction.response.edit_message(
                content="Ти більше не PL.",
                view=None,
            )
            return

        party = league.get_party(self.state, number)
        if not party or not party.get("start_ts"):
            await interaction.response.edit_message(
                content="Цього слота вже немає.",
                view=None,
            )
            return

        party["enabled"] = not party.get("enabled", True)
        self.save()
        await self.refresh()

        options = _slot_options(league, self.state)
        lines = _slot_lines(league, self.state)
        state_text = (
            "відкрито"
            if party["enabled"]
            else "закрито"
        )
        await interaction.response.edit_message(
            content=(
                f"**Паті {number}: запис {state_text}.**\n\n"
                "**Керування слотами**\n"
                + "\n".join(lines)
                + "\n\nОбери інше паті, якщо треба змінити його стан."
            ),
            view=(
                league.OneSelectView(
                    league.Select(
                        self,
                        "slot_toggle",
                        options,
                        placeholder="Змінити стан слота",
                    )
                )
                if options
                else None
            ),
        )

    league.GuildLeagueCog.toggle_slot = toggle_slot

    async def show_signup_order(self, interaction, number, edit=False):
        party = league.get_party(self.state, number)
        if not party:
            text = "Паті вже немає."
        else:
            lines = _signup_order_lines(league, party)
            if not lines:
                text = f"У **Паті {number}** ще немає записів."
            else:
                body = "\n".join(lines)
                if len(body) > 1700:
                    body = body[:1690] + "\n…"
                text = (
                    f"**Паті {number} • порядок запису**\n"
                    f"{league.discord_date_time(party['start_ts'])}\n\n"
                    f"{body}"
                )

        if edit:
            await interaction.response.edit_message(
                content=text,
                view=None,
            )
        else:
            await interaction.response.send_message(
                text,
                ephemeral=True,
            )

    league.GuildLeagueCog.show_signup_order = show_signup_order

    async def begin_signup_order(self, interaction):
        parties = [
            p for p in self.state.get("packs", [])
            if p.get("start_ts")
            and (
                p.get("members")
                or p.get("waitlist")
                or p.get("pending")
            )
        ]
        if not parties:
            await interaction.response.send_message(
                "Ще немає записів для перегляду.",
                ephemeral=True,
            )
            return

        if len(parties) == 1:
            await self.show_signup_order(
                interaction,
                parties[0]["number"],
                edit=False,
            )
            return

        options = [
            discord.SelectOption(
                label=f"Паті {p['number']}",
                value=str(p["number"]),
                description=(
                    f"{league.member_count(p)}/{league.MAX_MEMBERS}"
                    + (
                        f" +{league.waitlist_count(p)}"
                        if league.waitlist_count(p)
                        else ""
                    )
                ),
            )
            for p in parties
        ]
        await interaction.response.send_message(
            "**Для якого паті показати порядок запису?**",
            view=league.OneSelectView(
                league.Select(
                    self,
                    "signup_order_party",
                    options,
                    placeholder="Паті",
                )
            ),
            ephemeral=True,
        )

    league.GuildLeagueCog.begin_signup_order = begin_signup_order

    async def ping_no_response(self, interaction):
        role = interaction.guild.get_role(league.LEAGUE_ROLE_ID)
        if role is None:
            await interaction.response.send_message(
                f"Не знайшов роль <@&{league.LEAGUE_ROLE_ID}>.",
                ephemeral=True,
            )
            return

        responded = set(self.state.get("responses", {}).keys())
        for party in self.state.get("packs", []):
            for kind in ("members", "waitlist", "pending"):
                responded.update(
                    str(entry.get("user_id"))
                    for entry in party.get(kind, [])
                    if entry.get("user_id")
                )

        missing = [
            member
            for member in role.members
            if not member.bot
            and str(member.id) not in responded
        ]

        if not missing:
            await interaction.response.send_message(
                "Усі учасники з цією роллю вже відповіли.",
                ephemeral=True,
            )
            return

        mentions = " ".join(member.mention for member in missing)
        await interaction.response.send_message(
            (
                "👋 **Ще не відповіли щодо Ліги гільдій:**\n"
                f"{mentions}\n\n"
                "Оберіть роль і натисніть **Записатися**, "
                "або натисніть **Не можу**."
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )

    league.GuildLeagueCog.ping_no_response = ping_no_response

    original_pl_action = league.GuildLeagueCog.pl_action

    async def management_pl_action(self, interaction, action):
        if action not in {"slots", "signup_order", "ping_no_response"}:
            return await original_pl_action(
                self,
                interaction,
                action,
            )

        if not await self.ok_channel(interaction):
            return
        if not self.is_pl(interaction):
            await interaction.response.send_message(
                "Це меню доступне тільки PL.",
                ephemeral=True,
            )
            return

        if action == "slots":
            await self.begin_manage_slots(interaction)
            return
        if action == "signup_order":
            await self.begin_signup_order(interaction)
            return
        await self.ping_no_response(interaction)

    league.GuildLeagueCog.pl_action = management_pl_action

    async def pl_party_selected_ua(self, interaction, number, action):
        if not self.is_pl(interaction):
            await interaction.response.send_message(
                "Ти більше не PL.",
                ephemeral=True,
            )
            return

        party = league.get_party(self.state, number)
        if not party:
            await interaction.response.send_message(
                "Паті вже немає.",
                ephemeral=True,
            )
            return

        if action == "pending":
            pending = party.get("pending", [])
            if not pending:
                await interaction.response.send_message(
                    "Заявок немає.",
                    ephemeral=True,
                )
                return
            text = "\n".join(
                f"{league.role_text(x.get('role'))} <@{x['user_id']}>"
                for x in pending
            )
            await interaction.response.send_message(
                (
                    f"**Паті {number} • заявки**\n"
                    f"{league.discord_date_time(party['start_ts'])}\n\n"
                    f"{text}"
                ),
                ephemeral=True,
            )
            return

        if action in ("approve", "reject"):
            entries = party.get("pending", [])
        elif action == "remove":
            entries = (
                party.get("members", [])
                + party.get("waitlist", [])
            )
        else:
            entries = []

        if action in ("approve", "reject", "remove"):
            if not entries:
                await interaction.response.send_message(
                    "Немає кого обирати.",
                    ephemeral=True,
                )
                return

            wait_ids = {
                str(x.get("user_id"))
                for x in party.get("waitlist", [])
            }
            options = []
            for entry in entries[:25]:
                member = (
                    interaction.guild.get_member(
                        int(entry["user_id"])
                    )
                    if interaction.guild
                    else None
                )
                display_name = (
                    member.display_name
                    if member
                    else str(entry["user_id"])
                )
                suffix = (
                    " • лист очікування"
                    if str(entry["user_id"]) in wait_ids
                    else ""
                )
                options.append(
                    discord.SelectOption(
                        label=(
                            f"{display_name} • "
                            f"{league.role_text(entry.get('role'))}"
                            f"{suffix}"
                        )[:100],
                        value=str(entry["user_id"]),
                    )
                )

            prompt = {
                "approve": "**Кого прийняти?**",
                "reject": "**Чию заявку відхилити?**",
                "remove": "**Кого видалити?**",
            }[action]
            await interaction.response.send_message(
                prompt,
                view=league.OneSelectView(
                    league.Select(
                        self,
                        "member",
                        options,
                        meta={
                            "party": number,
                            "action": action,
                        },
                        placeholder="Учасник",
                    )
                ),
                ephemeral=True,
            )
            return

        if action == "reschedule":
            await interaction.response.send_message(
                (
                    f"**Паті {number}: зміна часу**\n"
                    "**1/2. Обери день:**"
                ),
                view=league.OneSelectView(
                    league.Select(
                        self,
                        "date",
                        league.date_options(),
                        meta={
                            "mode": "reschedule",
                            "party": number,
                        },
                        placeholder="Новий день",
                    )
                ),
                ephemeral=True,
            )
            return

        if action == "cancel":
            await interaction.response.send_message(
                f"Скасувати **Паті {number}**?",
                view=league.ConfirmCancelView(
                    self,
                    number,
                    interaction.user.id,
                ),
                ephemeral=True,
            )

    league.GuildLeagueCog.pl_party_selected = pl_party_selected_ua

    async def member_action_ua(
        self,
        interaction,
        number,
        action,
        user_id,
    ):
        async with self.lock:
            if not self.is_pl(interaction):
                await interaction.response.edit_message(
                    content="Ти більше не PL.",
                    view=None,
                )
                return

            party = league.get_party(self.state, number)
            if not party:
                await interaction.response.edit_message(
                    content="Паті вже немає.",
                    view=None,
                )
                return

            uid = str(user_id)
            promoted = None

            if action == "approve":
                entry = next(
                    (
                        x
                        for x in party.get("pending", [])
                        if str(x.get("user_id")) == uid
                    ),
                    None,
                )
                if not entry:
                    await interaction.response.edit_message(
                        content="Цієї заявки вже немає.",
                        view=None,
                    )
                    return

                party["pending"].remove(entry)
                if league.member_count(party) < league.MAX_MEMBERS:
                    party["members"].append(entry)
                    message = (
                        f"✅ <@{uid}> прийнято в **Паті {number}** "
                        f"({league.member_count(party)}/"
                        f"{league.MAX_MEMBERS})."
                    )
                else:
                    party["waitlist"].append(entry)
                    message = (
                        f"✅ <@{uid}> додано до **листа очікування "
                        f"Паті {number}** "
                        f"(+{league.waitlist_count(party)})."
                    )

            elif action == "reject":
                party["pending"] = [
                    x
                    for x in party.get("pending", [])
                    if str(x.get("user_id")) != uid
                ]
                message = f"❌ Заявку <@{uid}> відхилено."

            elif action == "remove":
                removed_kind, promoted = (
                    league.remove_user_from_party(
                        party,
                        uid,
                    )
                )
                if not removed_kind:
                    await interaction.response.edit_message(
                        content=(
                            "Цього користувача вже немає в паті."
                        ),
                        view=None,
                    )
                    return
                message = (
                    f"🗑️ <@{uid}> видалено з **Паті {number}**."
                )
            else:
                await interaction.response.edit_message(
                    content="Невідома дія.",
                    view=None,
                )
                return

            self.save()
            await self.refresh()
            if promoted:
                await self.send_promotion_notice(
                    party,
                    promoted,
                )

        await interaction.response.edit_message(
            content=message,
            view=None,
        )

    league.GuildLeagueCog.member_action = member_action_ua

    try:
        await cog.refresh()
    except Exception as exc:
        print(
            f"[GUILD_LEAGUE][MANAGEMENT][REFRESH] "
            f"{type(exc).__name__}: {exc}"
        )

    print(
        "[GUILD_LEAGUE] management enabled: "
        "responses, signup order, slot toggles, Ukrainian UI"
    )
