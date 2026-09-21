# -*- coding: utf-8 -*-
# cogs/tempvoice_cog.py

from __future__ import annotations

import asyncio
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.http import Route

from data.mongo_store import load_state, save_state


STATE_COLLECTION = "tempvoice_state"
STATE_DOCUMENT_ID = "main"
STATUS_MAX_LENGTH = 500


class CreateVoiceModal(discord.ui.Modal):
    def __init__(self, cog: "TempVoiceCog", member: discord.Member) -> None:
        super().__init__(title="Створити голосовий канал", timeout=300)

        self.cog = cog
        self.member_id = member.id
        self.guild_id = member.guild.id

        self.channel_name = discord.ui.TextInput(
            label="Назва каналу",
            placeholder="Наприклад: Фарм гільдії",
            default=f"{member.display_name}",
            min_length=1,
            max_length=100,
            required=True,
        )
        self.channel_status = discord.ui.TextInput(
            label="Статус каналу",
            placeholder="Наприклад: Ми зайняті, не турбувати",
            style=discord.TextStyle.paragraph,
            max_length=STATUS_MAX_LENGTH,
            required=False,
        )
        self.user_limit = discord.ui.TextInput(
            label="Кількість людей",
            placeholder="0 = без ліміту, або число 1-99",
            default="0",
            min_length=1,
            max_length=2,
            required=True,
        )

        self.add_item(self.channel_name)
        self.add_item(self.channel_status)
        self.add_item(self.user_limit)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = self.cog.bot.get_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message("Не вдалося знайти сервер.", ephemeral=True)
            return

        member = guild.get_member(self.member_id)
        if member is None:
            await interaction.response.send_message("Не вдалося знайти користувача.", ephemeral=True)
            return

        name = str(self.channel_name.value).strip()
        status = str(self.channel_status.value or "").strip()
        raw_limit = str(self.user_limit.value).strip()

        try:
            limit = int(raw_limit)
        except ValueError:
            await interaction.response.send_message(
                "Кількість людей має бути числом від 0 до 99.",
                ephemeral=True,
            )
            return

        if not 0 <= limit <= 99:
            await interaction.response.send_message(
                "Кількість людей має бути від 0 до 99.",
                ephemeral=True,
            )
            return

        await self.cog.create_room(
            interaction=interaction,
            member=member,
            name=name,
            status=status,
            user_limit=limit,
        )


