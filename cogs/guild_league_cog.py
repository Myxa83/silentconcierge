import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands


GUILD_ID = 1323454227816906802
CHANNEL_ID = 1534917454977962076
LEAGUE_ROLE_ID = 1450893024379797514

MAX_PARTIES = 3
MIN_MEMBERS = 6
MAX_MEMBERS = 10

TZ = ZoneInfo("Europe/Berlin")
COLOR = 0x3F3A78
FOOTER = "Silent Concierge by Myxa | Ліга гільдій"
DATA_FILE = Path("data/guild_league.json")

ROLES = {
    "tank": ("🛡️", "Tank"),
    "dps": ("⚔️", "DPS"),
    "shai": ("🧪", "Shai"),
}


def fresh_state() -> dict:
    return {
        "channel_id": CHANNEL_ID,
        "message_id": None,
        "pl_user_id": None,
        "packs": [],
        "roles": {},
    }


def _clean_entries(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("user_id") or "")
        if not uid or uid in seen:
            continue
        role = item.get("role")
        if role not in ROLES:
            role = None
        result.append({"user_id": uid, "role": role})
        seen.add(uid)
    return result


def load_state() -> dict:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        return fresh_state()

    try:
        state = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("root must be an object")
    except Exception as exc:
        print(f"[GUILD_LEAGUE][LOAD] {type(exc).__name__}: {exc}")
        return fresh_state()

    base = fresh_state()
    for key, value in base.items():
        state.setdefault(key, value)

    if not isinstance(state.get("packs"), list):
        state["packs"] = []
    if not isinstance(state.get("roles"), dict):
        state["roles"] = {}

    # Міграція зі старої версії, де PL зберігався в leader_id кожного паті.
    if not state.get("pl_user_id"):
        for party in state["packs"]:
            if isinstance(party, dict) and party.get("leader_id"):
                state["pl_user_id"] = str(party["leader_id"])
                break

    clean_roles = {}
    for uid, role in state.get("roles", {}).items():
        if role in ROLES:
            clean_roles[str(uid)] = role
    state["roles"] = clean_roles

    migrated = []
    for index, party in enumerate(state["packs"][:MAX_PARTIES], 1):
        if not isinstance(party, dict):
            continue

        members = _clean_entries(party.get("members"))[:MAX_MEMBERS]
        member_ids = {x["user_id"] for x in members}

        waitlist = [
            x for x in _clean_entries(party.get("waitlist"))
            if x["user_id"] not in member_ids
        ]
        occupied = member_ids | {x["user_id"] for x in waitlist}

        pending = [
            x for x in _clean_entries(party.get("pending"))
            if x["user_id"] not in occupied
        ]

        migrated.append(
            {
                "number": index,
                "start_ts": party.get("start_ts"),
                "members": members,
                "waitlist": waitlist,
                "pending": pending,
            }
        )

    state["packs"] = migrated
    return state


