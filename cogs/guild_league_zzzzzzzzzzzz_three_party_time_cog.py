from __future__ import annotations

from datetime import datetime

import discord


PARTIES_PER_TIME = 3
MAX_MEMBERS = 10
SLOTS_PER_PAGE = 25
SLOTS_PER_EMBED = 4


def _role_icon(league, role_key):
    role = league.ROLES.get(role_key or "")
    return role[0] if role else "❔"


def _clean_entry(entry):
    if not isinstance(entry, dict):
        return None
    uid = str(entry.get("user_id") or "")
    if not uid:
        return None
    result = {
        "user_id": uid,
        "role": entry.get("role"),
    }
    if entry.get("signed_at") is not None:
        result["signed_at"] = entry.get("signed_at")
    return result


def _clean_entries(entries):
    result = []
    seen = set()
    for raw in entries or []:
        entry = _clean_entry(raw)
        if not entry or entry["user_id"] in seen:
            continue
        result.append(entry)
        seen.add(entry["user_id"])
    return result


def _empty_party(number):
    return {
        "number": number,
        "members": [],
        "waitlist": [],
    }


def _normalize_slot(slot):
    """Migrate one old single-party slot into 3 parties without losing users."""
    if not isinstance(slot, dict):
        return slot

    raw_parties = slot.get("parties")
    parties = []

    if isinstance(raw_parties, list) and raw_parties:
        for number in range(1, PARTIES_PER_TIME + 1):
            raw = next(
                (
                    p for p in raw_parties
                    if isinstance(p, dict) and int(p.get("number", 0)) == number
                ),
                None,
            )
            if raw is None and number - 1 < len(raw_parties):
                candidate = raw_parties[number - 1]
                raw = candidate if isinstance(candidate, dict) else None
            raw = raw or {}
            parties.append(
                {
                    "number": number,
                    "members": _clean_entries(raw.get("members"))[:MAX_MEMBERS],
                    "waitlist": _clean_entries(raw.get("waitlist")),
                }
            )
    else:
        # Old format: members/waitlist lived directly on the time slot.
        old_members = _clean_entries(slot.get("members"))
        old_waitlist = _clean_entries(slot.get("waitlist"))
        parties = [_empty_party(i) for i in range(1, PARTIES_PER_TIME + 1)]

        for entry in old_members:
            target = next(
                (p for p in parties if len(p["members"]) < MAX_MEMBERS),
                None,
            )
            if target is None:
                parties[-1]["waitlist"].append(entry)
            else:
                target["members"].append(entry)
        parties[-1]["waitlist"].extend(old_waitlist)

    # A user may only occupy one place inside one time slot.
    seen = set()
    for party in parties:
        members = []
        for entry in party.get("members", []):
            uid = str(entry.get("user_id"))
            if uid in seen:
                continue
            members.append(entry)
            seen.add(uid)
        party["members"] = members[:MAX_MEMBERS]

    for party in parties:
        waitlist = []
        for entry in party.get("waitlist", []):
            uid = str(entry.get("user_id"))
            if uid in seen:
                continue
            waitlist.append(entry)
            seen.add(uid)
        party["waitlist"] = waitlist

    slot["parties"] = parties
    slot.pop("members", None)
    slot.pop("waitlist", None)
    slot.setdefault("enabled", True)
    return slot


def _slot_members(slot):
    return sum(len(p.get("members", [])) for p in slot.get("parties", []))


def _slot_waiting(slot):
    return sum(len(p.get("waitlist", [])) for p in slot.get("parties", []))


def _find_user(slot, uid):
    uid = str(uid)
    for party in slot.get("parties", []):
        for kind in ("members", "waitlist"):
            for entry in party.get(kind, []):
                if str(entry.get("user_id")) == uid:
                    return party, kind, entry
    return None, None, None


def _first_free_party(slot):
    return next(
        (
            party for party in slot.get("parties", [])
            if len(party.get("members", [])) < MAX_MEMBERS
        ),
        None,
    )


def _pop_first_waiting(slot):
    waiting = []
    for party in slot.get("parties", []):
        for index, entry in enumerate(party.get("waitlist", [])):
            signed_at = entry.get("signed_at")
            try:
                order = int(signed_at)
            except (TypeError, ValueError):
                order = 10**20
            waiting.append((order, party, index, entry))
    if not waiting:
        return None
    waiting.sort(key=lambda item: item[0])
    _order, party, index, entry = waiting[0]
    party["waitlist"].pop(index)
    return entry


