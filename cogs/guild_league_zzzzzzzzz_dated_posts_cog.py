from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands


DATA_FILE = Path("data/guild_league_dates.json")
MAX_MEMBERS = 10
SLOTS_PER_PAGE = 25


def load_data() -> dict:
    if not DATA_FILE.exists():
        return {"events": {}}
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"events": {}}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("events"), dict):
        data["events"] = {}
    return data


def save_data(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


def clock(ts: int, tz) -> str:
    return datetime.fromtimestamp(int(ts), tz).strftime("%H:%M")


def make_slots(day_iso: str, tz) -> list[dict]:
    day = datetime.fromisoformat(day_iso).date()
    start_hour = 13 if day.weekday() >= 5 else 17
    current = datetime(day.year, day.month, day.day, start_hour, 0, tzinfo=tz)
    end = datetime(day.year, day.month, day.day, 1, 0, tzinfo=tz) + timedelta(days=1)
    slots = []
    number = 1
    while current <= end:
        slots.append(
            {
                "number": number,
                "start_ts": int(current.timestamp()),
                "members": [],
                "waitlist": [],
                "enabled": True,
            }
        )
        number += 1
        current += timedelta(minutes=20)
    return slots


def find_entry(slot: dict, uid: str):
    for kind in ("members", "waitlist"):
        for entry in slot.get(kind, []):
            if str(entry.get("user_id")) == str(uid):
                return kind, entry
    return None, None


def promote(slot: dict):
    if len(slot.get("members", [])) >= MAX_MEMBERS:
        return None
    waitlist = slot.get("waitlist", [])
    if not waitlist:
        return None
    entry = waitlist.pop(0)
    slot.setdefault("members", []).append(entry)
    return entry


class DateTimeSelect(discord.ui.Select):
    def __init__(self, cog, day_iso: str, slots: list[dict]):
        options = []
        for slot in slots[:SLOTS_PER_PAGE]:
            count = len(slot.get("members", []))
            waiting = len(slot.get("waitlist", []))
            extra = f" +{waiting}" if waiting else ""
            options.append(
                discord.SelectOption(
                    label=f"{clock(slot['start_ts'], cog.league.TZ)} • {count}/10{extra}",
                    value=str(slot["number"]),
                    description=(
                        "Склад 10/10. Запис у лист очікування"
                        if count >= MAX_MEMBERS
                        else f"Вільно {MAX_MEMBERS - count} місць"
                    ),
                )
            )
        super().__init__(
            placeholder="Обери один або кілька часів",
            options=options,
            min_values=1,
            max_values=max(1, len(options)),
        )
        self.cog = cog
        self.day_iso = day_iso

    async def callback(self, interaction: discord.Interaction):
        await self.cog.add_times(interaction, self.day_iso, self.values)


class DateTimeView(discord.ui.View):
    def __init__(self, cog, day_iso: str, slots: list[dict], page: int = 0):
        super().__init__(timeout=180)
        self.cog = cog
        self.day_iso = day_iso
        self.slots = slots
        self.page = page

        start = page * SLOTS_PER_PAGE
        chunk = slots[start:start + SLOTS_PER_PAGE]
        if chunk:
            self.add_item(DateTimeSelect(cog, day_iso, chunk))

        all_btn = discord.ui.Button(
            label="Записатися на всі часи",
            emoji="✅",
            style=discord.ButtonStyle.success,
            row=1,
        )

        async def all_times(interaction):
            values = [str(x["number"]) for x in slots if x.get("enabled", True)]
            await self.cog.add_times(interaction, day_iso, values)

        all_btn.callback = all_times
        self.add_item(all_btn)

        if len(slots) > SLOTS_PER_PAGE:
            prev_btn = discord.ui.Button(
                label="Раніше",
                style=discord.ButtonStyle.secondary,
                disabled=page == 0,
                row=2,
            )
            next_btn = discord.ui.Button(
                label="Пізніше",
                style=discord.ButtonStyle.secondary,
                disabled=(page + 1) * SLOTS_PER_PAGE >= len(slots),
                row=2,
            )

            async def previous(interaction):
                new_page = max(0, page - 1)
                await interaction.response.edit_message(
                    content=self.cog.signup_text(day_iso, slots, new_page),
                    view=DateTimeView(cog, day_iso, slots, new_page),
                )

            async def next_page(interaction):
                new_page = page + 1
                await interaction.response.edit_message(
                    content=self.cog.signup_text(day_iso, slots, new_page),
                    view=DateTimeView(cog, day_iso, slots, new_page),
                )

            prev_btn.callback = previous
            next_btn.callback = next_page
            self.add_item(prev_btn)
            self.add_item(next_btn)


class DatedPanelView(discord.ui.View):
    def __init__(self, cog, day_iso: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.day_iso = day_iso
        compact = day_iso.replace("-", "")

        for key, style in (
            ("tank", discord.ButtonStyle.primary),
            ("dps", discord.ButtonStyle.danger),
            ("shai", discord.ButtonStyle.success),
        ):
            button = discord.ui.Button(
                label=cog.league.ROLES[key][1],
                emoji=cog.league.ROLES[key][0],
                style=style,
                custom_id=f"gl_date_{compact}_role_{key}",
                row=0,
            )

            async def choose(interaction, selected=key):
                await cog.set_date_role(interaction, day_iso, selected)

            button.callback = choose
            self.add_item(button)

        signup = discord.ui.Button(
            label="Записатися",
            emoji="✅",
            style=discord.ButtonStyle.success,
            custom_id=f"gl_date_{compact}_signup",
            row=1,
        )
        cant = discord.ui.Button(
            label="Не можу",
            emoji="✖️",
            style=discord.ButtonStyle.danger,
            custom_id=f"gl_date_{compact}_cant",
            row=1,
        )
        help_btn = discord.ui.Button(
            label="Допомога",
            emoji="❔",
            style=discord.ButtonStyle.secondary,
            custom_id=f"gl_date_{compact}_help",
            row=1,
        )

        async def signup_cb(interaction):
            await cog.begin_date_signup(interaction, day_iso)

        async def cant_cb(interaction):
            await cog.leave_date(interaction, day_iso)

        async def help_cb(interaction):
            await cog.help_date(interaction, day_iso)

        signup.callback = signup_cb
        cant.callback = cant_cb
        help_btn.callback = help_cb
        self.add_item(signup)
        self.add_item(cant)
        self.add_item(help_btn)


class PostDaySelect(discord.ui.Select):
    def __init__(self, cog):
        now = datetime.now(cog.league.TZ)
        days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
        options = []
        for offset in range(14):
            day = (now + timedelta(days=offset)).date()
            options.append(
                discord.SelectOption(
                    label=f"{days[day.weekday()]}, {day:%d.%m.%Y}",
                    value=day.isoformat(),
                    description=(
                        "13:00 - 01:00" if day.weekday() >= 5 else "17:00 - 01:00"
                    ),
                )
            )
        super().__init__(
            placeholder="Обери дату реєстрації",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        await self.cog.post_date(interaction, self.values[0])


class PostDayView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=180)
        self.add_item(PostDaySelect(cog))


class GuildLeagueDatedPosts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        from cogs import guild_league_cog as league
        self.league = league
        self.data = load_data()

    async def cog_load(self):
        today = datetime.now(self.league.TZ).date().isoformat()
        for day_iso, event in self.data.get("events", {}).items():
            if day_iso >= today and event.get("message_id"):
                self.bot.add_view(DatedPanelView(self, day_iso))

    def save(self):
        save_data(self.data)

    def event(self, day_iso: str):
        return self.data.setdefault("events", {}).get(day_iso)

    def build_embeds(self, day_iso: str):
        event = self.event(day_iso)
        if not event:
            return []
        day = datetime.fromisoformat(day_iso).date()
        pl = event.get("pl_user_id")
        header = discord.Embed(
            title=f"Ліга гільдій • {day:%d.%m.%Y}",
            description=(
                "Обери **Tank / DPS / Shai**, натисни **Записатися** і "
                "вибери **один або кілька часів**, коли можеш грати."
            ),
            color=self.league.COLOR,
        )
        header.add_field(name="Дата", value=day.strftime("%d.%m.%Y"), inline=True)
        header.add_field(name="PL", value=f"<@{pl}>" if pl else "не визначений", inline=True)
        header.add_field(name="Паті", value="максимум 10 + лист очікування", inline=True)

        embeds = [header]
        slots = event.get("slots", [])
        group_size = 9
        for start in range(0, len(slots), group_size):
            group = slots[start:start + group_size]
            embed = discord.Embed(color=self.league.COLOR)
            for col_start in range(0, 9, 3):
                col = group[col_start:col_start + 3]
                blocks = []
                for slot in col:
                    members = slot.get("members", [])
                    waitlist = slot.get("waitlist", [])
                    extra = f" +{len(waitlist)}" if waitlist else ""
                    lines = [
                        f"**{clock(slot['start_ts'], self.league.TZ)} ({len(members)}/10{extra})**"
                    ]
                    lines.extend(
                        f"{self.league.role_text(x.get('role'))} <@{x['user_id']}>"
                        for x in members
                    )
                    if waitlist:
                        lines.append("- лист очікування -")
                        lines.extend(
                            f"{self.league.role_text(x.get('role'))} <@{x['user_id']}>"
                            for x in waitlist
                        )
                    blocks.append("\n".join(lines))
                embed.add_field(
                    name="\u200b",
                    value="\n\n".join(blocks)[:1024] if blocks else "\u200b",
                    inline=True,
                )
            embeds.append(embed)
        if embeds:
            embeds[-1].set_footer(text=self.league.FOOTER)
        return embeds[:10]

    async def refresh_date(self, day_iso: str):
        event = self.event(day_iso)
        if not event or not event.get("message_id"):
            return
        channel = self.bot.get_channel(self.league.CHANNEL_ID) or await self.bot.fetch_channel(self.league.CHANNEL_ID)
        try:
            message = await channel.fetch_message(int(event["message_id"]))
        except Exception:
            return
        await message.edit(
            embeds=self.build_embeds(day_iso),
            view=DatedPanelView(self, day_iso),
        )

    def signup_text(self, day_iso: str, slots: list[dict], page: int = 0):
        start = page * SLOTS_PER_PAGE
        chunk = slots[start:start + SLOTS_PER_PAGE]
        day = datetime.fromisoformat(day_iso).date()
        if not chunk:
            return "Немає доступних часів."
        return (
            f"**Запис на {day:%d.%m.%Y}**\n"
            "**Обери ВСІ часи, коли можеш грати.** "
            "Можна вибрати кілька рядків одночасно."
        )

    async def set_date_role(self, interaction, day_iso: str, role_key: str):
        event = self.event(day_iso)
        if not event:
            await interaction.response.send_message("Ця реєстрація вже недоступна.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        event.setdefault("roles", {})[uid] = role_key
        for slot in event.get("slots", []):
            for kind in ("members", "waitlist"):
                for entry in slot.get(kind, []):
                    if str(entry.get("user_id")) == uid:
                        entry["role"] = role_key
        self.save()
        await self.refresh_date(day_iso)
        await interaction.response.send_message(
            f"Обрано **{self.league.role_text(role_key)}**.", ephemeral=True
        )

    async def begin_date_signup(self, interaction, day_iso: str):
        event = self.event(day_iso)
        if not event:
            await interaction.response.send_message("Ця реєстрація вже недоступна.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        if not event.get("roles", {}).get(uid):
            await interaction.response.send_message(
                "Спочатку обери **Tank**, **DPS** або **Shai**.", ephemeral=True
            )
            return
        slots = [x for x in event.get("slots", []) if x.get("enabled", True)]
        await interaction.response.send_message(
            self.signup_text(day_iso, slots, 0),
            view=DateTimeView(self, day_iso, slots, 0),
            ephemeral=True,
        )

    async def add_times(self, interaction, day_iso: str, values):
        event = self.event(day_iso)
        if not event:
            await interaction.response.edit_message(content="Ця реєстрація вже недоступна.", view=None)
            return
        uid = str(interaction.user.id)
        role_key = event.get("roles", {}).get(uid)
        if not role_key:
            await interaction.response.edit_message(content="Спочатку обери роль.", view=None)
            return
        wanted = {int(x) for x in values}
        lines = []
        now_ts = int(datetime.now(self.league.TZ).timestamp())
        for slot in event.get("slots", []):
            if int(slot.get("number", 0)) not in wanted or not slot.get("enabled", True):
                continue
            kind, _ = find_entry(slot, uid)
            time_text = clock(slot["start_ts"], self.league.TZ)
            if kind:
                lines.append(f"▫️ {time_text} - вже записаний")
                continue
            entry = {"user_id": uid, "role": role_key, "signed_at": now_ts}
            if len(slot.get("members", [])) < MAX_MEMBERS:
                slot.setdefault("members", []).append(entry)
                lines.append(f"✅ {time_text} - склад {len(slot['members'])}/10")
            else:
                slot.setdefault("waitlist", []).append(entry)
                lines.append(f"✅ {time_text} - лист очікування +{len(slot['waitlist'])}")
        self.save()
        await self.refresh_date(day_iso)
        await interaction.response.edit_message(
            content="**Твій запис:**\n" + ("\n".join(lines) if lines else "Нічого не змінено."),
            view=None,
        )

    async def leave_date(self, interaction, day_iso: str):
        event = self.event(day_iso)
        if not event:
            await interaction.response.send_message("Ця реєстрація вже недоступна.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        removed = []
        for slot in event.get("slots", []):
            for kind in ("members", "waitlist"):
                before = slot.get(kind, [])
                after = [x for x in before if str(x.get("user_id")) != uid]
                if len(after) != len(before):
                    slot[kind] = after
                    removed.append(clock(slot["start_ts"], self.league.TZ))
                    if kind == "members":
                        promote(slot)
                    break
        self.save()
        await self.refresh_date(day_iso)
        await interaction.response.send_message(
            "Записи скасовано." + ("\nЧаси: " + ", ".join(removed) if removed else ""),
            ephemeral=True,
        )

    async def help_date(self, interaction, day_iso: str):
        await interaction.response.send_message(
            (
                "**Як записатися:**\n"
                "1. Обери **Tank / DPS / Shai**.\n"
                "2. Натисни **Записатися**.\n"
                "3. Обери **один або кілька часів** одночасно.\n\n"
                "У кожному паті максимум **10 людей**. Після 10/10 запис іде "
                "в **лист очікування**. **Не можу** скасовує всі записи на цю дату."
            ),
            ephemeral=True,
        )

    async def post_date(self, interaction, day_iso: str):
        await interaction.response.defer(ephemeral=True)
        events = self.data.setdefault("events", {})
        event = events.get(day_iso)
        if not event:
            event = {
                "message_id": None,
                "pl_user_id": str(interaction.user.id),
                "roles": {},
                "slots": make_slots(day_iso, self.league.TZ),
            }
            events[day_iso] = event
        elif not event.get("pl_user_id"):
            event["pl_user_id"] = str(interaction.user.id)

        channel = self.bot.get_channel(self.league.CHANNEL_ID) or await self.bot.fetch_channel(self.league.CHANNEL_ID)
        message = None
        if event.get("message_id"):
            try:
                message = await channel.fetch_message(int(event["message_id"]))
            except Exception:
                message = None

        view = DatedPanelView(self, day_iso)
        if message:
            await message.edit(embeds=self.build_embeds(day_iso), view=view)
        else:
            day = datetime.fromisoformat(day_iso).date()
            message = await channel.send(
                content=f"<@&{self.league.LEAGUE_ROLE_ID}> реєстрація на **{day:%d.%m.%Y}**",
                embeds=self.build_embeds(day_iso),
                view=view,
                allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False),
            )
            event["message_id"] = str(message.id)
            self.bot.add_view(DatedPanelView(self, day_iso))
        self.save()
        await interaction.followup.send(
            f"Реєстрацію на **{datetime.fromisoformat(day_iso).date():%d.%m.%Y}** запощено: {message.jump_url}",
            ephemeral=True,
        )

    @app_commands.command(
        name="guild_league_post",
        description="Запостити реєстрацію Ліги гільдій наперед на вибрану дату",
    )
    @app_commands.guilds(discord.Object(id=1323454227816906802))
    async def guild_league_post(self, interaction: discord.Interaction):
        is_admin = interaction.user.guild_permissions.administrator
        has_role = (
            isinstance(interaction.user, discord.Member)
            and any(r.id == self.league.LEAGUE_ROLE_ID for r in interaction.user.roles)
        )
        if not (is_admin or has_role):
            await interaction.response.send_message("Немає доступу до цієї команди.", ephemeral=True)
            return
        if interaction.channel_id != self.league.CHANNEL_ID:
            await interaction.response.send_message(
                f"Запусти команду в <#{self.league.CHANNEL_ID}>.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            "**Обери дату, на яку хочеш запостити реєстрацію:**",
            view=PostDayView(self),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(GuildLeagueDatedPosts(bot))
