# -*- coding: utf-8 -*-
from __future__ import annotations

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

MAX_PACKS = 3
MIN_MEMBERS = 8
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
        "packs": [],
        "roles": {},
    }


def role_text(key: str | None) -> str:
    value = ROLES.get(key or "")
    return f"{value[0]} {value[1]}" if value else "❔ роль не обрана"


def load_json_state() -> dict:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        return fresh_state()

    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("root is not an object")
    except Exception as exc:
        print(f"[GUILD_LEAGUE][JSON][LOAD ERROR] {type(exc).__name__}: {exc}")
        return fresh_state()

    base = fresh_state()
    for key, value in base.items():
        data.setdefault(key, value)

    if not isinstance(data.get("packs"), list):
        data["packs"] = []
    if not isinstance(data.get("roles"), dict):
        data["roles"] = {}

    for p in data["packs"]:
        p.setdefault("members", [])
        p.setdefault("pending", [])
        p.setdefault("leader_role", None)
        p.setdefault("start_ts", None)

    return data


def save_json_state(state: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(DATA_FILE)


def get_pack(state: dict, number: int) -> dict | None:
    return next(
        (p for p in state["packs"] if int(p["number"]) == int(number)),
        None,
    )


def user_pack(
    state: dict,
    user_id: int | str,
) -> tuple[dict | None, str | None]:
    uid = str(user_id)
    for p in state["packs"]:
        if str(p.get("leader_id")) == uid:
            return p, "leader"
        if any(str(x.get("user_id")) == uid for x in p.get("members", [])):
            return p, "member"
        if any(str(x.get("user_id")) == uid for x in p.get("pending", [])):
            return p, "pending"
    return None, None


def confirmed_count(p: dict) -> int:
    return 1 + len(p.get("members", []))


def pack_status(p: dict) -> str:
    if not p.get("start_ts"):
        return "🟣 Налаштування"
    total = confirmed_count(p)
    if total >= MAX_MEMBERS:
        return "🟢 Повна"
    if total >= MIN_MEMBERS:
        return "🟢 Готова"
    return "🟡 Формується"


def date_options() -> list[discord.SelectOption]:
    day_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
    now = datetime.now(TZ)
    result = []

    for offset in range(14):
        day = (now + timedelta(days=offset)).date()
        result.append(
            discord.SelectOption(
                label=f"{day_names[day.weekday()]}, {day:%d.%m.%Y}",
                value=day.isoformat(),
                description=(
                    "слоти з 13:00 до 01:00"
                    if day.weekday() >= 5
                    else "слоти з 17:00 до 01:00"
                ),
            )
        )
    return result


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
        result.append(
            (
                f"{current:%H:%M}{suffix}",
                int(current.timestamp()),
            )
        )
        current += timedelta(minutes=20)

    return result


def pack_embed(
    number: int,
    p: dict | None,
    bot_user,
) -> discord.Embed:
    if p is None:
        embed = discord.Embed(
            title=f"Пачка {number}",
            description="*Ще не створена.*\nНатисніть **Створити пачку**.",
            color=COLOR,
        )
        embed.add_field(
            name="Учасники",
            value="0/10",
            inline=True,
        )
        embed.add_field(
            name="PL",
            value="-",
            inline=True,
        )
        embed.set_footer(
            text=FOOTER,
            icon_url=bot_user.display_avatar.url if bot_user else None,
        )
        return embed

    leader_id = str(p["leader_id"])
    leader_role = p.get("leader_role")
    start_ts = p.get("start_ts")

    if start_ts:
        local = datetime.fromtimestamp(
            int(start_ts),
            TZ,
        )
        description = (
            f"**День і час:** <t:{int(start_ts)}:F>\n"
            f"**Час Ліги:** {local:%H:%M} {local.tzname()}\n"
            f"**PL:** <@{leader_id}> | {role_text(leader_role)}"
        )
    else:
        description = (
            f"**PL:** <@{leader_id}> | {role_text(leader_role)}\n"
            "**День і час:** ще не обрані\n"
            "PL має обрати роль і натиснути **Створити пачку**."
        )

    embed = discord.Embed(
        title=f"Пачка {number} | {pack_status(p)}",
        description=description,
        color=COLOR,
    )

    lines = [
        f"`01.` 👑 {role_text(leader_role)} <@{leader_id}>"
    ]
    lines.extend(
        f"`{index:02}.` {role_text(entry.get('role'))} <@{entry['user_id']}>"
        for index, entry in enumerate(p.get("members", []), 2)
    )

    embed.add_field(
        name=f"Учасники ({confirmed_count(p)}/10)",
        value="\n".join(lines),
        inline=False,
    )

    pending = p.get("pending", [])
    if pending:
        pending_text = "\n".join(
            f"⏳ {role_text(entry.get('role'))} <@{entry['user_id']}>"
            for entry in pending
        )
        pending_text += (
            "\n\n**PL:** відкрий `Керування PL` → "
            "`Підтвердити заявку`."
        )
    else:
        pending_text = "Немає"

    embed.add_field(
        name=f"Заявки PL ({len(pending)})",
        value=pending_text[:1024],
        inline=False,
    )

    embed.set_footer(
        text=FOOTER,
        icon_url=bot_user.display_avatar.url if bot_user else None,
    )
    return embed


class SimpleSelect(discord.ui.Select):
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

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        value = self.values[0]

        if self.kind == "pack":
            await self.cog.signup_to(
                interaction,
                int(value),
                self.meta["move"],
            )
            return

        if self.kind == "date":
            await interaction.response.edit_message(
                content="Оберіть час:",
                view=TimeView(
                    self.cog,
                    value,
                    self.meta,
                ),
            )
            return

        if self.kind == "member":
            await self.cog.member_action(
                interaction,
                self.meta["pack"],
                self.meta["action"],
                int(value),
            )


class OneSelectView(discord.ui.View):
    def __init__(self, select: discord.ui.Select):
        super().__init__(timeout=180)
        self.add_item(select)


class TimeView(discord.ui.View):
    def __init__(
        self,
        cog,
        day: str,
        meta: dict,
        page: int = 0,
    ):
        super().__init__(timeout=180)
        slots = time_slots(day)

        options = [
            discord.SelectOption(
                label=label,
                value=str(timestamp),
            )
            for label, timestamp
            in slots[page * 25 : (page + 1) * 25]
        ]

        select = discord.ui.Select(
            placeholder="Оберіть час",
            options=options,
        )

        async def chosen(
            interaction: discord.Interaction,
        ):
            timestamp = int(select.values[0])
            if meta["mode"] == "create":
                await cog.create_finish(
                    interaction,
                    timestamp,
                )
            else:
                await cog.reschedule_finish(
                    interaction,
                    meta["pack"],
                    timestamp,
                )

        select.callback = chosen
        self.add_item(select)

        if len(slots) > 25:
            previous = discord.ui.Button(
                label="Раніше",
                disabled=page == 0,
            )
            next_page = discord.ui.Button(
                label="Пізніше",
                disabled=(page + 1) * 25 >= len(slots),
            )

            async def go_previous(
                interaction: discord.Interaction,
            ):
                await interaction.response.edit_message(
                    view=TimeView(
                        cog,
                        day,
                        meta,
                        max(0, page - 1),
                    )
                )

            async def go_next(
                interaction: discord.Interaction,
            ):
                await interaction.response.edit_message(
                    view=TimeView(
                        cog,
                        day,
                        meta,
                        page + 1,
                    )
                )

            previous.callback = go_previous
            next_page.callback = go_next
            self.add_item(previous)
            self.add_item(next_page)


class PLSelect(discord.ui.Select):
    def __init__(self, cog):
        actions = [
            ("✅", "Підтвердити заявку", "approve"),
            ("❌", "Відхилити заявку", "reject"),
            ("📋", "Переглянути заявки", "pending"),
            ("🗑️", "Видалити учасника", "remove"),
            ("📅", "Змінити день / час", "reschedule"),
            ("👑", "Передати PL", "leader"),
            ("🔄", "Оновити повідомлення", "refresh"),
            ("⛔", "Скасувати пачку", "cancel"),
        ]
        super().__init__(
            placeholder="Керування PL",
            custom_id="league_pl",
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
        self.cog = cog

    async def callback(
        self,
        interaction: discord.Interaction,
    ):
        await self.cog.pl_action(
            interaction,
            self.values[0],
        )


class MainView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)

        role_buttons = (
            ("tank", discord.ButtonStyle.primary),
            ("dps", discord.ButtonStyle.danger),
            ("shai", discord.ButtonStyle.success),
        )

        for key, style in role_buttons:
            button = discord.ui.Button(
                label=ROLES[key][1],
                emoji=ROLES[key][0],
                style=style,
                custom_id=f"league_role_{key}",
                row=0,
            )

            async def choose_role(
                interaction: discord.Interaction,
                selected=key,
            ):
                await cog.set_role(
                    interaction,
                    selected,
                )

            button.callback = choose_role
            self.add_item(button)

        actions = [
            (
                "Записатися",
                "✅",
                discord.ButtonStyle.success,
                "league_signup",
                lambda interaction: cog.begin_signup(
                    interaction,
                    False,
                ),
            ),
            (
                "Перейти",
                "🔁",
                discord.ButtonStyle.primary,
                "league_move",
                lambda interaction: cog.begin_signup(
                    interaction,
                    True,
                ),
            ),
            (
                "Відписатися",
                "✖️",
                discord.ButtonStyle.danger,
                "league_leave",
                cog.leave,
            ),
            (
                "Створити пачку",
                "➕",
                discord.ButtonStyle.secondary,
                "league_create",
                cog.begin_create,
            ),
        ]

        for (
            label,
            emoji,
            style,
            custom_id,
            callback,
        ) in actions:
            button = discord.ui.Button(
                label=label,
                emoji=emoji,
                style=style,
                custom_id=custom_id,
                row=(
                    1
                    if custom_id != "league_create"
                    else 2
                ),
            )
            button.callback = callback
            self.add_item(button)

        self.add_item(PLSelect(cog))


class CancelView(discord.ui.View):
    def __init__(
        self,
        cog,
        number: int,
        user_id: int,
    ):
        super().__init__(timeout=60)
        self.cog = cog
        self.number = number
        self.user_id = user_id

    @discord.ui.button(
        label="Так, скасувати",
        style=discord.ButtonStyle.danger,
    )
    async def yes(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Не ваше підтвердження.",
                ephemeral=True,
            )
            return

        await self.cog.cancel(
            interaction,
            self.number,
        )

    @discord.ui.button(
        label="Ні",
        style=discord.ButtonStyle.secondary,
    )
    async def no(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        await interaction.response.edit_message(
            content="Скасування відмінено.",
            view=None,
        )


class GuildLeagueCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
    ):
        self.bot = bot
        self.state = load_json_state()
        self.lock = asyncio.Lock()

    async def cog_load(self):
        self.bot.add_view(
            MainView(self)
        )

    def save(self):
        save_json_state(
            self.state
        )

    async def ok_channel(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if (
            interaction.guild_id == GUILD_ID
            and interaction.channel_id == CHANNEL_ID
        ):
            return True

        await interaction.response.send_message(
            f"Працює тільки в <#{CHANNEL_ID}>.",
            ephemeral=True,
        )
        return False

    async def fetch_panel_message(
        self,
    ) -> discord.Message | None:
        message_id = self.state.get("message_id")
        if not message_id:
            return None

        channel = (
            self.bot.get_channel(CHANNEL_ID)
            or await self.bot.fetch_channel(CHANNEL_ID)
        )

        try:
            return await channel.fetch_message(
                int(message_id)
            )
        except Exception:
            return None

    async def refresh(self):
        message = await self.fetch_panel_message()
        if message is None:
            return

        await message.edit(
            embeds=[
                pack_embed(
                    number,
                    get_pack(
                        self.state,
                        number,
                    ),
                    self.bot.user,
                )
                for number
                in range(
                    1,
                    MAX_PACKS + 1,
                )
            ],
            view=MainView(self),
        )

    async def set_role(
        self,
        interaction: discord.Interaction,
        key: str,
    ):
        if not await self.ok_channel(
            interaction
        ):
            return

        uid = str(
            interaction.user.id
        )
        self.state["roles"][uid] = key

        p, membership = user_pack(
            self.state,
            uid,
        )

        if p:
            if membership == "leader":
                p["leader_role"] = key
            else:
                for entry in (
                    p.get("members", [])
                    + p.get("pending", [])
                ):
                    if (
                        str(entry["user_id"])
                        == uid
                    ):
                        entry["role"] = key

        self.save()
        await self.refresh()

        await interaction.response.send_message(
            f"Обрано **{role_text(key)}**.",
            ephemeral=True,
        )

    async def begin_signup(
        self,
        interaction: discord.Interaction,
        move: bool,
    ):
        if not await self.ok_channel(
            interaction
        ):
            return

        uid = str(
            interaction.user.id
        )
        selected_role = (
            self.state["roles"].get(uid)
        )
        current, current_status = (
            user_pack(
                self.state,
                uid,
            )
        )

        if not selected_role:
            await interaction.response.send_message(
                "Спочатку оберіть Tank, DPS або Shai.",
                ephemeral=True,
            )
            return

        if move and not current:
            await interaction.response.send_message(
                "Ви ще ніде не записані.",
                ephemeral=True,
            )
            return

        if (
            move
            and current_status == "leader"
        ):
            await interaction.response.send_message(
                "PL спочатку має передати PL або скасувати пачку.",
                ephemeral=True,
            )
            return

        if not move and current:
            await interaction.response.send_message(
                (
                    f"Ви вже в Пачці {current['number']}. "
                    "Використайте Перейти."
                ),
                ephemeral=True,
            )
            return

        available = [
            p
            for p in self.state["packs"]
            if p.get("start_ts")
            and confirmed_count(p) < MAX_MEMBERS
            and (
                current is None
                or p["number"]
                != current["number"]
            )
        ]

        if not available:
            await interaction.response.send_message(
                "Немає доступної створеної пачки.",
                ephemeral=True,
            )
            return

        options = [
            discord.SelectOption(
                label=(
                    f"Пачка {p['number']} | "
                    f"{confirmed_count(p)}/10"
                ),
                value=str(
                    p["number"]
                ),
            )
            for p in available
        ]

        await interaction.response.send_message(
            (
                "Оберіть пачку. "
                "Після цього заявка з'явиться у PL."
            ),
            view=OneSelectView(
                SimpleSelect(
                    self,
                    "pack",
                    options,
                    meta={
                        "move": move,
                    },
                )
            ),
            ephemeral=True,
        )

    async def signup_to(
        self,
        interaction: discord.Interaction,
        number: int,
        move: bool,
    ):
        async with self.lock:
            p = get_pack(
                self.state,
                number,
            )
            uid = str(
                interaction.user.id
            )
            selected_role = (
                self.state["roles"].get(uid)
            )
            current, current_status = (
                user_pack(
                    self.state,
                    uid,
                )
            )

            if (
                not p
                or not p.get("start_ts")
                or confirmed_count(p)
                >= MAX_MEMBERS
            ):
                await interaction.response.edit_message(
                    content="Пачка недоступна.",
                    view=None,
                )
                return

            if current_status == "leader":
                await interaction.response.edit_message(
                    content="PL не може перейти напряму.",
                    view=None,
                )
                return

            if current:
                current["members"] = [
                    x
                    for x in current.get(
                        "members",
                        [],
                    )
                    if str(x["user_id"])
                    != uid
                ]
                current["pending"] = [
                    x
                    for x in current.get(
                        "pending",
                        [],
                    )
                    if str(x["user_id"])
                    != uid
                ]

            p["pending"] = [
                x
                for x in p.get(
                    "pending",
                    [],
                )
                if str(x["user_id"])
                != uid
            ]
            p["pending"].append(
                {
                    "user_id": uid,
                    "role": selected_role,
                }
            )

            self.save()
            await self.refresh()

            channel = (
                self.bot.get_channel(
                    CHANNEL_ID
                )
                or await self.bot.fetch_channel(
                    CHANNEL_ID
                )
            )
            await channel.send(
                (
                    f"<@{p['leader_id']}> нова заявка "
                    f"до **Пачки {number}** від "
                    f"<@{uid}> як **{role_text(selected_role)}**.\n"
                    "Відкрий **Керування PL** → "
                    "**Підтвердити заявку**."
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )

        await interaction.response.edit_message(
            content=(
                f"Заявку до **Пачки {number}** "
                f"збережено. PL: <@{p['leader_id']}>."
            ),
            view=None,
        )

    async def leave(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.ok_channel(
            interaction
        ):
            return

        p, membership = user_pack(
            self.state,
            interaction.user.id,
        )

        if not p:
            await interaction.response.send_message(
                "Ви ніде не записані.",
                ephemeral=True,
            )
            return

        if membership == "leader":
            await interaction.response.send_message(
                (
                    "PL має передати PL "
                    "або скасувати пачку."
                ),
                ephemeral=True,
            )
            return

        uid = str(
            interaction.user.id
        )
        p["members"] = [
            x
            for x in p.get("members", [])
            if str(x["user_id"]) != uid
        ]
        p["pending"] = [
            x
            for x in p.get("pending", [])
            if str(x["user_id"]) != uid
        ]

        self.save()
        await self.refresh()

        await interaction.response.send_message(
            (
                f"Ви відписалися "
                f"від Пачки {p['number']}."
            ),
            ephemeral=True,
        )

    async def begin_create(
        self,
        interaction: discord.Interaction,
    ):
        if not await self.ok_channel(
            interaction
        ):
            return

        uid = str(
            interaction.user.id
        )
        selected_role = (
            self.state["roles"].get(uid)
        )
        current, current_status = (
            user_pack(
                self.state,
                uid,
            )
        )

        if not selected_role:
            await interaction.response.send_message(
                (
                    "Спочатку оберіть Tank, DPS або Shai. "
                    "PL входить у 10 людей."
                ),
                ephemeral=True,
            )
            return

        if (
            current
            and current_status == "leader"
            and not current.get("start_ts")
        ):
            select = SimpleSelect(
                self,
                "date",
                date_options(),
                meta={
                    "mode": "create",
                    "pack": current["number"],
                },
                placeholder="Оберіть день",
            )
            await interaction.response.send_message(
                (
                    f"Налаштування **Пачки {current['number']}**. "
                    "Оберіть день:"
                ),
                view=OneSelectView(
                    select
                ),
                ephemeral=True,
            )
            return

        if current:
            await interaction.response.send_message(
                (
                    "Щоб стати PL нової пачки, "
                    "спочатку вийдіть з поточної."
                ),
                ephemeral=True,
            )
            return

        if len(self.state["packs"]) >= MAX_PACKS:
            await interaction.response.send_message(
                "Уже створено всі 3 пачки.",
                ephemeral=True,
            )
            return

        number = len(
            self.state["packs"]
        ) + 1

        self.state["packs"].append(
            {
                "number": number,
                "leader_id": uid,
                "leader_role": selected_role,
                "start_ts": None,
                "members": [],
                "pending": [],
            }
        )
        self.save()
        await self.refresh()

        select = SimpleSelect(
            self,
            "date",
            date_options(),
            meta={
                "mode": "create",
                "pack": number,
            },
            placeholder="Оберіть день",
        )
        await interaction.response.send_message(
            (
                f"Ви стали PL **Пачки {number}**. "
                "Оберіть день:"
            ),
            view=OneSelectView(
                select
            ),
            ephemeral=True,
        )

    async def create_finish(
        self,
        interaction: discord.Interaction,
        timestamp: int,
    ):
        async with self.lock:
            uid = str(
                interaction.user.id
            )
            selected_role = (
                self.state["roles"].get(uid)
            )
            current, current_status = (
                user_pack(
                    self.state,
                    uid,
                )
            )

            if (
                not current
                or current_status != "leader"
            ):
                await interaction.response.edit_message(
                    content=(
                        "Ця пачка більше "
                        "не належить вам."
                    ),
                    view=None,
                )
                return

            if not selected_role:
                await interaction.response.edit_message(
                    content="Спочатку оберіть роль.",
                    view=None,
                )
                return

            current["leader_role"] = selected_role
            current["start_ts"] = timestamp
            number = current["number"]

            self.save()
            await self.refresh()

            channel = (
                self.bot.get_channel(
                    CHANNEL_ID
                )
                or await self.bot.fetch_channel(
                    CHANNEL_ID
                )
            )
            await channel.send(
                (
                    f"<@&{LEAGUE_ROLE_ID}> створено "
                    f"**Пачку {number}** на "
                    f"<t:{timestamp}:F>. "
                    f"PL: <@{uid}>."
                ),
                allowed_mentions=discord.AllowedMentions(
                    roles=True,
                    users=True,
                ),
            )

        await interaction.response.edit_message(
            content=(
                f"**Пачку {number}** створено. "
                "Ви PL і перший учасник."
            ),
            view=None,
        )

    async def pl_action(
        self,
        interaction: discord.Interaction,
        action: str,
    ):
        if not await self.ok_channel(
            interaction
        ):
            return

        p = next(
            (
                item
                for item in self.state["packs"]
                if str(item.get("leader_id"))
                == str(interaction.user.id)
            ),
            None,
        )

        if not p:
            await interaction.response.send_message(
                "Доступно тільки PL.",
                ephemeral=True,
            )
            return

        number = p["number"]

        if action == "refresh":
            await self.refresh()
            await interaction.response.send_message(
                "Оновлено.",
                ephemeral=True,
            )
            return

        if action == "pending":
            pending = p.get(
                "pending",
                [],
            )
            if not pending:
                await interaction.response.send_message(
                    "Заявок немає.",
                    ephemeral=True,
                )
                return

            text = "\n".join(
                (
                    f"{role_text(x.get('role'))} "
                    f"<@{x['user_id']}>"
                )
                for x in pending
            )
            await interaction.response.send_message(
                (
                    f"**Заявки до Пачки {number}:**\n"
                    f"{text}\n\n"
                    "Для прийняття обери в "
                    "**Керування PL** пункт "
                    "**Підтвердити заявку**."
                ),
                ephemeral=True,
            )
            return

        if action in (
            "approve",
            "reject",
        ):
            entries = p.get(
                "pending",
                [],
            )
        elif action in (
            "remove",
            "leader",
        ):
            entries = p.get(
                "members",
                [],
            )
        else:
            entries = []

        if action in (
            "approve",
            "reject",
            "remove",
            "leader",
        ):
            if not entries:
                await interaction.response.send_message(
                    (
                        "Заявок немає."
                        if action in (
                            "approve",
                            "reject",
                        )
                        else "Немає кого обирати."
                    ),
                    ephemeral=True,
                )
                return

            options = []
            for entry in entries[:25]:
                member = (
                    interaction.guild.get_member(
                        int(entry["user_id"])
                    )
                    if interaction.guild
                    else None
                )
                name = (
                    member.display_name
                    if member
                    else str(
                        entry["user_id"]
                    )
                )
                options.append(
                    discord.SelectOption(
                        label=f"{name} | {role_text(entry.get('role'))}"[:100],
                        value=str(
                            entry["user_id"]
                        ),
                    )
                )

            prompt = {
                "approve": "Кого підтвердити?",
                "reject": "Чию заявку відхилити?",
                "remove": "Кого видалити з пачки?",
                "leader": "Кому передати PL?",
            }[action]

            await interaction.response.send_message(
                prompt,
                view=OneSelectView(
                    SimpleSelect(
                        self,
                        "member",
                        options,
                        meta={
                            "pack": number,
                            "action": action,
                        },
                    )
                ),
                ephemeral=True,
            )
            return

        if action == "reschedule":
            select = SimpleSelect(
                self,
                "date",
                date_options(),
                meta={
                    "mode": "reschedule",
                    "pack": number,
                },
                placeholder="Оберіть день",
            )
            await interaction.response.send_message(
                "Оберіть новий день:",
                view=OneSelectView(
                    select
                ),
                ephemeral=True,
            )
            return

        if action == "cancel":
            await interaction.response.send_message(
                f"Скасувати Пачку {number}?",
                view=CancelView(
                    self,
                    number,
                    interaction.user.id,
                ),
                ephemeral=True,
            )

    async def member_action(
        self,
        interaction: discord.Interaction,
        number: int,
        action: str,
        target: int,
    ):
        async with self.lock:
            p = get_pack(
                self.state,
                number,
            )
            uid = str(
                target
            )

            if (
                not p
                or str(p.get("leader_id"))
                != str(interaction.user.id)
            ):
                await interaction.response.edit_message(
                    content="Ви вже не PL.",
                    view=None,
                )
                return

            if action == "approve":
                if (
                    confirmed_count(p)
                    >= MAX_MEMBERS
                ):
                    await interaction.response.edit_message(
                        content="Пачка вже 10/10.",
                        view=None,
                    )
                    return

                entry = next(
                    (
                        x
                        for x in p.get(
                            "pending",
                            [],
                        )
                        if str(x["user_id"])
                        == uid
                    ),
                    None,
                )
                if not entry:
                    await interaction.response.edit_message(
                        content="Заявку вже оброблено.",
                        view=None,
                    )
                    return

                p["pending"].remove(
                    entry
                )
                p["members"].append(
                    entry
                )
                message = (
                    f"<@{uid}> підтверджено "
                    f"в Пачку {number}."
                )

            elif action == "reject":
                p["pending"] = [
                    x
                    for x in p.get(
                        "pending",
                        [],
                    )
                    if str(x["user_id"])
                    != uid
                ]
                message = (
                    "Заявку відхилено."
                )

            elif action == "remove":
                p["members"] = [
                    x
                    for x in p.get(
                        "members",
                        [],
                    )
                    if str(x["user_id"])
                    != uid
                ]
                message = (
                    f"<@{uid}> видалено "
                    f"з Пачки {number}."
                )

            elif action == "leader":
                entry = next(
                    (
                        x
                        for x in p.get(
                            "members",
                            [],
                        )
                        if str(x["user_id"])
                        == uid
                    ),
                    None,
                )
                if not entry:
                    await interaction.response.edit_message(
                        content="Учасника вже немає.",
                        view=None,
                    )
                    return

                old_leader = {
                    "user_id": str(
                        p["leader_id"]
                    ),
                    "role": p.get(
                        "leader_role"
                    ),
                }

                p["members"].remove(
                    entry
                )
                p["members"].insert(
                    0,
                    old_leader,
                )
                p["leader_id"] = uid
                p["leader_role"] = (
                    entry.get("role")
                )
                message = (
                    f"PL передано <@{uid}>."
                )
            else:
                await interaction.response.edit_message(
                    content="Невідома дія.",
                    view=None,
                )
                return

            self.save()
            await self.refresh()

        await interaction.response.edit_message(
            content=message,
            view=None,
        )

    async def reschedule_finish(
        self,
        interaction: discord.Interaction,
        number: int,
        timestamp: int,
    ):
        p = get_pack(
            self.state,
            number,
        )
        if (
            not p
            or str(p.get("leader_id"))
            != str(interaction.user.id)
        ):
            await interaction.response.edit_message(
                content="Ви вже не PL.",
                view=None,
            )
            return

        p["start_ts"] = timestamp
        self.save()
        await self.refresh()

        await interaction.response.edit_message(
            content=(
                f"Час змінено на "
                f"<t:{timestamp}:F>."
            ),
            view=None,
        )

    async def cancel(
        self,
        interaction: discord.Interaction,
        number: int,
    ):
        p = get_pack(
            self.state,
            number,
        )
        if (
            not p
            or str(p.get("leader_id"))
            != str(interaction.user.id)
        ):
            await interaction.response.edit_message(
                content="Ви вже не PL.",
                view=None,
            )
            return

        self.state["packs"] = [
            item
            for item in self.state["packs"]
            if int(item["number"])
            != int(number)
        ]

        for index, item in enumerate(
            self.state["packs"],
            1,
        ):
            item["number"] = index

        self.save()
        await self.refresh()

        await interaction.response.edit_message(
            content=(
                f"Пачку {number} скасовано. "
                "Нумерацію оновлено."
            ),
            view=None,
        )

    async def ensure_first_pack(
        self,
        interaction: discord.Interaction,
    ):
        if self.state["packs"]:
            return

        uid = str(
            interaction.user.id
        )
        self.state["packs"].append(
            {
                "number": 1,
                "leader_id": uid,
                "leader_role": (
                    self.state["roles"].get(
                        uid
                    )
                ),
                "start_ts": None,
                "members": [],
                "pending": [],
            }
        )
        self.save()

    @app_commands.command(
        name="guild_league_panel",
        description="Створити або оновити панель Ліги гільдій",
    )
    @app_commands.guilds(
        discord.Object(
            id=GUILD_ID
        )
    )
    async def panel(
        self,
        interaction: discord.Interaction,
    ):
        is_admin = (
            interaction.user
            .guild_permissions
            .administrator
        )
        has_league_role = (
            isinstance(
                interaction.user,
                discord.Member,
            )
            and any(
                role.id
                == LEAGUE_ROLE_ID
                for role
                in interaction.user.roles
            )
        )

        if not (
            is_admin
            or has_league_role
        ):
            await interaction.response.send_message(
                (
                    "Команда доступна учасникам "
                    f"<@&{LEAGUE_ROLE_ID}>."
                ),
                ephemeral=True,
            )
            return

        if (
            interaction.channel_id
            != CHANNEL_ID
        ):
            await interaction.response.send_message(
                f"Запустіть у <#{CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        await self.ensure_first_pack(
            interaction
        )

        existing = await self.fetch_panel_message()
        embeds = [
            pack_embed(
                number,
                get_pack(
                    self.state,
                    number,
                ),
                self.bot.user,
            )
            for number
            in range(
                1,
                MAX_PACKS + 1,
            )
        ]

        if existing:
            await existing.edit(
                embeds=embeds,
                view=MainView(self),
            )
            await interaction.response.send_message(
                (
                    "Панель Ліги оновлено. "
                    f"{existing.jump_url}"
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embeds=embeds,
            view=MainView(self),
        )

        message = (
            await interaction.original_response()
        )
        self.state["message_id"] = (
            message.id
        )
        self.save()


async def setup(
    bot: commands.Bot,
):
    await bot.add_cog(
        GuildLeagueCog(bot)
    )