class TempVoiceCog(commands.Cog):
    voice = app_commands.Group(
        name="voice",
        description="Тимчасові голосові кімнати",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._lock = asyncio.Lock()
        self._state = self._load_state()

    def _load_state(self) -> dict:
        raw = load_state(
            STATE_COLLECTION,
            {"category_id": 0, "channels": {}},
            document_id=STATE_DOCUMENT_ID,
        )

        if not isinstance(raw, dict):
            raw = {}

        category_id = raw.get("category_id", 0)
        channels = raw.get("channels", {})

        try:
            category_id = int(category_id or 0)
        except (TypeError, ValueError):
            category_id = 0

        clean_channels: dict[str, int] = {}
        if isinstance(channels, dict):
            for channel_id, owner_id in channels.items():
                try:
                    clean_channels[str(int(channel_id))] = int(owner_id)
                except (TypeError, ValueError):
                    continue

        return {"category_id": category_id, "channels": clean_channels}

    def _save_state(self) -> None:
        save_state(
            STATE_COLLECTION,
            self._state,
            document_id=STATE_DOCUMENT_ID,
        )

    @property
    def category_id(self) -> int:
        try:
            return int(self._state.get("category_id", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def channels(self) -> dict[str, int]:
        channels = self._state.setdefault("channels", {})
        if not isinstance(channels, dict):
            channels = {}
            self._state["channels"] = channels
        return channels

    def _get_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        channel = guild.get_channel(self.category_id)
        return channel if isinstance(channel, discord.CategoryChannel) else None

    def _owner_id_for(self, channel_id: int) -> Optional[int]:
        value = self.channels.get(str(channel_id))
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _find_owned_channel(
        self,
        guild: discord.Guild,
        owner_id: int,
    ) -> Optional[discord.VoiceChannel]:
        for channel_id, mapped_owner_id in list(self.channels.items()):
            try:
                if int(mapped_owner_id) != owner_id:
                    continue
                channel = guild.get_channel(int(channel_id))
            except (TypeError, ValueError):
                continue

            if isinstance(channel, discord.VoiceChannel):
                return channel

        return None

    def _is_temp_channel(self, channel: Optional[discord.abc.GuildChannel]) -> bool:
        return isinstance(channel, discord.VoiceChannel) and str(channel.id) in self.channels

    async def _set_voice_status(
        self,
        channel: discord.VoiceChannel,
        status: str,
    ) -> bool:
        try:
            await self.bot.http.request(
                Route(
                    "PUT",
                    "/channels/{channel_id}/voice-status",
                    channel_id=channel.id,
                ),
                json={"status": status or None},
                reason="Temporary voice status changed",
            )
            return True
        except (discord.Forbidden, discord.HTTPException) as error:
            print(
                f"[TEMPVOICE][STATUS][ERROR] channel={channel.id} "
                f"{type(error).__name__}: {error}"
            )
            return False

    async def _delete_temp_channel(
        self,
        channel: discord.VoiceChannel,
        *,
        reason: str,
    ) -> None:
        channel_id = channel.id

        try:
            await channel.delete(reason=reason)
            print(f"[TEMPVOICE][DELETE] channel={channel_id} reason={reason}")
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException) as error:
            print(
                f"[TEMPVOICE][DELETE][ERROR] channel={channel_id} "
                f"{type(error).__name__}: {error}"
            )
            return

        self.channels.pop(str(channel_id), None)
        self._save_state()

    async def create_room(
        self,
        *,
        interaction: discord.Interaction,
        member: discord.Member,
        name: str,
        status: str,
        user_limit: int,
    ) -> None:
        if not member.voice or not member.voice.channel:
            await interaction.response.send_message(
                "Спочатку зайди в будь-який голосовий канал, а потім створи свою кімнату.",
                ephemeral=True,
            )
            return

        category = self._get_category(member.guild)
        if category is None:
            await interaction.response.send_message(
                "Категорія тимчасових голосових ще не налаштована. "
                "Адміністратор має виконати `/voice setup`.",
                ephemeral=True,
            )
            return

        async with self._lock:
            existing = self._find_owned_channel(member.guild, member.id)
            if existing is not None:
                await interaction.response.send_message(
                    f"У тебе вже є тимчасова кімната: {existing.mention}",
                    ephemeral=True,
                )
                return

            # Копіюємо права категорії: ролі та боти отримують ті самі
            # permission overwrites, що й в інших голосових цієї категорії.
            overwrites = dict(category.overwrites)

            # Автор отримує право зайти у власну кімнату та керувати нею.
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                stream=True,
                use_voice_activation=True,
                move_members=True,
                mute_members=True,
                deafen_members=True,
                manage_channels=True,
            )

            try:
                channel = await member.guild.create_voice_channel(
                    name=name[:100],
                    category=category,
                    overwrites=overwrites,
                    user_limit=user_limit,
                    reason=f"Temporary voice created by {member} ({member.id})",
                )
            except (discord.Forbidden, discord.HTTPException) as error:
                print(
                    f"[TEMPVOICE][CREATE][ERROR] user={member.id} "
                    f"{type(error).__name__}: {error}"
                )
                await interaction.response.send_message(
                    "Не вдалося створити голосову кімнату. Перевір права бота.",
                    ephemeral=True,
                )
                return

            self.channels[str(channel.id)] = member.id
            self._save_state()

            status_ok = True
            if status:
                status_ok = await self._set_voice_status(channel, status)

            try:
                await member.move_to(channel, reason="Move owner to temporary voice room")
            except (discord.Forbidden, discord.HTTPException) as error:
                print(
                    f"[TEMPVOICE][MOVE][ERROR] user={member.id} channel={channel.id} "
                    f"{type(error).__name__}: {error}"
                )
                await self._delete_temp_channel(
                    channel,
                    reason="Could not move temporary voice owner",
                )
                await interaction.response.send_message(
                    "Канал створився, але бот не зміг перенести тебе в нього, "
                    "тому кімнату видалено.",
                    ephemeral=True,
                )
                return

        limit_text = "без ліміту" if user_limit == 0 else str(user_limit)
        status_text = status if status else "без статусу"
        warning = ""

        if status and not status_ok:
            warning = (
                "\n\nСтатус не встановився. Боту потрібні права "
                "`Set Voice Channel Status` і `Manage Channels`."
            )

        await interaction.response.send_message(
            f"Створено {channel.mention}\n"
            f"Статус: **{status_text}**\n"
            f"Ліміт: **{limit_text}**"
            f"{warning}",
            ephemeral=True,
        )

    async def _require_owner_channel(
        self,
        interaction: discord.Interaction,
    ) -> Optional[discord.VoiceChannel]:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Цю команду можна використовувати тільки на сервері.",
                ephemeral=True,
            )
            return None

        member = interaction.user
        if not member.voice or not isinstance(member.voice.channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "Ти маєш бути у своїй тимчасовій голосовій кімнаті.",
                ephemeral=True,
            )
            return None

        channel = member.voice.channel
        if self._owner_id_for(channel.id) != member.id:
            await interaction.response.send_message(
                "Цією кімнатою може керувати тільки її автор.",
                ephemeral=True,
            )
            return None

        return channel

    @voice.command(name="create", description="Створити свою тимчасову голосову кімнату")
    async def voice_create(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Цю команду можна використовувати тільки на сервері.",
                ephemeral=True,
            )
            return

        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "Спочатку зайди в будь-який голосовий канал.",
                ephemeral=True,
            )
            return

        existing = self._find_owned_channel(interaction.guild, interaction.user.id)
        if existing is not None:
            await interaction.response.send_message(
                f"У тебе вже є тимчасова кімната: {existing.mention}",
                ephemeral=True,
            )
            return

        if self._get_category(interaction.guild) is None:
            await interaction.response.send_message(
                "Категорія тимчасових голосових ще не налаштована.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(CreateVoiceModal(self, interaction.user))

    @voice.command(name="name", description="Змінити назву своєї кімнати")
    @app_commands.describe(name="Нова назва")
    async def voice_name(self, interaction: discord.Interaction, name: str) -> None:
        channel = await self._require_owner_channel(interaction)
        if channel is None:
            return

        name = name.strip()
        if not name:
            await interaction.response.send_message("Назва не може бути порожньою.", ephemeral=True)
            return

        try:
            await channel.edit(
                name=name[:100],
                reason=f"Temporary voice renamed by {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не вдалося змінити назву.", ephemeral=True)
            return

        await interaction.response.send_message(
            f"Назву змінено на **{name[:100]}**.",
            ephemeral=True,
        )

    @voice.command(name="status", description="Змінити статус своєї кімнати")
    @app_commands.describe(status="Текст статусу. Вкажи '-' щоб прибрати статус")
    async def voice_status(self, interaction: discord.Interaction, status: str) -> None:
        channel = await self._require_owner_channel(interaction)
        if channel is None:
            return

        status = status.strip()
        if status == "-":
            status = ""

        if len(status) > STATUS_MAX_LENGTH:
            await interaction.response.send_message(
                f"Статус може містити максимум {STATUS_MAX_LENGTH} символів.",
                ephemeral=True,
            )
            return

        ok = await self._set_voice_status(channel, status)
        if not ok:
            await interaction.response.send_message(
                "Не вдалося змінити статус. Перевір права бота "
                "`Set Voice Channel Status` і `Manage Channels`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Статус прибрано." if not status else f"Статус змінено на: **{status}**",
            ephemeral=True,
        )

    @voice.command(name="limit", description="Змінити кількість місць у своїй кімнаті")
    @app_commands.describe(limit="0 = без ліміту, або число 1-99")
    async def voice_limit(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 0, 99],
    ) -> None:
        channel = await self._require_owner_channel(interaction)
        if channel is None:
            return

        try:
            await channel.edit(
                user_limit=limit,
                reason=f"Temporary voice limit changed by {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message("Не вдалося змінити ліміт.", ephemeral=True)
            return

        text_limit = "без ліміту" if limit == 0 else str(limit)
        await interaction.response.send_message(
            f"Новий ліміт: **{text_limit}**.",
            ephemeral=True,
        )

    @voice.command(name="delete", description="Видалити свою кімнату зараз")
    async def voice_delete(self, interaction: discord.Interaction) -> None:
        channel = await self._require_owner_channel(interaction)
        if channel is None:
            return

        await interaction.response.defer(ephemeral=True)
        await self._delete_temp_channel(
            channel,
            reason=f"Temporary voice deleted by owner {interaction.user}",
        )
        await interaction.followup.send("Кімнату видалено.", ephemeral=True)

    @voice.command(name="setup", description="Налаштувати категорію тимчасових голосових")
    @app_commands.describe(category="Категорія, де створювати тимчасові кімнати")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def voice_setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
    ) -> None:
        self._state["category_id"] = category.id
        self._save_state()

        await interaction.response.send_message(
            f"Категорію для тимчасових голосових встановлено: **{category.name}**.",
            ephemeral=True,
        )

    @voice_setup.error
    async def voice_setup_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Цю команду може використовувати тільки адміністрація.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Цю команду може використовувати тільки адміністрація.",
                    ephemeral=True,
                )
            return
        raise error

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        changed = False

        for guild in self.bot.guilds:
            for channel_id, owner_id in list(self.channels.items()):
                try:
                    channel = guild.get_channel(int(channel_id))
                except (TypeError, ValueError):
                    channel = None

                if channel is None or not isinstance(channel, discord.VoiceChannel):
                    self.channels.pop(channel_id, None)
                    changed = True
                    continue

                owner = guild.get_member(int(owner_id))
                owner_is_inside = (
                    owner is not None
                    and owner.voice is not None
                    and owner.voice.channel is not None
                    and owner.voice.channel.id == channel.id
                )

                if not owner_is_inside:
                    await self._delete_temp_channel(
                        channel,
                        reason="Temporary voice owner is not in channel after restart",
                    )
                    changed = True

        if changed:
            self._save_state()

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if before.channel == after.channel:
            return

        before_channel = before.channel
        if not isinstance(before_channel, discord.VoiceChannel):
            return

        if not self._is_temp_channel(before_channel):
            return

        owner_id = self._owner_id_for(before_channel.id)

        # Автор вийшов або перейшов в інший voice — його кімната зникає,
        # навіть якщо всередині ще залишилися гості.
        if owner_id == member.id:
            await self._delete_temp_channel(
                before_channel,
                reason=f"Temporary voice owner left ({member.id})",
            )
            return

        # Страховка: порожня тимчасова кімната також видаляється.
        if len(before_channel.members) == 0:
            await self._delete_temp_channel(
                before_channel,
                reason="Temporary voice became empty",
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TempVoiceCog(bot))
