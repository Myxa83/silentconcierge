# -*- coding: utf-8 -*-
"""Black Shrine daily interest and party finder.

Flow:
- eligible members mark themselves available today;
- one of them opens a party search;
- others request to join;
- PL approves/rejects requests;
- party members and PL can be changed;
- every state change is stored in MongoDB immediately.
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from data.gear_store import load_gear, get_member_gear
from data import shrine_store


GUILD_ID = 1323454227816906802
ROLE_SUFFERING = 1406569206815658077
MIN_AP = 336
SHRINE_SEARCH_CHANNEL_ID = 1546166344662392954
SHRINE_PARTY_CATEGORY_ID = 1494376243250987158
GEAR_CHANNEL_URL = (
    "https://discord.com/channels/"
    "1323454227816906802/1358443998603120824"
)

ROLE_MODERATOR = 1375070910138028044
ROLE_LEADER = 1323454517664157736
PANEL_POST_ROLES = {ROLE_MODERATOR, ROLE_LEADER}

TZ = ZoneInfo(os.getenv("SHRINE_TIMEZONE", "Europe/Berlin"))
COLOR = 0x05B2B4
FOOTER = "Silent Concierge by Myxa | Black Shrine"


def _stat(value) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else 0


def _gear_snapshot(gear: dict | None, display_name: str = "") -> dict:
    gear = gear or {}
    return {
        "display_name": display_name or str(gear.get("display_name") or ""),
        "ap": _stat(gear.get("ap")),
        "aap": _stat(gear.get("aap")),
        "dp": _stat(gear.get("dp")),
        "gs": _stat(gear.get("gs")),
        "link": str(gear.get("link") or ""),
    }


class CreatePartyModal(discord.ui.Modal, title="Пошук групи Black Shrine"):
    party_name = discord.ui.TextInput(
        label="Назва паті",
        placeholder="Наприклад: Принц без нервів",
        max_length=80,
    )
    activity = discord.ui.TextInput(
        label="Активність / бос",
        placeholder="Black Shrine Hard / Принц / будь-які боси",
        max_length=80,
        default="Black Shrine Hard",
    )
    time_text = discord.ui.TextInput(
        label="Коли",
        placeholder="Наприклад: 20:00 або зараз",
        max_length=80,
        default="Зараз",
    )
    notes = discord.ui.TextInput(
        label="Примітка",
        placeholder="Що саме хочеш пройти, скільки босів, побажання...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, cog: "ShrineCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog.create_party(
            interaction,
            party_name=str(self.party_name.value),
            activity=str(self.activity.value),
            time_text=str(self.time_text.value),
            notes=str(self.notes.value or ""),
        )


class EditPartyModal(discord.ui.Modal, title="Редагувати пошук групи"):
    party_name = discord.ui.TextInput(
        label="Назва паті",
        max_length=80,
    )
    activity = discord.ui.TextInput(
        label="Активність / бос",
        max_length=80,
    )
    time_text = discord.ui.TextInput(
        label="Коли",
        max_length=80,
    )
    notes = discord.ui.TextInput(
        label="Примітка",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, cog: "ShrineCog", party: dict):
        super().__init__()
        self.cog = cog
        self.party_id = str(party["_id"])
        self.party_name.default = str(party.get("party_name") or "shrine-party")
        self.activity.default = str(party.get("activity") or "Black Shrine")
        self.time_text.default = str(party.get("time_text") or "Не вказано")
        self.notes.default = str(party.get("notes") or "")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        party = await asyncio.to_thread(
            shrine_store.edit_party,
            self.party_id,
            interaction.user.id,
            party_name=str(self.party_name.value),
            activity=str(self.activity.value),
            time_text=str(self.time_text.value),
            notes=str(self.notes.value or ""),
        )
        if not party:
            await interaction.followup.send(
                "Не вдалося змінити паті. Перевір, що ти все ще ПЛ.",
                ephemeral=True,
            )
            return

        await self.cog.rename_party_channel(party)
        await self.cog.refresh_party(party)
        await self.cog.refresh_daily_panel()
        await interaction.followup.send("Пошук групи оновлено.", ephemeral=True)


class ShrineDailyView(discord.ui.View):
    def __init__(self, cog: "ShrineCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Хочу Shrine сьогодні",
        emoji="⚔️",
        style=discord.ButtonStyle.success,
        custom_id="shrine:daily:yes:v1",
    )
    async def yes(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        await interaction.response.defer(ephemeral=True)

        ok, reason, _snapshot = await self.cog.check_eligible(
            interaction.user
        )
        if not ok:
            await interaction.followup.send(reason, ephemeral=True)
            return

        day = self.cog.today()
        await asyncio.to_thread(
            shrine_store.set_today_member,
            day,
            interaction.user.id,
            interaction.user.display_name,
            True,
        )
        await self.cog.refresh_daily_panel(day)
        await interaction.followup.send(
            "Додано до списку бажаючих на сьогодні.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Не можу сьогодні",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        custom_id="shrine:daily:no:v1",
    )
    async def no(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        await interaction.response.defer(ephemeral=True)
        day = self.cog.today()

        active = await asyncio.to_thread(
            shrine_store.find_active_membership,
            day,
            interaction.user.id,
        )
        if active:
            await interaction.followup.send(
                "Ти вже в активній паті. Спочатку вийди з неї "
                "або попроси ПЛ замінити тебе.",
                ephemeral=True,
            )
            return

        await asyncio.to_thread(
            shrine_store.set_today_member,
            day,
            interaction.user.id,
            interaction.user.display_name,
            False,
        )
        await self.cog.refresh_daily_panel(day)
        await interaction.followup.send(
            "Прибрано зі списку на сьогодні.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Пошук групи",
        emoji="🔎",
        style=discord.ButtonStyle.primary,
        custom_id="shrine:daily:create:v1",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        await interaction.response.send_message(
            "Створення паті: введи **/shrine_create** у каналі "
            f"<#{SHRINE_SEARCH_CHANNEL_ID}>.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Оновити",
        emoji="🔄",
        style=discord.ButtonStyle.secondary,
        custom_id="shrine:daily:refresh:v1",
    )
    async def refresh(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        await interaction.response.defer(ephemeral=True)
        await self.cog.refresh_daily_panel()
        await interaction.followup.send("Список оновлено.", ephemeral=True)


class ShrinePartyView(discord.ui.View):
    def __init__(self, cog: "ShrineCog", *, disabled: bool = False):
        super().__init__(timeout=None)
        self.cog = cog
        if disabled:
            for item in self.children:
                item.disabled = True

    @discord.ui.button(
        label="Хочу в паті",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="shrine:party:join:v1",
    )
    async def join(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        await interaction.response.defer(ephemeral=True)
        party = await self.cog.party_from_interaction(interaction)
        if not party:
            await interaction.followup.send(
                "Цей пошук групи вже недоступний.",
                ephemeral=True,
            )
            return

        if party.get("status") != "searching":
            await interaction.followup.send(
                "ПЛ уже закрив прийом нових заявок.",
                ephemeral=True,
            )
            return

        ok, reason, snapshot = await self.cog.check_eligible(
            interaction.user
        )
        if not ok:
            await interaction.followup.send(reason, ephemeral=True)
            return

        if interaction.user.id in party.get("members", []):
            await interaction.followup.send(
                "Ти вже в цій паті.",
                ephemeral=True,
            )
            return
        if interaction.user.id in party.get("pending", []):
            await interaction.followup.send(
                "Твоя заявка вже очікує рішення ПЛ.",
                ephemeral=True,
            )
            return

        other = await asyncio.to_thread(
            shrine_store.find_active_membership,
            str(party.get("date")),
            interaction.user.id,
        )
        if other and str(other.get("_id")) != str(party.get("_id")):
            await interaction.followup.send(
                "Ти вже в іншій активній Shrine-паті.",
                ephemeral=True,
            )
            return

        await asyncio.to_thread(
            shrine_store.set_today_member,
            str(party.get("date")),
            interaction.user.id,
            interaction.user.display_name,
            True,
        )
        updated = await asyncio.to_thread(
            shrine_store.request_join,
            str(party["_id"]),
            interaction.user.id,
            snapshot,
        )
        if not updated:
            await interaction.followup.send(
                "Не вдалося подати заявку. Можливо, ПЛ щойно закрив пошук.",
                ephemeral=True,
            )
            return

        await self.cog.refresh_party(updated)
        await self.cog.refresh_daily_panel(str(party.get("date")))
        await interaction.followup.send(
            "Заявку відправлено ПЛ. Після підтвердження ти "
            "з'явишся в складі з актуальним гіром.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Відмовитись / Вийти",
        emoji="🚪",
        style=discord.ButtonStyle.secondary,
        custom_id="shrine:party:leave:v1",
    )
    async def leave(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        await interaction.response.defer(ephemeral=True)
        party = await self.cog.party_from_interaction(interaction)
        if not party:
            await interaction.followup.send(
                "Ця паті вже недоступна.",
                ephemeral=True,
            )
            return

        if int(party.get("leader_id", 0)) == interaction.user.id:
            await interaction.followup.send(
                "ПЛ не може вийти напряму. Спочатку передай ПЛ іншому "
                "учаснику через Керування ПЛ.",
                ephemeral=True,
            )
            return

        updated = await asyncio.to_thread(
            shrine_store.withdraw_or_decline,
            str(party["_id"]),
            interaction.user.id,
        )
        if not updated:
            await interaction.followup.send(
                "Ти не був у цій паті або заявці.",
                ephemeral=True,
            )
            return

        await self.cog.refresh_party(updated)
        await self.cog.refresh_daily_panel(str(party.get("date")))
        await interaction.followup.send(
            "Готово. Тебе прибрано з цієї паті/заявки.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Керування ПЛ",
        emoji="👑",
        style=discord.ButtonStyle.primary,
        custom_id="shrine:party:manage:v1",
    )
    async def manage(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ):
        party = await self.cog.party_from_interaction(interaction)
        if not party:
            await interaction.response.send_message(
                "Ця паті вже недоступна.",
                ephemeral=True,
            )
            return
        if int(party.get("leader_id", 0)) != interaction.user.id:
            await interaction.response.send_message(
                "Керування доступне тільки ПЛ цієї паті.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            self.cog.manage_summary(party),
            view=PartyManageView(self.cog, str(party["_id"])),
            ephemeral=True,
        )


class PartyManageView(discord.ui.View):
    def __init__(self, cog: "ShrineCog", party_id: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.party_id = party_id

    async def _party(self):
        return await asyncio.to_thread(
            shrine_store.get_party,
            self.party_id,
        )

    async def _leader_guard(self, interaction, party):
        if (
            not party
            or int(party.get("leader_id", 0)) != interaction.user.id
        ):
            await interaction.response.send_message(
                "Ти більше не ПЛ цієї паті.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Заявки",
        emoji="📨",
        style=discord.ButtonStyle.primary,
        row=0,
    )
    async def pending(self, interaction, _button):
        party = await self._party()
        if not await self._leader_guard(interaction, party):
            return
        await self.cog.show_pending(interaction, party)

    @discord.ui.button(
        label="Видалити",
        emoji="🗑️",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def remove(self, interaction, _button):
        party = await self._party()
        if not await self._leader_guard(interaction, party):
            return
        await self.cog.show_member_action(interaction, party, "remove")

    @discord.ui.button(
        label="Замінити",
        emoji="🔁",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def replace(self, interaction, _button):
        party = await self._party()
        if not await self._leader_guard(interaction, party):
            return
        await self.cog.show_replace_member(interaction, party)

    @discord.ui.button(
        label="Передати ПЛ",
        emoji="👑",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def transfer(self, interaction, _button):
        party = await self._party()
        if not await self._leader_guard(interaction, party):
            return
        await self.cog.show_member_action(interaction, party, "transfer")

    @discord.ui.button(
        label="Редагувати",
        emoji="✏️",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def edit(self, interaction, _button):
        party = await self._party()
        if not await self._leader_guard(interaction, party):
            return
        await interaction.response.send_modal(EditPartyModal(self.cog, party))

    @discord.ui.button(
        label="Закрити / відкрити пошук",
        emoji="🔒",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def toggle(self, interaction, _button):
        party = await self._party()
        if not await self._leader_guard(interaction, party):
            return

        await interaction.response.defer(ephemeral=True)
        updated = await asyncio.to_thread(
            shrine_store.toggle_search,
            self.party_id,
            interaction.user.id,
        )
        if not updated:
            await interaction.followup.send(
                "Не вдалося змінити стан пошуку.",
                ephemeral=True,
            )
            return

        await self.cog.refresh_party(updated)
        await self.cog.refresh_daily_panel(str(updated.get("date")))
        state = (
            "відкрито"
            if updated.get("status") == "searching"
            else "закрито"
        )
        await interaction.followup.send(
            f"Пошук групи {state}.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Завершити паті",
        emoji="🏁",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def complete(self, interaction, _button):
        party = await self._party()
        if not await self._leader_guard(interaction, party):
            return
        await interaction.response.send_message(
            "Завершити цю паті? Тимчасовий канал буде видалено, "
            "а історія паті залишиться в MongoDB.",
            view=ConfirmCompleteView(self.cog, self.party_id),
            ephemeral=True,
        )


class ConfirmCompleteView(discord.ui.View):
    def __init__(self, cog: "ShrineCog", party_id: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.party_id = party_id

    @discord.ui.button(label="Так, завершити", style=discord.ButtonStyle.success)
    async def yes(self, interaction, _button):
        await interaction.response.defer(ephemeral=True)
        party = await asyncio.to_thread(
            shrine_store.complete_party,
            self.party_id,
            interaction.user.id,
        )
        if not party:
            await interaction.followup.send(
                "Не вдалося завершити паті.",
                ephemeral=True,
            )
            return
        await self.cog.refresh_daily_panel(str(party.get("date")))
        await interaction.followup.send(
            "Паті завершено. Тимчасовий канал зараз буде видалено.",
            ephemeral=True,
        )

        channel = interaction.channel
        if (
            isinstance(channel, discord.TextChannel)
            and channel.category_id == SHRINE_PARTY_CATEGORY_ID
        ):
            await asyncio.sleep(1)
            try:
                await channel.delete(
                    reason=(
                        "Black Shrine party completed by "
                        f"{interaction.user} ({interaction.user.id})"
                    )
                )
            except Exception as error:
                print(
                    f"[SHRINE][DELETE][ERROR] channel={channel.id} "
                    f"{type(error).__name__}: {error}"
                )

    @discord.ui.button(label="Ні", style=discord.ButtonStyle.secondary)
    async def no(self, interaction, _button):
        await interaction.response.edit_message(
            content="Скасовано.",
            view=None,
        )


class PendingSelect(discord.ui.Select):
    def __init__(self, cog: "ShrineCog", party: dict, options: list[discord.SelectOption]):
        super().__init__(
            placeholder="Оберіть заявку",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.cog = cog
        self.party_id = str(party["_id"])

    async def callback(self, interaction: discord.Interaction):
        uid = int(self.values[0])
        await interaction.response.send_message(
            f"Заявка <@{uid}>",
            view=ReviewDecisionView(self.cog, self.party_id, uid),
            ephemeral=True,
        )


class PendingSelectView(discord.ui.View):
    def __init__(self, select: PendingSelect):
        super().__init__(timeout=180)
        self.add_item(select)


class ReviewDecisionView(discord.ui.View):
    def __init__(self, cog: "ShrineCog", party_id: str, user_id: int):
        super().__init__(timeout=180)
        self.cog = cog
        self.party_id = party_id
        self.user_id = int(user_id)

    @discord.ui.button(label="Прийняти", emoji="✅", style=discord.ButtonStyle.success)
    async def approve(self, interaction, _button):
        await interaction.response.defer(ephemeral=True)
        party = await asyncio.to_thread(shrine_store.get_party, self.party_id)
        if not party or int(party.get("leader_id", 0)) != interaction.user.id:
            await interaction.followup.send(
                "Ти більше не ПЛ цієї паті.",
                ephemeral=True,
            )
            return

        member = interaction.guild.get_member(self.user_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(self.user_id)
            except Exception:
                member = None
        if member is None:
            await interaction.followup.send(
                "Не знайшов цього користувача на сервері.",
                ephemeral=True,
            )
            return

        ok, reason, snapshot = await self.cog.check_eligible(member)
        if not ok:
            await interaction.followup.send(reason, ephemeral=True)
            return

        other = await asyncio.to_thread(
            shrine_store.find_active_membership,
            str(party.get("date")),
            self.user_id,
        )
        if other and str(other.get("_id")) != self.party_id:
            await interaction.followup.send(
                "Ця людина вже в іншій активній Shrine-паті.",
                ephemeral=True,
            )
            return

        updated = await asyncio.to_thread(
            shrine_store.approve_member,
            self.party_id,
            interaction.user.id,
            self.user_id,
            snapshot,
        )
        if not updated:
            await interaction.followup.send(
                "Не вдалося прийняти заявку: вона вже змінена "
                "або склад 5/5.",
                ephemeral=True,
            )
            return

        await asyncio.to_thread(
            shrine_store.remove_pending_from_other_parties,
            str(updated.get("date")),
            self.user_id,
            self.party_id,
        )
        await self.cog.refresh_party(updated)
        await self.cog.refresh_daily_panel(str(updated.get("date")))
        await interaction.followup.send(
            f"<@{self.user_id}> прийнято в паті.",
            ephemeral=True,
        )

    @discord.ui.button(label="Відхилити", emoji="❌", style=discord.ButtonStyle.danger)
    async def reject(self, interaction, _button):
        await interaction.response.defer(ephemeral=True)
        updated = await asyncio.to_thread(
            shrine_store.reject_member,
            self.party_id,
            interaction.user.id,
            self.user_id,
        )
        if not updated:
            await interaction.followup.send(
                "Заявки вже немає або ти більше не ПЛ.",
                ephemeral=True,
            )
            return

        await self.cog.refresh_party(updated)
        await interaction.followup.send(
            f"Заявку <@{self.user_id}> відхилено.",
            ephemeral=True,
        )


class MemberActionSelect(discord.ui.Select):
    def __init__(
        self,
        cog: "ShrineCog",
        party: dict,
        action: str,
        options: list[discord.SelectOption],
    ):
        labels = {
            "remove": "Кого видалити",
            "transfer": "Кому передати ПЛ",
        }
        super().__init__(
            placeholder=labels[action],
            min_values=1,
            max_values=1,
            options=options,
        )
        self.cog = cog
        self.party_id = str(party["_id"])
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        uid = int(self.values[0])
        await interaction.response.defer(ephemeral=True)

        if self.action == "remove":
            updated = await asyncio.to_thread(
                shrine_store.remove_member,
                self.party_id,
                interaction.user.id,
                uid,
            )
            message = f"<@{uid}> видалено зі складу."
        else:
            updated = await asyncio.to_thread(
                shrine_store.transfer_leader,
                self.party_id,
                interaction.user.id,
                uid,
            )
            message = f"ПЛ передано <@{uid}>."

        if not updated:
            await interaction.followup.send(
                "Дія не виконана. Склад або ПЛ уже змінилися.",
                ephemeral=True,
            )
            return

        await self.cog.refresh_party(updated)
        await self.cog.refresh_daily_panel(str(updated.get("date")))
        await interaction.followup.send(message, ephemeral=True)


class MemberActionView(discord.ui.View):
    def __init__(self, select: MemberActionSelect):
        super().__init__(timeout=180)
        self.add_item(select)


class ReplaceOldSelect(discord.ui.Select):
    def __init__(
        self,
        cog: "ShrineCog",
        party: dict,
        options: list[discord.SelectOption],
    ):
        super().__init__(
            placeholder="Кого замінити",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.cog = cog
        self.party_id = str(party["_id"])

    async def callback(self, interaction: discord.Interaction):
        old_uid = int(self.values[0])
        party = await asyncio.to_thread(shrine_store.get_party, self.party_id)
        if not party or int(party.get("leader_id", 0)) != interaction.user.id:
            await interaction.response.send_message(
                "Ти більше не ПЛ цієї паті.",
                ephemeral=True,
            )
            return

        pending = list(party.get("pending", []))
        if not pending:
            await interaction.response.send_message(
                "Немає заявок, ким можна замінити учасника.",
                ephemeral=True,
            )
            return

        options = await self.cog.user_options(
            interaction.guild,
            pending,
            include_gear=True,
        )
        await interaction.response.send_message(
            f"Ким замінити <@{old_uid}>?",
            view=ReplaceNewView(
                ReplaceNewSelect(
                    self.cog,
                    self.party_id,
                    old_uid,
                    options,
                )
            ),
            ephemeral=True,
        )


class ReplaceOldView(discord.ui.View):
    def __init__(self, select: ReplaceOldSelect):
        super().__init__(timeout=180)
        self.add_item(select)


class ReplaceNewSelect(discord.ui.Select):
    def __init__(
        self,
        cog: "ShrineCog",
        party_id: str,
        old_uid: int,
        options: list[discord.SelectOption],
    ):
        super().__init__(
            placeholder="Новий учасник",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.cog = cog
        self.party_id = party_id
        self.old_uid = int(old_uid)

    async def callback(self, interaction: discord.Interaction):
        new_uid = int(self.values[0])
        await interaction.response.defer(ephemeral=True)

        member = interaction.guild.get_member(new_uid)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(new_uid)
            except Exception:
                member = None
        if member is None:
            await interaction.followup.send(
                "Не знайшов нового учасника.",
                ephemeral=True,
            )
            return

        ok, reason, snapshot = await self.cog.check_eligible(member)
        if not ok:
            await interaction.followup.send(reason, ephemeral=True)
            return

        updated = await asyncio.to_thread(
            shrine_store.replace_member,
            self.party_id,
            interaction.user.id,
            self.old_uid,
            new_uid,
            snapshot,
        )
        if not updated:
            await interaction.followup.send(
                "Заміна не виконана. Склад або заявка вже змінилися.",
                ephemeral=True,
            )
            return

        await asyncio.to_thread(
            shrine_store.remove_pending_from_other_parties,
            str(updated.get("date")),
            new_uid,
            self.party_id,
        )
        await self.cog.refresh_party(updated)
        await self.cog.refresh_daily_panel(str(updated.get("date")))
        await interaction.followup.send(
            f"<@{self.old_uid}> замінено на <@{new_uid}>.",
            ephemeral=True,
        )


class ReplaceNewView(discord.ui.View):
    def __init__(self, select: ReplaceNewSelect):
        super().__init__(timeout=180)
        self.add_item(select)


class ShrineCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(ShrineDailyView(self))
        self.bot.add_view(ShrinePartyView(self))
        self._permission_task = asyncio.create_task(
            self.enforce_shrine_permissions()
        )
        print("[SHRINE] persistent views registered")

    def cog_unload(self):
        task = getattr(self, "_permission_task", None)
        if task and not task.done():
            task.cancel()

    async def enforce_shrine_permissions(self):
        await self.bot.wait_until_ready()

        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            return

        role = guild.get_role(ROLE_SUFFERING)
        if role is None:
            print("[SHRINE][PERMS] suffering role not found")
            return

        targets = []
        for channel_id in (
            SHRINE_SEARCH_CHANNEL_ID,
            SHRINE_PARTY_CATEGORY_ID,
        ):
            channel = guild.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await guild.fetch_channel(channel_id)
                except Exception:
                    channel = None
            if channel is not None:
                targets.append(channel)

        for target in targets:
            try:
                await target.set_permissions(
                    guild.default_role,
                    view_channel=False,
                    reason="Black Shrine is only for suffering role",
                )
                await target.set_permissions(
                    role,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    reason="Allow suffering role into Black Shrine",
                )
            except Exception as error:
                print(
                    f"[SHRINE][PERMS][ERROR] target={target.id} "
                    f"{type(error).__name__}: {error}"
                )

    def today(self) -> str:
        return datetime.now(TZ).date().isoformat()

    def can_post_panel(self, member: discord.Member) -> bool:
        if member.guild_permissions.manage_guild:
            return True
        return any(role.id in PANEL_POST_ROLES for role in member.roles)

    async def check_eligible(
        self,
        member: discord.Member,
    ) -> tuple[bool, str, dict]:
        if not isinstance(member, discord.Member):
            return False, "Ця дія доступна лише на сервері.", {}

        if not any(role.id == ROLE_SUFFERING for role in member.roles):
            return (
                False,
                "Для Shrine-пошуку потрібна роль Страждущі. "
                f"Мінімум для неї: {MIN_AP}+ main AP.",
                {},
            )

        gear = await asyncio.to_thread(get_member_gear, member.id)
        if not gear:
            return (
                False,
                "Я не бачу твого актуального гіру. Залиш публічне "
                f"Garmoth-посилання тут:\n{GEAR_CHANNEL_URL}",
                {},
            )

        ap = _stat(gear.get("ap"))
        if ap < MIN_AP:
            return (
                False,
                f"Твій main AP: {ap}. Для Shrine потрібно {MIN_AP}+ AP.",
                {},
            )

        return True, "", _gear_snapshot(gear, member.display_name)

    async def user_options(
        self,
        guild: discord.Guild,
        user_ids: list[int],
        *,
        include_gear: bool,
    ) -> list[discord.SelectOption]:
        gear_data = await asyncio.to_thread(load_gear)
        options = []

        for uid in user_ids[:25]:
            member = guild.get_member(int(uid))
            name = member.display_name if member else str(uid)
            description = None
            if include_gear:
                gear = gear_data.get(str(uid), {})
                description = (
                    f"AP {_stat(gear.get('ap'))} | "
                    f"DP {_stat(gear.get('dp'))} | "
                    f"GS {_stat(gear.get('gs'))}"
                )

            options.append(
                discord.SelectOption(
                    label=name[:100],
                    value=str(uid),
                    description=(description[:100] if description else None),
                )
            )

        return options

    async def party_from_interaction(
        self,
        interaction: discord.Interaction,
    ) -> dict | None:
        message = interaction.message
        if message is None:
            return None
        return await asyncio.to_thread(
            shrine_store.get_party_by_message,
            message.id,
        )

    async def build_daily_embed(self, day: str) -> discord.Embed:
        members, parties, gear_data = await asyncio.gather(
            asyncio.to_thread(shrine_store.list_today_members, day),
            asyncio.to_thread(shrine_store.list_active_parties, day),
            asyncio.to_thread(load_gear),
        )

        embed = discord.Embed(
            title="⚔️ Black Shrine — бажаючі сьогодні",
            description=(
                "Натисни **Хочу Shrine сьогодні**, щоб з'явитися у списку.\n"
                "Якщо готовий збирати людей — натисни **Пошук групи**."
            ),
            color=COLOR,
        )

        if members:
            lines = []
            for item in members[:15]:
                uid = int(item["user_id"])
                gear = gear_data.get(str(uid), {})
                lines.append(
                    f"• <@{uid}> — "
                    f"AP **{_stat(gear.get('ap'))}** | "
                    f"DP {_stat(gear.get('dp'))} | "
                    f"GS {_stat(gear.get('gs'))}"
                )
            if len(members) > 15:
                lines.append(f"… ще {len(members) - 15}")
            embed.add_field(
                name=f"Бажаючі ({len(members)})",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="Бажаючі (0)",
                value="Поки ніхто не відмітився.",
                inline=False,
            )

        active_lines = []
        for party in parties[:10]:
            leader = int(party.get("leader_id", 0))
            count = len(party.get("members", []))
            state = "🔎" if party.get("status") == "searching" else "🔒"
            active_lines.append(
                f"{state} **{party.get('party_name', 'Shrine party')}** • "
                f"<@{leader}> — **{count}/5** • "
                f"{party.get('activity', 'Black Shrine')} • "
                f"{party.get('time_text', 'Не вказано')}"
            )

        if active_lines:
            embed.add_field(
                name="Активні пошуки",
                value="\n".join(active_lines),
                inline=False,
            )

        embed.set_footer(text=f"{FOOTER} | {day}")
        return embed

    async def build_party_embed(self, party: dict) -> discord.Embed:
        gear_data = await asyncio.to_thread(load_gear)
        status = str(party.get("status") or "searching")
        status_text = {
            "searching": "🔎 Пошук відкрито",
            "closed": "🔒 Пошук закрито",
            "completed": "🏁 Паті завершено",
        }.get(status, status)

        leader_id = int(party.get("leader_id", 0))
        members = [int(uid) for uid in party.get("members", [])]
        snapshots = party.get("gear_snapshots", {}) or {}

        lines = []
        for uid in members:
            gear = gear_data.get(str(uid)) or snapshots.get(str(uid), {})
            icon = "👑" if uid == leader_id else "⚔️"
            lines.append(
                f"{icon} <@{uid}> — "
                f"AP **{_stat(gear.get('ap'))}** | "
                f"AAP {_stat(gear.get('aap'))} | "
                f"DP {_stat(gear.get('dp'))} | "
                f"GS {_stat(gear.get('gs'))}"
            )

        party_name = str(party.get("party_name") or "BLACK SHRINE PARTY")
        embed = discord.Embed(
            title=f"⚔️ {party_name}",
            color=COLOR if status != "completed" else 0x808080,
        )
        embed.add_field(
            name="Активність",
            value=str(party.get("activity") or "Black Shrine"),
            inline=False,
        )
        embed.add_field(
            name="Party Leader",
            value=f"<@{leader_id}>",
            inline=True,
        )
        embed.add_field(
            name="Вимога",
            value=f"{party.get('requirement_ap', MIN_AP)}+ AP",
            inline=True,
        )
        embed.add_field(
            name="Місця",
            value=f"{len(members)}/5",
            inline=True,
        )
        embed.add_field(
            name="Коли",
            value=str(party.get("time_text") or "Не вказано"),
            inline=False,
        )
        embed.add_field(
            name=f"Склад ({len(members)}/5)",
            value="\n".join(lines) if lines else "Порожньо",
            inline=False,
        )

        pending = list(party.get("pending", []))
        if pending and status != "completed":
            embed.add_field(
                name="Заявки очікують рішення ПЛ",
                value=f"**{len(pending)}**",
                inline=True,
            )

        notes = str(party.get("notes") or "").strip()
        if notes:
            embed.add_field(
                name="Примітка",
                value=notes[:1000],
                inline=False,
            )

        embed.add_field(name="Статус", value=status_text, inline=False)
        embed.set_footer(
            text=f"{FOOTER} | ID {party.get('_id')}"
        )
        return embed

    async def refresh_daily_panel(self, day: str | None = None) -> bool:
        day = day or self.today()
        panel = await asyncio.to_thread(shrine_store.get_daily_panel, day)
        if not panel:
            return False

        channel = self.bot.get_channel(int(panel["channel_id"]))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(
                    int(panel["channel_id"])
                )
            except Exception:
                return False

        try:
            message = await channel.fetch_message(int(panel["message_id"]))
        except Exception:
            return False

        embed = await self.build_daily_embed(day)
        try:
            await message.edit(embed=embed, view=ShrineDailyView(self))
            return True
        except Exception as error:
            print(
                f"[SHRINE][PANEL][ERROR] "
                f"{type(error).__name__}: {error}"
            )
            return False

    async def refresh_party(self, party: dict):
        channel_id = party.get("channel_id")
        message_id = party.get("message_id")
        if not channel_id or not message_id:
            return

        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except Exception:
                return

        try:
            message = await channel.fetch_message(int(message_id))
        except Exception:
            return

        embed = await self.build_party_embed(party)
        disabled = party.get("status") == "completed"
        try:
            await message.edit(
                embed=embed,
                view=ShrinePartyView(self, disabled=disabled),
            )
        except Exception as error:
            print(
                f"[SHRINE][PARTY][ERROR] "
                f"{type(error).__name__}: {error}"
            )

    async def create_party(
        self,
        interaction: discord.Interaction,
        *,
        party_name: str,
        activity: str,
        time_text: str,
        notes: str,
    ):
        ok, reason, snapshot = await self.check_eligible(interaction.user)
        if not ok:
            await interaction.followup.send(reason, ephemeral=True)
            return

        day = self.today()

        active = await asyncio.to_thread(
            shrine_store.find_active_membership,
            day,
            interaction.user.id,
        )
        if active:
            await interaction.followup.send(
                "Ти вже входиш до активної Shrine-паті.",
                ephemeral=True,
            )
            return

        await asyncio.to_thread(
            shrine_store.set_today_member,
            day,
            interaction.user.id,
            interaction.user.display_name,
            True,
        )

        guild = interaction.guild
        category = guild.get_channel(SHRINE_PARTY_CATEGORY_ID)
        if category is None:
            try:
                category = await guild.fetch_channel(
                    SHRINE_PARTY_CATEGORY_ID
                )
            except Exception:
                category = None

        if not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send(
                "Не знайшов категорію для Shrine-паті.",
                ephemeral=True,
            )
            return

        suffering_role = guild.get_role(ROLE_SUFFERING)
        bot_member = guild.me
        if suffering_role is None:
            await interaction.followup.send(
                "Не знайшов роль Страждущі.",
                ephemeral=True,
            )
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
            ),
            suffering_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                add_reactions=True,
            ),
        }
        if bot_member is not None:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
            )

        channel_name = self.party_channel_name(party_name)

        try:
            party_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=(
                    "Temporary Black Shrine party created by "
                    f"{interaction.user} ({interaction.user.id})"
                ),
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "Боту бракує **Manage Channels** для створення "
                "тимчасової Shrine-паті.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as error:
            await interaction.followup.send(
                f"Discord не дав створити канал: {error}",
                ephemeral=True,
            )
            return

        try:
            party = await asyncio.to_thread(
                shrine_store.create_party,
                day=day,
                leader_id=interaction.user.id,
                party_name=party_name,
                activity=activity,
                time_text=time_text,
                notes=notes,
                requirement_ap=MIN_AP,
                gear_snapshot=snapshot,
            )

            embed = await self.build_party_embed(party)
            message = await party_channel.send(
                embed=embed,
                view=ShrinePartyView(self),
            )

            party = await asyncio.to_thread(
                shrine_store.set_party_message,
                str(party["_id"]),
                party_channel.id,
                message.id,
            )
        except Exception:
            try:
                await party_channel.delete(
                    reason="Shrine party setup failed"
                )
            except Exception:
                pass
            raise

        await self.refresh_daily_panel(day)

        await interaction.followup.send(
            (
                f"Паті створено: {party_channel.mention}. "
                "Заявки потраплятимуть на підтвердження ПЛ."
            ),
            ephemeral=True,
        )

    @staticmethod
    def party_channel_name(value: str) -> str:
        name = str(value or "").strip().casefold()
        name = re.sub(r"\s+", "-", name)
        name = re.sub(r"[^\w\-]+", "-", name, flags=re.UNICODE)
        name = re.sub(r"-{2,}", "-", name).strip("-_")
        return (name or "shrine-party")[:90]

    async def rename_party_channel(self, party: dict) -> None:
        channel_id = party.get("channel_id")
        if not channel_id:
            return

        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except Exception:
                return

        if isinstance(channel, discord.TextChannel):
            target = self.party_channel_name(
                str(party.get("party_name") or "shrine-party")
            )
            if channel.name != target:
                try:
                    await channel.edit(
                        name=target,
                        reason="Shrine PL renamed party",
                    )
                except Exception as error:
                    print(
                        f"[SHRINE][RENAME][ERROR] "
                        f"{type(error).__name__}: {error}"
                    )

    def manage_summary(self, party: dict) -> str:
        return (
            f"Керування паті {party.get('_id')}\n"
            f"Склад: {len(party.get('members', []))}/5\n"
            f"Заявок: {len(party.get('pending', []))}\n"
            f"Статус: {party.get('status')}"
        )

    async def show_pending(
        self,
        interaction: discord.Interaction,
        party: dict,
    ):
        pending = [int(uid) for uid in party.get("pending", [])]
        if not pending:
            await interaction.response.send_message(
                "Заявок зараз немає.",
                ephemeral=True,
            )
            return

        options = await self.user_options(
            interaction.guild,
            pending,
            include_gear=True,
        )
        await interaction.response.send_message(
            "Оберіть заявку:",
            view=PendingSelectView(PendingSelect(self, party, options)),
            ephemeral=True,
        )

    async def show_member_action(
        self,
        interaction: discord.Interaction,
        party: dict,
        action: str,
    ):
        leader_id = int(party.get("leader_id", 0))
        members = [
            int(uid)
            for uid in party.get("members", [])
            if int(uid) != leader_id
        ]
        if not members:
            await interaction.response.send_message(
                "У паті немає інших учасників.",
                ephemeral=True,
            )
            return

        options = await self.user_options(
            interaction.guild,
            members,
            include_gear=True,
        )
        await interaction.response.send_message(
            "Оберіть учасника:",
            view=MemberActionView(
                MemberActionSelect(self, party, action, options)
            ),
            ephemeral=True,
        )

    async def show_replace_member(
        self,
        interaction: discord.Interaction,
        party: dict,
    ):
        if not party.get("pending"):
            await interaction.response.send_message(
                "Для заміни потрібна хоча б одна заявка в очікуванні.",
                ephemeral=True,
            )
            return

        leader_id = int(party.get("leader_id", 0))
        replaceable = [
            int(uid)
            for uid in party.get("members", [])
            if int(uid) != leader_id
        ]
        if not replaceable:
            await interaction.response.send_message(
                "Немає учасника, якого можна замінити.",
                ephemeral=True,
            )
            return

        options = await self.user_options(
            interaction.guild,
            replaceable,
            include_gear=True,
        )
        await interaction.response.send_message(
            "Кого замінити?",
            view=ReplaceOldView(
                ReplaceOldSelect(self, party, options)
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="shrine_create",
        description="Створити тимчасову Black Shrine паті",
    )
    async def shrine_create(self, interaction: discord.Interaction):
        if (
            not interaction.guild
            or not isinstance(interaction.user, discord.Member)
        ):
            await interaction.response.send_message(
                "Команда доступна тільки на сервері.",
                ephemeral=True,
            )
            return

        if interaction.channel_id != SHRINE_SEARCH_CHANNEL_ID:
            await interaction.response.send_message(
                "Створювати Shrine-паті можна тільки в каналі "
                f"<#{SHRINE_SEARCH_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        ok, reason, _snapshot = await self.check_eligible(
            interaction.user
        )
        if not ok:
            await interaction.response.send_message(
                reason,
                ephemeral=True,
            )
            return

        day = self.today()
        active = await asyncio.to_thread(
            shrine_store.find_active_membership,
            day,
            interaction.user.id,
        )
        if active:
            await interaction.response.send_message(
                "Ти вже входиш до активної Shrine-паті.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(CreatePartyModal(self))

    @app_commands.command(
        name="shrine_panel",
        description="Опублікувати або оновити список Black Shrine на сьогодні",
    )
    async def shrine_panel(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(
            interaction.user,
            discord.Member,
        ):
            await interaction.response.send_message(
                "Команда доступна тільки на сервері.",
                ephemeral=True,
            )
            return

        if interaction.channel_id != SHRINE_SEARCH_CHANNEL_ID:
            await interaction.response.send_message(
                "Shrine-панель можна публікувати тільки в каналі "
                f"<#{SHRINE_SEARCH_CHANNEL_ID}>.",
                ephemeral=True,
            )
            return

        if not self.can_post_panel(interaction.user):
            await interaction.response.send_message(
                "Немає доступу до публікації Shrine-панелі.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        day = self.today()

        panel = await asyncio.to_thread(shrine_store.get_daily_panel, day)
        if panel and await self.refresh_daily_panel(day):
            await interaction.followup.send(
                "Сьогоднішню Shrine-панель оновлено.",
                ephemeral=True,
            )
            return

        embed = await self.build_daily_embed(day)
        message = await interaction.channel.send(
            embed=embed,
            view=ShrineDailyView(self),
        )
        await asyncio.to_thread(
            shrine_store.save_daily_panel,
            day,
            message.channel.id,
            message.id,
        )
        await interaction.followup.send(
            "Shrine-панель на сьогодні опубліковано.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ShrineCog(bot))
    print("[COG] ShrineCog завантажено")