def _promote(slot):
    promoted = []
    while True:
        target = _first_free_party(slot)
        if target is None:
            break
        entry = _pop_first_waiting(slot)
        if entry is None:
            break
        target.setdefault("members", []).append(entry)
        promoted.append((target, entry))
    return promoted


def _party_block(league, slot, party):
    members = party.get("members", [])
    waiting = party.get("waitlist", [])
    extra = f" +{len(waiting)}" if waiting else ""
    ts = int(slot["start_ts"])
    number = int(party.get("number", 1))
    keycap = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣"}.get(number, str(number))

    lines = [f"**{keycap} <t:{ts}:t> ({len(members)}/10{extra})**"]
    for entry in members:
        lines.append(f"{_role_icon(league, entry.get('role'))} <@{entry['user_id']}>")

    if waiting:
        lines.append("- очікування -")
        for entry in waiting:
            lines.append(f"{_role_icon(league, entry.get('role'))} <@{entry['user_id']}>")

    return "\n".join(lines) if len(lines) > 1 else lines[0] + "\n-"


class LocalTimeSelect(discord.ui.Select):
    def __init__(self, cog, day_iso, slots, page=0):
        options = []
        start = page * SLOTS_PER_PAGE
        for index, slot in enumerate(slots[:SLOTS_PER_PAGE], start=start + 1):
            members = _slot_members(slot)
            waiting = _slot_waiting(slot)
            extra = f" +{waiting}" if waiting else ""
            options.append(
                discord.SelectOption(
                    label=f"№{index} • {members}/30{extra}",
                    value=str(slot["number"]),
                    description=(
                        "3 паті заповнені, далі лист очікування"
                        if members >= PARTIES_PER_TIME * MAX_MEMBERS
                        else f"Вільно {PARTIES_PER_TIME * MAX_MEMBERS - members} місць"
                    )[:100],
                )
            )

        super().__init__(
            placeholder="Обери один або кілька номерів часу",
            options=options,
            min_values=1,
            max_values=max(1, len(options)),
        )
        self.cog = cog
        self.day_iso = day_iso

    async def callback(self, interaction):
        await self.cog.add_times(interaction, self.day_iso, self.values)


class LocalTimeView(discord.ui.View):
    def __init__(self, cog, day_iso, slots, page=0):
        super().__init__(timeout=180)
        self.cog = cog
        self.day_iso = day_iso
        self.slots = slots
        self.page = page

        start = page * SLOTS_PER_PAGE
        chunk = slots[start:start + SLOTS_PER_PAGE]
        if chunk:
            self.add_item(LocalTimeSelect(cog, day_iso, chunk, page))

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

        if len(slots) > SLOTS_PER_PAGE:
            previous = discord.ui.Button(
                label="Раніше",
                style=discord.ButtonStyle.secondary,
                disabled=page == 0,
                row=2,
            )
            later = discord.ui.Button(
                label="Пізніше",
                style=discord.ButtonStyle.secondary,
                disabled=(page + 1) * SLOTS_PER_PAGE >= len(slots),
                row=2,
            )

            async def go_previous(interaction):
                new_page = max(0, page - 1)
                await interaction.response.edit_message(
                    content=self.cog.signup_text(self.day_iso, self.slots, new_page),
                    view=LocalTimeView(self.cog, self.day_iso, self.slots, new_page),
                )

            async def go_later(interaction):
                new_page = page + 1
                await interaction.response.edit_message(
                    content=self.cog.signup_text(self.day_iso, self.slots, new_page),
                    view=LocalTimeView(self.cog, self.day_iso, self.slots, new_page),
                )

            previous.callback = go_previous
            later.callback = go_later
            self.add_item(previous)
            self.add_item(later)