def save_state(state: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(DATA_FILE)


def role_text(role_key: str | None) -> str:
    role = ROLES.get(role_key or "")
    return f"{role[0]} {role[1]}" if role else "❔"


def get_party(state: dict, number: int) -> dict | None:
    return next(
        (p for p in state["packs"] if int(p["number"]) == int(number)),
        None,
    )


def find_user(
    state: dict,
    user_id: int | str,
) -> tuple[dict | None, str | None]:
    uid = str(user_id)
    for party in state["packs"]:
        for kind in ("members", "waitlist", "pending"):
            if any(
                str(x.get("user_id")) == uid
                for x in party.get(kind, [])
            ):
                return party, kind
    return None, None


def member_count(party: dict) -> int:
    return len(party.get("members", []))


def waitlist_count(party: dict) -> int:
    return len(party.get("waitlist", []))


def discord_time(ts: int) -> str:
    return f"<t:{int(ts)}:t>"


def discord_date_time(ts: int) -> str:
    return f"<t:{int(ts)}:F>"


def status_icon(party: dict) -> str:
    count = member_count(party)
    if count >= MAX_MEMBERS:
        return "✅"
    if count >= MIN_MEMBERS:
        return "🟢"
    return "🟡"


def promote_waitlist(party: dict) -> dict | None:
    if member_count(party) >= MAX_MEMBERS:
        return None
    waitlist = party.get("waitlist", [])
    if not waitlist:
        return None
    promoted = waitlist.pop(0)
    party.setdefault("members", []).append(promoted)
    return promoted


def remove_user_from_party(party: dict, user_id: int | str) -> tuple[str | None, dict | None]:
    uid = str(user_id)
    removed_kind = None

    for kind in ("members", "waitlist", "pending"):
        before = party.get(kind, [])
        after = [x for x in before if str(x.get("user_id")) != uid]
        if len(after) != len(before):
            party[kind] = after
            removed_kind = kind
            break

    promoted = promote_waitlist(party) if removed_kind == "members" else None
    return removed_kind, promoted


def date_options() -> list[discord.SelectOption]:
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    now = datetime.now(TZ)
    options = []

    for offset in range(14):
        day = (now + timedelta(days=offset)).date()
        weekend = day.weekday() >= 5
        options.append(
            discord.SelectOption(
                label=f"{days[day.weekday()]}, {day:%d.%m.%Y}",
                value=day.isoformat(),
                description=(
                    "13:00 - 01:00 CET/CEST"
                    if weekend
                    else "17:00 - 01:00 CET/CEST"
                ),
            )
        )
    return options


def time_slots(day_iso: str) -> list[tuple[str, int]]:
    day = datetime.fromisoformat(day_iso).date()
    start_hour = 13 if day.weekday() >= 5 else 17
    current = datetime(
        day.year,
        day.month,
        day.day,
        start_hour,
        0,
        tzinfo=TZ,
    )
    end = datetime(
        day.year,
        day.month,
        day.day,
        1,
        0,
        tzinfo=TZ,
    ) + timedelta(days=1)

    result = []
    while current <= end:
        suffix = " (+1 день)" if current.date() != day else ""
        result.append((f"{current:%H:%M}{suffix}", int(current.timestamp())))
        current += timedelta(minutes=20)
    return result


def header_embed(state: dict) -> discord.Embed:
    pl = state.get("pl_user_id")
    pl_text = f"<@{pl}>" if pl else "не визначений"

    embed = discord.Embed(
        title="Запис на Лігу гільдій",
        description=(
            "Обери **Tank / DPS / Shai**, потім натисни **Записатися** "
            "і вибери паті. Якщо паті 10/10, після підтвердження PL "
            "ти потрапиш у waitlist."
        ),
        color=COLOR,
    )
    embed.add_field(name="PL", value=pl_text, inline=True)
    embed.add_field(
        name="Склад",
        value=f"{MIN_MEMBERS}-{MAX_MEMBERS} гравців",
        inline=True,
    )
    embed.add_field(name="Інтервал", value="кожні 20 хв", inline=True)
    return embed


def party_field(
    party: dict | None,
    number: int,
) -> tuple[str, str]:
    if not party:
        return f"Паті {number}  Не створено", "-"

    ts = party.get("start_ts")
    members = member_count(party)
    waiting = waitlist_count(party)
    extra = f" +{waiting}" if waiting else ""

    name = (
        f"{number}  {discord_time(ts)} ({members}/{MAX_MEMBERS}{extra})"
        if ts
        else f"{number}  Час не обраний ({members}/{MAX_MEMBERS}{extra})"
    )

    lines = [
        f"{role_text(member.get('role'))} <@{member['user_id']}>"
        for member in party.get("members", [])
    ]

    waitlist = party.get("waitlist", [])
    if waitlist:
        lines.append("- waitlist -")
        lines.extend(
            f"{role_text(member.get('role'))} <@{member['user_id']}>"
            for member in waitlist
        )

    pending_count = len(party.get("pending", []))
    if pending_count:
        lines.append(f"📥 Заявки: {pending_count}")

    if not lines:
        lines.append("- порожньо -")

    if ts:
        lines.append(f"\n{status_icon(party)} {discord_date_time(ts)}")

    return name[:256], "\n".join(lines)[:1024]


def parties_embed(state: dict, bot_user) -> discord.Embed:
    embed = discord.Embed(color=COLOR)
    for number in range(1, MAX_PARTIES + 1):
        name, value = party_field(get_party(state, number), number)
        embed.add_field(name=name, value=value, inline=True)

    if bot_user:
        embed.set_footer(text=FOOTER, icon_url=bot_user.display_avatar.url)
    else:
        embed.set_footer(text=FOOTER)
    return embed


class Select(discord.ui.Select):
    def __init__(
        self,
        cog,
        kind: str,
        options: list[discord.SelectOption],
        *,
        meta: dict | None = None,
        placeholder: str = "Оберіть",
    ):
        super().__init__(
            placeholder=placeholder,
            options=options,
            min_values=1,
            max_values=1,
        )
        self.cog = cog
        self.kind = kind
        self.meta = meta or {}

    async def callback(self, interaction: discord.Interaction):
        value = self.values[0]

        if self.kind == "party_signup":
            await self.cog.signup_to(interaction, int(value))
            return

        if self.kind == "date":
            await interaction.response.edit_message(
                content="**2/2. Обери час:**",
                view=TimeView(self.cog, value, self.meta),
            )
            return

        if self.kind == "pl_party":
            await self.cog.pl_party_selected(
                interaction,
                int(value),
                self.meta["action"],
            )
            return

        if self.kind == "member":
            await self.cog.member_action(
                interaction,
                int(self.meta["party"]),
                self.meta["action"],
                str(value),
            )
            return

        if self.kind == "transfer_pl":
            await self.cog.transfer_pl(interaction, str(value))


class OneSelectView(discord.ui.View):
    def __init__(self, select: discord.ui.Select):
        super().__init__(timeout=180)
        self.add_item(select)


class TimeView(discord.ui.View):
    def __init__(self, cog, day: str, meta: dict, page: int = 0):
        super().__init__(timeout=180)
        all_slots = time_slots(day)

        select = discord.ui.Select(
            placeholder="Час CET/CEST",
            options=[
                discord.SelectOption(label=label, value=str(ts))
                for label, ts in all_slots[page * 25:(page + 1) * 25]
            ],
        )

        async def chosen(interaction: discord.Interaction):
            timestamp = int(select.values[0])
            if meta["mode"] == "create":
                await cog.create_finish(
                    interaction,
                    int(meta["party"]),
                    timestamp,
                )
            else:
                await cog.reschedule_finish(
                    interaction,
                    int(meta["party"]),
                    timestamp,
                )

        select.callback = chosen
        self.add_item(select)

        if len(all_slots) > 25:
            previous = discord.ui.Button(label="Раніше", disabled=page == 0)
            next_page = discord.ui.Button(
                label="Пізніше",
                disabled=(page + 1) * 25 >= len(all_slots),
            )

            async def go_previous(interaction: discord.Interaction):
                await interaction.response.edit_message(
                    view=TimeView(cog, day, meta, max(0, page - 1))
                )

            async def go_next(interaction: discord.Interaction):
                await interaction.response.edit_message(
                    view=TimeView(cog, day, meta, page + 1)
                )

            previous.callback = go_previous
            next_page.callback = go_next
            self.add_item(previous)
            self.add_item(next_page)


class PLMenu(discord.ui.Select):
    def __init__(self, cog):
        actions = [
            ("🔄", "Оновити повідомлення", "refresh"),
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
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await self.cog.pl_action(interaction, self.values[0])


class MainView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)

        for key, style in (
            ("tank", discord.ButtonStyle.primary),
            ("dps", discord.ButtonStyle.danger),
            ("shai", discord.ButtonStyle.success),
        ):
            button = discord.ui.Button(
                label=ROLES[key][1],
                emoji=ROLES[key][0],
                style=style,
                custom_id=f"guild_league_role_{key}",
                row=0,
            )

            async def choose_role(interaction: discord.Interaction, selected=key):
                await cog.set_role(interaction, selected)

            button.callback = choose_role
            self.add_item(button)

        signup = discord.ui.Button(
            label="Записатися",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id="guild_league_signup",
            row=1,
        )
        cant = discord.ui.Button(
            label="Не можу",
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            custom_id="guild_league_cant",
            row=1,
        )
        help_button = discord.ui.Button(
            label="Допомога",
            emoji="❔",
            style=discord.ButtonStyle.secondary,
            custom_id="guild_league_help",
            row=1,
        )

        signup.callback = cog.begin_signup
        cant.callback = cog.leave
        help_button.callback = cog.help

        self.add_item(signup)
        self.add_item(cant)
        self.add_item(help_button)
        self.add_item(PLMenu(cog))


class ConfirmCancelView(discord.ui.View):
    def __init__(self, cog, party_number: int, pl_user_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.party_number = party_number
        self.pl_user_id = pl_user_id

    @discord.ui.button(label="Так, скасувати", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if interaction.user.id != self.pl_user_id:
            await interaction.response.send_message(
                "Це не твоє підтвердження.",
                ephemeral=True,
            )
            return
        await self.cog.cancel_party(interaction, self.party_number)

    @discord.ui.button(label="Ні", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Скасування відмінено.",
            view=None,
        )


class GuildLeagueCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.state = load_state()
        self.lock = asyncio.Lock()

    async def cog_load(self):
        self.bot.add_view(MainView(self))

    def save(self):
        save_state(self.state)

    def reload_from_json(self):
        self.state = load_state()

    async def ok_channel(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id == GUILD_ID and interaction.channel_id == CHANNEL_ID:
            return True
        await interaction.response.send_message(
            f"Працює тільки в <#{CHANNEL_ID}>.",
            ephemeral=True,
        )
        return False

    def is_pl(self, interaction: discord.Interaction) -> bool:
        return str(self.state.get("pl_user_id")) == str(interaction.user.id)

    async def panel_message(self) -> discord.Message | None:
        message_id = self.state.get("message_id")
        if not message_id:
            return None
        channel = self.bot.get_channel(CHANNEL_ID) or await self.bot.fetch_channel(CHANNEL_ID)
        try:
            return await channel.fetch_message(int(message_id))
        except Exception:
            return None

    async def refresh(self):
        message = await self.panel_message()
        if not message:
            return
        await message.edit(
            content=None,
            embeds=[header_embed(self.state), parties_embed(self.state, self.bot.user)],
            view=MainView(self),
        )

    async def send_promotion_notice(self, party: dict, promoted: dict | None):
        if not promoted or not party.get("start_ts"):
            return
        channel = self.bot.get_channel(CHANNEL_ID) or await self.bot.fetch_channel(CHANNEL_ID)
        await channel.send(
            (
                f"<@{promoted['user_id']}> місце звільнилося в **Паті {party['number']}**. "
                f"Тебе автоматично перенесено з waitlist у склад.\n"
                f"🕒 {discord_date_time(party['start_ts'])}"
            ),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    async def set_role(self, interaction: discord.Interaction, role_key: str):
        if not await self.ok_channel(interaction):
            return

        uid = str(interaction.user.id)
        self.state["roles"][uid] = role_key
        party, kind = find_user(self.state, uid)
        if party and kind:
            for entry in party.get(kind, []):
                if str(entry.get("user_id")) == uid:
                    entry["role"] = role_key
                    break

        self.save()
        await self.refresh()
        await interaction.response.send_message(
            f"Обрано **{role_text(role_key)}**.",
            ephemeral=True,
        )

    async def begin_signup(self, interaction: discord.Interaction):
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

        current_party, _ = find_user(self.state, uid)
        available = [p for p in self.state["packs"] if p.get("start_ts")]
        if not available:
            await interaction.response.send_message(
                "Зараз немає створеного паті з обраним часом.",
                ephemeral=True,
            )
            return

        lines = []
        options = []
        for party in available:
            number = party["number"]
            count = member_count(party)
            waiting = waitlist_count(party)
            marker = " • зараз тут" if current_party is party else ""
            full = count >= MAX_MEMBERS
            extra = f" +{waiting}" if waiting else ""
            lines.append(
                f"**{number}.** {discord_date_time(party['start_ts'])} "
                f"• {count}/{MAX_MEMBERS}{extra}{marker}"
            )
            options.append(
                discord.SelectOption(
                    label=f"Паті {number} • {count}/{MAX_MEMBERS}{extra}",
                    value=str(number),
                    description=(
                        "Повне - після схвалення в waitlist"
                        if full
                        else "Обрати це паті"
                    ),
                )
            )

        await interaction.response.send_message(
            "\n".join(lines) + "\n\n**Обери паті:**",
            view=OneSelectView(
                Select(
                    self,
                    "party_signup",
                    options,
                    placeholder="Паті",
                )
            ),
            ephemeral=True,
        )

    async def signup_to(self, interaction: discord.Interaction, number: int):
        async with self.lock:
            party = get_party(self.state, number)
            uid = str(interaction.user.id)
            role_key = self.state["roles"].get(uid)

            if not party or not party.get("start_ts"):
                await interaction.response.edit_message(
                    content="Це паті вже недоступне.",
                    view=None,
                )
                return
            if not role_key:
                await interaction.response.edit_message(
                    content="Спочатку обери роль.",
                    view=None,
                )
                return

            current_party, current_kind = find_user(self.state, uid)
            if current_party is party:
                status = {
                    "members": "у складі",
                    "waitlist": "у waitlist",
                    "pending": "подав заявку",
                }.get(current_kind, "записаний")
                await interaction.response.edit_message(
                    content=(
                        f"Ти вже {status} **Паті {number}**.\n"
                        f"🕒 {discord_date_time(party['start_ts'])}"
                    ),
                    view=None,
                )
                return

            promoted = None
            if current_party:
                _removed, promoted = remove_user_from_party(current_party, uid)

            party["pending"] = [
                x for x in party.get("pending", [])
                if str(x.get("user_id")) != uid
            ]
            party["pending"].append({"user_id": uid, "role": role_key})

            self.save()
            await self.refresh()
            if promoted:
                await self.send_promotion_notice(current_party, promoted)

            channel = self.bot.get_channel(CHANNEL_ID) or await self.bot.fetch_channel(CHANNEL_ID)
            pl = self.state.get("pl_user_id")
            if pl:
                await channel.send(
                    (
                        f"<@{pl}> нова заявка в **Паті {number}**\n"
                        f"{role_text(role_key)} <@{uid}> • "
                        f"{discord_date_time(party['start_ts'])}"
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
                f"🕒 {discord_date_time(party['start_ts'])}\n"
                f"Роль: **{role_text(role_key)}**"
            ),
            view=None,
        )

    async def leave(self, interaction: discord.Interaction):
        if not await self.ok_channel(interaction):
            return

        party, kind = find_user(self.state, interaction.user.id)
        if not party:
            await interaction.response.send_message(
                "Ти не записаний у жодне паті.",
                ephemeral=True,
            )
            return

        uid = str(interaction.user.id)
        number = party["number"]
        removed_kind, promoted = remove_user_from_party(party, uid)
        self.save()
        await self.refresh()
        if promoted:
            await self.send_promotion_notice(party, promoted)

        text = f"Твій запис у **Паті {number}** скасовано."
        if removed_kind == "waitlist":
            text = f"Тебе прибрано з waitlist **Паті {number}**."
        await interaction.response.send_message(text, ephemeral=True)

    async def help(self, interaction: discord.Interaction):
        if not await self.ok_channel(interaction):
            return
        await interaction.response.send_message(
            (
                "**Як записатися:**\n"
                "1. Обери **Tank**, **DPS** або **Shai**.\n"
                "2. Натисни **Записатися**.\n"
                "3. Обери паті з потрібним часом.\n\n"
                "PL підтверджує заявку. Якщо склад уже 10/10, підтверджена "
                "заявка переходить у **waitlist**. Коли місце звільняється, "
                "перший у waitlist автоматично переходить у склад.\n\n"
                "**Не можу** скасовує заявку, участь або waitlist.\n"
                "Час Discord автоматично показується у твоєму часовому поясі."
            ),
            ephemeral=True,
        )

    async def pl_action(self, interaction: discord.Interaction, action: str):
        if not await self.ok_channel(interaction):
            return
        if not self.is_pl(interaction):
            await interaction.response.send_message(
                "Це меню доступне тільки PL.",
                ephemeral=True,
            )
            return

        if action == "refresh":
            await self.refresh()
            await interaction.response.send_message("Панель оновлена.", ephemeral=True)
            return
        if action == "create":
            await self.begin_create(interaction)
            return
        if action == "transfer":
            await self.begin_transfer_pl(interaction)
            return

        candidates = []
        for party in self.state["packs"]:
            if action in ("approve", "reject", "pending") and party.get("pending"):
                candidates.append(party)
            elif action == "remove" and (party.get("members") or party.get("waitlist")):
                candidates.append(party)
            elif action in ("reschedule", "cancel"):
                candidates.append(party)

        if not candidates:
            text = (
                "Заявок немає."
                if action in ("approve", "reject", "pending")
                else "Немає доступної дії."
            )
            await interaction.response.send_message(text, ephemeral=True)
            return

        if len(candidates) == 1:
            await self.pl_party_selected(interaction, candidates[0]["number"], action)
            return

        options = []
        for party in candidates:
            waiting = waitlist_count(party)
            extra = f" +{waiting}" if waiting else ""
            options.append(
                discord.SelectOption(
                    label=f"Паті {party['number']}",
                    value=str(party["number"]),
                    description=(
                        f"{discord_time(party['start_ts'])} • "
                        f"{member_count(party)}/{MAX_MEMBERS}{extra}"
                        if party.get("start_ts")
                        else f"{member_count(party)}/{MAX_MEMBERS}{extra}"
                    ),
                )
            )

        await interaction.response.send_message(
            "**Обери паті:**",
            view=OneSelectView(
                Select(
                    self,
                    "pl_party",
                    options,
                    meta={"action": action},
                    placeholder="Паті",
                )
            ),
            ephemeral=True,
        )

    async def pl_party_selected(
        self,
        interaction: discord.Interaction,
        number: int,
        action: str,
    ):
        if not self.is_pl(interaction):
            await interaction.response.send_message("Ти більше не PL.", ephemeral=True)
            return

        party = get_party(self.state, number)
        if not party:
            await interaction.response.send_message("Паті вже немає.", ephemeral=True)
            return

        if action == "pending":
            pending = party.get("pending", [])
            if not pending:
                await interaction.response.send_message("Заявок немає.", ephemeral=True)
                return
            text = "\n".join(
                f"{role_text(x.get('role'))} <@{x['user_id']}>"
                for x in pending
            )
            await interaction.response.send_message(
                (
                    f"**Паті {number} - заявки**\n"
                    f"{discord_date_time(party['start_ts'])}\n\n{text}"
                ),
                ephemeral=True,
            )
            return

        if action in ("approve", "reject"):
            entries = party.get("pending", [])
        elif action == "remove":
            entries = party.get("members", []) + party.get("waitlist", [])
        else:
            entries = []

        if action in ("approve", "reject", "remove"):
            if not entries:
                await interaction.response.send_message("Немає кого обирати.", ephemeral=True)
                return

            options = []
            wait_ids = {str(x.get("user_id")) for x in party.get("waitlist", [])}
            for entry in entries[:25]:
                member = (
                    interaction.guild.get_member(int(entry["user_id"]))
                    if interaction.guild
                    else None
                )
                display_name = member.display_name if member else str(entry["user_id"])
                suffix = " • waitlist" if str(entry["user_id"]) in wait_ids else ""
                options.append(
                    discord.SelectOption(
                        label=(
                            f"{display_name} • {role_text(entry.get('role'))}{suffix}"
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
                view=OneSelectView(
                    Select(
                        self,
                        "member",
                        options,
                        meta={"party": number, "action": action},
                        placeholder="Учасник",
                    )
                ),
                ephemeral=True,
            )
            return

        if action == "reschedule":
            await interaction.response.send_message(
                f"**Паті {number}: зміна часу**\n**1/2. Обери день:**",
                view=OneSelectView(
                    Select(
                        self,
                        "date",
                        date_options(),
                        meta={"mode": "reschedule", "party": number},
                        placeholder="Новий день",
                    )
                ),
                ephemeral=True,
            )
            return

        if action == "cancel":
            await interaction.response.send_message(
                f"Скасувати **Паті {number}**?",
                view=ConfirmCancelView(self, number, interaction.user.id),
                ephemeral=True,
            )

    async def member_action(
        self,
        interaction: discord.Interaction,
        number: int,
        action: str,
        user_id: str,
    ):
        async with self.lock:
            if not self.is_pl(interaction):
                await interaction.response.edit_message(
                    content="Ти більше не PL.",
                    view=None,
                )
                return

            party = get_party(self.state, number)
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
                        x for x in party.get("pending", [])
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
                if member_count(party) < MAX_MEMBERS:
                    party["members"].append(entry)
                    message = (
                        f"✅ <@{uid}> прийнято в **Паті {number}** "
                        f"({member_count(party)}/{MAX_MEMBERS})."
                    )
                else:
                    party["waitlist"].append(entry)
                    message = (
                        f"✅ <@{uid}> підтверджено в **waitlist Паті {number}** "
                        f"(+{waitlist_count(party)})."
                    )

            elif action == "reject":
                party["pending"] = [
                    x for x in party.get("pending", [])
                    if str(x.get("user_id")) != uid
                ]
                message = f"❌ Заявку <@{uid}> відхилено."

            elif action == "remove":
                removed_kind, promoted = remove_user_from_party(party, uid)
                if not removed_kind:
                    await interaction.response.edit_message(
                        content="Цього користувача вже немає в паті.",
                        view=None,
                    )
                    return
                message = f"🗑️ <@{uid}> видалено з **Паті {number}**."
            else:
                await interaction.response.edit_message(
                    content="Невідома дія.",
                    view=None,
                )
                return

            self.save()
            await self.refresh()
            if promoted:
                await self.send_promotion_notice(party, promoted)

        await interaction.response.edit_message(content=message, view=None)

    async def begin_create(self, interaction: discord.Interaction):
        if not self.is_pl(interaction):
            await interaction.response.send_message(
                "Тільки PL може створювати паті.",
                ephemeral=True,
            )
            return

        # Якщо створення випадково перервали, продовжуємо незавершене паті,
        # а не створюємо новий порожній запис.
        unfinished = next(
            (p for p in self.state["packs"] if not p.get("start_ts")),
            None,
        )
        if unfinished:
            number = unfinished["number"]
        else:
            if len(self.state["packs"]) >= MAX_PARTIES:
                await interaction.response.send_message(
                    "Уже створені всі 3 паті.",
                    ephemeral=True,
                )
                return
            number = len(self.state["packs"]) + 1
            self.state["packs"].append(
                {
                    "number": number,
                    "start_ts": None,
                    "members": [],
                    "waitlist": [],
                    "pending": [],
                }
            )
            self.save()
            await self.refresh()

        await interaction.response.send_message(
            f"**Паті {number}**\n**1/2. Обери день:**",
            view=OneSelectView(
                Select(
                    self,
                    "date",
                    date_options(),
                    meta={"mode": "create", "party": number},
                    placeholder="День",
                )
            ),
            ephemeral=True,
        )

    async def create_finish(
        self,
        interaction: discord.Interaction,
        number: int,
        timestamp: int,
    ):
        if not self.is_pl(interaction):
            await interaction.response.edit_message(
                content="Ти більше не PL.",
                view=None,
            )
            return

        party = get_party(self.state, number)
        if not party:
            await interaction.response.edit_message(
                content="Паті вже немає.",
                view=None,
            )
            return

        party["start_ts"] = timestamp
        self.save()
        await self.refresh()

        channel = self.bot.get_channel(CHANNEL_ID) or await self.bot.fetch_channel(CHANNEL_ID)
        await channel.send(
            (
                f"<@&{LEAGUE_ROLE_ID}> створено **Паті {number}**\n"
                f"🕒 {discord_date_time(timestamp)}\n"
                "Для участі обери роль і натисни **Записатися**."
            ),
            allowed_mentions=discord.AllowedMentions(
                roles=True,
                users=False,
                everyone=False,
            ),
        )
        await interaction.response.edit_message(
            content=(
                f"✅ **Паті {number} створено.**\n"
                f"🕒 {discord_date_time(timestamp)}"
            ),
            view=None,
        )

    async def reschedule_finish(
        self,
        interaction: discord.Interaction,
        number: int,
        timestamp: int,
    ):
        if not self.is_pl(interaction):
            await interaction.response.edit_message(
                content="Ти більше не PL.",
                view=None,
            )
            return

        party = get_party(self.state, number)
        if not party:
            await interaction.response.edit_message(
                content="Паті вже немає.",
                view=None,
            )
            return

        party["start_ts"] = timestamp
        self.save()
        await self.refresh()
        await interaction.response.edit_message(
            content=(
                f"✅ Час **Паті {number}** змінено.\n"
                f"🕒 {discord_date_time(timestamp)}"
            ),
            view=None,
        )

    async def cancel_party(self, interaction: discord.Interaction, number: int):
        if not self.is_pl(interaction):
            await interaction.response.edit_message(
                content="Ти більше не PL.",
                view=None,
            )
            return

        self.state["packs"] = [
            p for p in self.state["packs"]
            if int(p["number"]) != int(number)
        ]
        for index, party in enumerate(self.state["packs"], 1):
            party["number"] = index

        self.save()
        await self.refresh()
        await interaction.response.edit_message(
            content=f"Паті {number} скасовано.",
            view=None,
        )

    async def begin_transfer_pl(self, interaction: discord.Interaction):
        users = {}
        for party in self.state["packs"]:
            for kind in ("members", "waitlist", "pending"):
                for entry in party.get(kind, []):
                    uid = str(entry.get("user_id"))
                    if uid and uid != str(interaction.user.id):
                        users[uid] = entry

        if not users:
            await interaction.response.send_message(
                "Немає учасників, кому можна передати PL.",
                ephemeral=True,
            )
            return

        options = []
        for uid in list(users.keys())[:25]:
            member = interaction.guild.get_member(int(uid)) if interaction.guild else None
            options.append(
                discord.SelectOption(
                    label=(member.display_name if member else uid)[:100],
                    value=uid,
                )
            )

        await interaction.response.send_message(
            "**Кому передати PL?**",
            view=OneSelectView(
                Select(
                    self,
                    "transfer_pl",
                    options,
                    placeholder="Новий PL",
                )
            ),
            ephemeral=True,
        )

    async def transfer_pl(
        self,
        interaction: discord.Interaction,
        new_pl_user_id: str,
    ):
        if not self.is_pl(interaction):
            await interaction.response.edit_message(
                content="Ти більше не PL.",
                view=None,
            )
            return

        self.state["pl_user_id"] = str(new_pl_user_id)
        self.save()
        await self.refresh()
        await interaction.response.edit_message(
            content=f"👑 PL передано <@{new_pl_user_id}>.",
            view=None,
        )

    @app_commands.command(
        name="guild_league_panel",
        description="Створити або відновити панель Ліги гільдій",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def panel(self, interaction: discord.Interaction):
        is_admin = interaction.user.guild_permissions.administrator
        has_league_role = (
            isinstance(interaction.user, discord.Member)
            and any(role.id == LEAGUE_ROLE_ID for role in interaction.user.roles)
        )

        if not (is_admin or has_league_role):
            await interaction.response.send_message(
                f"Команда доступна учасникам <@&{LEAGUE_ROLE_ID}>.",
                ephemeral=True,
            )
            return
        if interaction.channel_id != CHANNEL_ID:
            await interaction.response.send_message(
                f"Запусти команду в <#{CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        # Перед побудовою панелі перечитуємо JSON. Усі ролі, записи,
        # заявки та waitlist підтягуються назад після повторного створення
        # повідомлення або рестарту когу.
        self.reload_from_json()

        if not self.state.get("pl_user_id"):
            self.state["pl_user_id"] = str(interaction.user.id)
            self.save()

        embeds = [header_embed(self.state), parties_embed(self.state, self.bot.user)]
        existing = await self.panel_message()

        if existing:
            await existing.edit(
                content=None,
                embeds=embeds,
                view=MainView(self),
            )
            await interaction.response.send_message(
                f"Панель оновлена з JSON: {existing.jump_url}",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embeds=embeds,
            view=MainView(self),
        )
        message = await interaction.original_response()
        self.state["message_id"] = message.id
        self.save()


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildLeagueCog(bot))