async def setup(bot):
    """Final dated-league model: date -> time -> 3 parties, local Discord time."""
    from cogs import guild_league_zzzzzzzzz_dated_posts_cog as dated

    cog = bot.get_cog("GuildLeagueDatedPosts")
    if cog is None:
        print("[GUILD_LEAGUE][3PARTY] GuildLeagueDatedPosts not found")
        return

    # New future registrations are created directly in the 3-party structure.
    previous_make_slots = dated.make_slots

    def make_three_party_slots(day_iso, tz):
        slots = previous_make_slots(day_iso, tz)
        return [_normalize_slot(slot) for slot in slots]

    dated.make_slots = make_three_party_slots

    changed = False
    for event in cog.data.get("events", {}).values():
        for slot in event.get("slots", []):
            before = "parties" in slot
            _normalize_slot(slot)
            if not before:
                changed = True
    if changed:
        cog.save()

    def build_embeds_three(self, day_iso):
        event = self.event(day_iso)
        if not event:
            return []

        slots = [
            _normalize_slot(slot)
            for slot in event.get("slots", [])
            if slot.get("enabled", True)
        ]
        pl = event.get("pl_user_id")
        first_ts = int(slots[0]["start_ts"]) if slots else None

        header = discord.Embed(
            title="Ліга гільдій",
            description=(
                "**Tank / DPS / Shai → Записатися → обери всі часи, коли можеш.**\n"
                "На кожен час доступно до **3 паті по 10 гравців**. "
                "Час Discord показує кожному у його часовому поясі."
            ),
            color=self.league.COLOR,
        )
        header.add_field(
            name="Дата",
            value=f"<t:{first_ts}:D>" if first_ts else day_iso,
            inline=True,
        )
        header.add_field(
            name="PL",
            value=f"<@{pl}>" if pl else "не визначений",
            inline=True,
        )
        header.add_field(name="Формат", value="3 × 10 + очікування", inline=True)

        embeds = [header]
        for start in range(0, len(slots), SLOTS_PER_EMBED):
            group = slots[start:start + SLOTS_PER_EMBED]
            embed = discord.Embed(color=self.league.COLOR)
            for slot in group:
                parties = slot.get("parties", [])
                for number in range(1, PARTIES_PER_TIME + 1):
                    party = next(
                        (p for p in parties if int(p.get("number", 0)) == number),
                        _empty_party(number),
                    )
                    embed.add_field(
                        name="\u200b",
                        value=_party_block(self.league, slot, party)[:1024],
                        inline=True,
                    )
            embeds.append(embed)

        if embeds:
            embeds[-1].set_footer(text=self.league.FOOTER)
        return embeds[:10]

    dated.GuildLeagueDatedPosts.build_embeds = build_embeds_three

    def signup_text_three(self, day_iso, slots, page=0):
        start = page * SLOTS_PER_PAGE
        chunk = slots[start:start + SLOTS_PER_PAGE]
        if not chunk:
            return "Немає доступних часів."

        lines = [
            "**Обери ВСІ часи, коли можеш грати:**",
            "Час нижче Discord показує **у твоєму часовому поясі**.",
            "",
        ]
        for index, slot in enumerate(chunk, start=start + 1):
            members = _slot_members(slot)
            waiting = _slot_waiting(slot)
            extra = f" +{waiting} очікує" if waiting else ""
            lines.append(
                f"**№{index}**  <t:{int(slot['start_ts'])}:t>  •  {members}/30{extra}"
            )
        lines.append("\nУ меню нижче вибери **номери** потрібних часів одночасно.")
        return "\n".join(lines)[:3900]

    dated.GuildLeagueDatedPosts.signup_text = signup_text_three

    async def begin_date_signup_three(self, interaction, day_iso):
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
            _normalize_slot(slot)
            for slot in event.get("slots", [])
            if slot.get("enabled", True)
        ]
        if not slots:
            await interaction.response.send_message(
                "На цю дату немає доступних часів.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            self.signup_text(day_iso, slots, 0),
            view=LocalTimeView(self, day_iso, slots, 0),
            ephemeral=True,
        )

    dated.GuildLeagueDatedPosts.begin_date_signup = begin_date_signup_three

    async def set_date_role_three(self, interaction, day_iso, role_key):
        event = self.event(day_iso)
        if not event:
            await interaction.response.send_message(
                "Ця реєстрація вже недоступна.", ephemeral=True
            )
            return
        uid = str(interaction.user.id)
        event.setdefault("roles", {})[uid] = role_key
        for slot in event.get("slots", []):
            _normalize_slot(slot)
            for party in slot.get("parties", []):
                for kind in ("members", "waitlist"):
                    for entry in party.get(kind, []):
                        if str(entry.get("user_id")) == uid:
                            entry["role"] = role_key
        self.save()
        await self.refresh_date(day_iso)
        await interaction.response.send_message(
            f"Обрано **{self.league.role_text(role_key)}**.", ephemeral=True
        )

    dated.GuildLeagueDatedPosts.set_date_role = set_date_role_three

    async def add_times_three(self, interaction, day_iso, values):
        event = self.event(day_iso)
        if not event:
            await interaction.response.edit_message(
                content="Ця реєстрація вже недоступна.", view=None
            )
            return

        uid = str(interaction.user.id)
        role_key = event.get("roles", {}).get(uid)
        if not role_key:
            await interaction.response.edit_message(
                content="Спочатку обери роль.", view=None
            )
            return

        wanted = {int(value) for value in values}
        now_ts = int(datetime.now(self.league.TZ).timestamp())
        lines = []

        for slot in event.get("slots", []):
            _normalize_slot(slot)
            if int(slot.get("number", 0)) not in wanted or not slot.get("enabled", True):
                continue

            party, kind, _entry = _find_user(slot, uid)
            ts = int(slot["start_ts"])
            if party is not None:
                status = "у складі" if kind == "members" else "у листі очікування"
                lines.append(
                    f"▫️ <t:{ts}:t> - вже {status} Паті {party['number']}"
                )
                continue

            entry = {"user_id": uid, "role": role_key, "signed_at": now_ts}
            target = _first_free_party(slot)
            if target is not None:
                target.setdefault("members", []).append(entry)
                lines.append(
                    f"✅ <t:{ts}:t> - Паті {target['number']} "
                    f"({len(target['members'])}/10)"
                )
            else:
                target = slot["parties"][-1]
                target.setdefault("waitlist", []).append(entry)
                lines.append(
                    f"✅ <t:{ts}:t> - лист очікування +{_slot_waiting(slot)}"
                )

        self.save()
        await self.refresh_date(day_iso)
        await interaction.response.edit_message(
            content="**Твій запис:**\n" + ("\n".join(lines) if lines else "Нічого не змінено."),
            view=None,
        )

    dated.GuildLeagueDatedPosts.add_times = add_times_three

    async def leave_date_three(self, interaction, day_iso):
        event = self.event(day_iso)
        if not event:
            await interaction.response.send_message(
                "Ця реєстрація вже недоступна.", ephemeral=True
            )
            return

        uid = str(interaction.user.id)
        removed_times = []
        for slot in event.get("slots", []):
            _normalize_slot(slot)
            removed_here = False
            for party in slot.get("parties", []):
                for kind in ("members", "waitlist"):
                    before = party.get(kind, [])
                    after = [x for x in before if str(x.get("user_id")) != uid]
                    if len(after) != len(before):
                        party[kind] = after
                        removed_here = True
            if removed_here:
                removed_times.append(int(slot["start_ts"]))
                _promote(slot)

        self.save()
        await self.refresh_date(day_iso)
        times = ", ".join(f"<t:{ts}:t>" for ts in removed_times)
        await interaction.response.send_message(
            "Записи скасовано." + (f"\nЧаси: {times}" if times else ""),
            ephemeral=True,
        )

    dated.GuildLeagueDatedPosts.leave_date = leave_date_three

    async def help_date_three(self, interaction, day_iso):
        await interaction.response.send_message(
            (
                "**Як записатися**\n"
                "1. Обери **Tank / DPS / Shai**.\n"
                "2. Натисни **Записатися**.\n"
                "3. Відміть **один або кілька номерів часу одночасно**.\n\n"
                "На кожен час є максимум **3 паті по 10 людей**. "
                "Бот заповнює Паті 1, потім Паті 2, потім Паті 3. "
                "Після 30/30 наступні йдуть у **лист очікування**.\n"
                "Час Discord автоматично показує у твоєму часовому поясі.\n"
                "**Не можу** скасовує всі твої записи на цю дату."
            ),
            ephemeral=True,
        )

    dated.GuildLeagueDatedPosts.help_date = help_date_three

    # Repaint already-posted future registrations in the new compact 3-column layout.
    cog.save()
    today = datetime.now(cog.league.TZ).date().isoformat()
    for day_iso, event in list(cog.data.get("events", {}).items()):
        if day_iso < today or not event.get("message_id"):
            continue
        try:
            await cog.refresh_date(day_iso)
        except Exception as exc:
            print(
                f"[GUILD_LEAGUE][3PARTY][REFRESH] {day_iso} "
                f"{type(exc).__name__}: {exc}"
            )

    print(
        "[GUILD_LEAGUE] dated signup: local Discord time + 3 parties per time enabled"
    )
