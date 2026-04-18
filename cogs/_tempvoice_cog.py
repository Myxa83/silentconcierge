# cogs/tempvoice_cog.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands


class CreateVoiceModal(discord.ui.Modal, title="Створення голосового каналу"):
    channel_name = discord.ui.TextInput(
        label="Назва каналу",
        placeholder="Наприклад: Моя кімната",
        max_length=100,
        required=False,
    )

    user_limit = discord.ui.TextInput(
        label="Ліміт користувачів (0 = без ліміту)",
        placeholder="Наприклад: 5",
        max_length=2,
        required=False,
        default="0",
    )

    status = discord.ui.TextInput(
        label="Статус (open / lock)",
        placeholder="open або lock",
        max_length=5,
        required=False,
        default="open",
    )

    def __init__(self, cog: "TempVoiceCog", member_id: int, guild_id: int) -> None:
        super().__init__()
        self.cog = cog
        self.member_id = member_id
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        guild = self.cog.bot.get_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message(
                "Не вдалося знайти сервер.",
                ephemeral=True,
            )
            return

        member = guild.get_member(self.member_id)
        if member is None:
            await interaction.response.send_message(
                "Не вдалося знайти користувача на сервері.",
                ephemeral=True,
            )
            return

        raw_name = self.channel_name.value.strip() if self.channel_name.value else ""
        raw_limit = self.user_limit.value.strip() if self.user_limit.value else "0"
        raw_status = self.status.value.strip().lower() if self.status.value else "open"

        if raw_status not in {"open", "lock"}:
            await interaction.response.send_message(
                "Статус має бути тільки `open` або `lock`.",
                ephemeral=True,
            )
            return

        try:
            limit = int(raw_limit)
        except ValueError:
            await interaction.response.send_message(
                "Ліміт має бути числом від 0 до 99.",
                ephemeral=True,
            )
            return

        if limit < 0 or limit > 99:
            await interaction.response.send_message(
                "Ліміт має бути в межах від 0 до 99.",
                ephemeral=True,
            )
            return

        await self.cog.create_channel_from_modal(
            interaction=interaction,
            member=member,
            name=raw_name or None,
            limit=limit,
            status=raw_status,
        )


class CreateVoiceView(discord.ui.View):
    def __init__(self, cog: "TempVoiceCog", member_id: int, guild_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.member_id = member_id
        self.guild_id = guild_id

    @discord.ui.button(label="Створити канал", style=discord.ButtonStyle.green, emoji="🎤")
    async def create_channel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.member_id:
            await interaction.response.send_message(
                "Ця кнопка не для тебе.",
                ephemeral=True,
            )
            return

        guild = self.cog.bot.get_guild(self.guild_id)
        if guild is None:
            await interaction.response.send_message(
                "Не вдалося знайти сервер.",
                ephemeral=True,
            )
            return

        member = guild.get_member(self.member_id)
        if member is None:
            await interaction.response.send_message(
                "Не вдалося знайти тебе на сервері.",
                ephemeral=True,
            )
            return

        if not member.voice or not member.voice.channel:
            await interaction.response.send_message(
                "Спочатку зайди в канал-створювач.",
                ephemeral=True,
            )
            return

        if member.voice.channel.id != self.cog.create_channel_id:
            await interaction.response.send_message(
                "Ти маєш бути саме в каналі-створювачі.",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            CreateVoiceModal(
                cog=self.cog,
                member_id=self.member_id,
                guild_id=self.guild_id,
            )
        )


class TempVoiceCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

        # =========================
        # ЗАМІНИ ЦІ 2 ID НА СВОЇ
        # =========================

        # ID голосового каналу-створювача
        self.create_channel_id: int = 123456789012345678

        # ID категорії, де створювати тимчасові voice-канали
        self.temp_category_id: int = 123456789012345678

        # ID текстового каналу, куди бот пише кнопку створення
        self.panel_text_channel_id: int = 1324007760001630239

        # 0 = без ліміту
        self.default_user_limit: int = 0

        # Шаблон стандартної назви каналу
        self.channel_name_template: str = "🎤 {display_name}"

        # channel_id -> owner_id
        self.temp_channel_owners: dict[int, int] = {}

        # user_id, щоб не спамити повідомленням багато разів поспіль
        self.pending_panel_message: set[int] = set()

        self.voice_group = app_commands.Group(
            name="voice",
            description="Керування тимчасовим голосовим каналом",
        )
        self.voice_group.add_command(self.voice_name)
        self.voice_group.add_command(self.voice_limit)
        self.voice_group.add_command(self.voice_lock)
        self.voice_group.add_command(self.voice_unlock)
        self.voice_group.add_command(self.voice_claim)

    async def cog_load(self) -> None:
        try:
            self.bot.tree.add_command(self.voice_group)
        except app_commands.CommandAlreadyRegistered:
            pass

    async def cog_unload(self) -> None:
        try:
            self.bot.tree.remove_command(self.voice_group.name, type=self.voice_group.type)
        except Exception:
            pass

    def _build_channel_name(self, member: discord.Member) -> str:
        safe_name = member.display_name.strip() or member.name
        return self.channel_name_template.format(display_name=safe_name)

    def _get_category(self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        category = guild.get_channel(self.temp_category_id)
        if isinstance(category, discord.CategoryChannel):
            return category
        return None

    def _get_panel_text_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        channel = guild.get_channel(self.panel_text_channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
        return None

    def _is_temp_voice_channel(self, channel: Optional[discord.abc.GuildChannel]) -> bool:
        if channel is None:
            return False

        if not isinstance(channel, discord.VoiceChannel):
            return False

        if channel.id == self.create_channel_id:
            return False

        if not channel.category:
            return False

        return channel.category.id == self.temp_category_id

    def _get_member_temp_channel(self, member: discord.Member) -> Optional[discord.VoiceChannel]:
        if not member.voice or not member.voice.channel:
            return None

        channel = member.voice.channel
        if not isinstance(channel, discord.VoiceChannel):
            return None

        if not self._is_temp_voice_channel(channel):
            return None

        return channel

    def _is_owner(self, member: discord.Member, channel: discord.VoiceChannel) -> bool:
        owner_id = self.temp_channel_owners.get(channel.id)
        return owner_id == member.id

    async def _delete_channel_if_empty(self, channel: Optional[discord.abc.GuildChannel]) -> None:
        if not self._is_temp_voice_channel(channel):
            return

        assert isinstance(channel, discord.VoiceChannel)

        if len(channel.members) > 0:
            return

        try:
            await channel.delete(reason="Temporary voice channel is empty")
        except (discord.Forbidden, discord.HTTPException):
            return
        finally:
            self.temp_channel_owners.pop(channel.id, None)

    async def _create_temp_channel_for_member(
        self,
        member: discord.Member,
        name: Optional[str] = None,
        limit: Optional[int] = None,
        locked: bool = False,
    ) -> Optional[discord.VoiceChannel]:
        guild = member.guild
        category = self._get_category(guild)
        if category is None:
            return None

        channel_name = name.strip() if name else self._build_channel_name(member)
        final_limit = self.default_user_limit if limit is None else limit

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=not locked,
                speak=True,
                stream=True,
                use_voice_activation=True,
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                stream=True,
                use_voice_activation=True,
                move_members=True,
                manage_channels=True,
                manage_permissions=True,
            ),
        }

        try:
            new_channel = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                user_limit=final_limit,
                reason=f"Temporary voice channel created for {member} ({member.id})",
            )
        except (discord.Forbidden, discord.HTTPException):
            return None

        self.temp_channel_owners[new_channel.id] = member.id
        return new_channel

    async def _lock_channel(self, channel: discord.VoiceChannel) -> bool:
        guild = channel.guild
        overwrite = channel.overwrites_for(guild.default_role)
        overwrite.connect = False

        try:
            await channel.set_permissions(
                guild.default_role,
                overwrite=overwrite,
                reason="Temporary voice channel locked",
            )
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def _unlock_channel(self, channel: discord.VoiceChannel) -> bool:
        guild = channel.guild
        overwrite = channel.overwrites_for(guild.default_role)
        overwrite.connect = True

        try:
            await channel.set_permissions(
                guild.default_role,
                overwrite=overwrite,
                reason="Temporary voice channel unlocked",
            )
            return True
        except (discord.Forbidden, discord.HTTPException):
            return False

    async def _send_creator_panel_message(self, member: discord.Member) -> None:
        if member.id in self.pending_panel_message:
            return

        self.pending_panel_message.add(member.id)

        try:
            channel = self._get_panel_text_channel(member.guild)
            if channel is None:
                return

            embed = discord.Embed(
                title="Створення голосового каналу",
                description=(
                    f"{member.mention}, натисни кнопку нижче, щоб створити свій voice-канал.\n\n"
                    "У формі можна вказати:\n"
                    "- назву\n"
                    "- ліміт\n"
                    "- статус `open` або `lock`"
                ),
                color=0x1F2427,
            )

            await channel.send(
                content=member.mention,
                embed=embed,
                view=CreateVoiceView(
                    cog=self,
                    member_id=member.id,
                    guild_id=member.guild.id,
                ),
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        except (discord.Forbidden, discord.HTTPException):
            pass
        finally:
            self.pending_panel_message.discard(member.id)

    async def create_channel_from_modal(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        name: Optional[str],
        limit: int,
        status: str,
    ) -> None:
        if not member.voice or not member.voice.channel:
            await interaction.response.send_message(
                "Ти вже не в voice-каналі. Зайди в канал-створювач ще раз.",
                ephemeral=True,
            )
            return

        if member.voice.channel.id != self.create_channel_id:
            await interaction.response.send_message(
                "Ти маєш бути саме в каналі-створювачі.",
                ephemeral=True,
            )
            return

        locked = status == "lock"

        new_channel = await self._create_temp_channel_for_member(
            member=member,
            name=name,
            limit=limit,
            locked=locked,
        )

        if new_channel is None:
            await interaction.response.send_message(
                "Не вдалося створити канал. Перевір права бота, category ID і text channel ID.",
                ephemeral=True,
            )
            return

        try:
            await member.move_to(new_channel, reason="Move member to temp voice channel")
        except (discord.Forbidden, discord.HTTPException):
            try:
                await new_channel.delete(reason="Could not move member into temp voice channel")
            except (discord.Forbidden, discord.HTTPException):
                pass
            finally:
                self.temp_channel_owners.pop(new_channel.id, None)

            await interaction.response.send_message(
                "Канал створився, але не вдалося тебе туди перенести. Канал видалено.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            (
                f"Канал створено: **{new_channel.name}**\n"
                f"Ліміт: **{'без ліміту' if limit == 0 else limit}**\n"
                f"Статус: **{'закритий' if locked else 'відкритий'}**"
            ),
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            category = guild.get_channel(self.temp_category_id)

            if not isinstance(category, discord.CategoryChannel):
                continue

            for channel in category.voice_channels:
                if channel.id == self.create_channel_id:
                    continue

                if len(channel.members) == 0:
                    try:
                        await channel.delete(reason="Cleanup empty temp voice after restart")
                    except (discord.Forbidden, discord.HTTPException):
                        pass

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        if after.channel and after.channel.id == self.create_channel_id:
            await self._send_creator_panel_message(member)
            return

        if before.channel and before.channel != after.channel:
            await self._delete_channel_if_empty(before.channel)

    @app_commands.command(name="name", description="Змінити назву свого тимчасового каналу")
    @app_commands.describe(name="Нова назва каналу")
    async def voice_name(self, interaction: discord.Interaction, name: str) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Це можна використати тільки на сервері.",
                ephemeral=True,
            )
            return

        channel = self._get_member_temp_channel(interaction.user)
        if channel is None:
            await interaction.response.send_message(
                "Ти маєш бути у своєму тимчасовому голосовому каналі.",
                ephemeral=True,
            )
            return

        if not self._is_owner(interaction.user, channel):
            await interaction.response.send_message(
                "Тільки власник каналу може змінювати назву. Якщо був рестарт, використай `/voice claim`.",
                ephemeral=True,
            )
            return

        name = name.strip()
        if not name:
            await interaction.response.send_message(
                "Назва не може бути порожньою.",
                ephemeral=True,
            )
            return

        if len(name) > 100:
            await interaction.response.send_message(
                "Назва занадто довга. Максимум 100 символів.",
                ephemeral=True,
            )
            return

        try:
            await channel.edit(name=name, reason=f"Temp voice renamed by {interaction.user}")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "Не вдалося змінити назву каналу.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Назву каналу змінено на: **{name}**",
            ephemeral=True,
        )

    @app_commands.command(name="limit", description="Змінити ліміт користувачів")
    @app_commands.describe(limit="Вкажи число від 0 до 99. 0 = без ліміту")
    async def voice_limit(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 0, 99],
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Це можна використати тільки на сервері.",
                ephemeral=True,
            )
            return

        channel = self._get_member_temp_channel(interaction.user)
        if channel is None:
            await interaction.response.send_message(
                "Ти маєш бути у своєму тимчасовому голосовому каналі.",
                ephemeral=True,
            )
            return

        if not self._is_owner(interaction.user, channel):
            await interaction.response.send_message(
                "Тільки власник каналу може змінювати ліміт. Якщо був рестарт, використай `/voice claim`.",
                ephemeral=True,
            )
            return

        try:
            await channel.edit(user_limit=limit, reason=f"Temp voice limit changed by {interaction.user}")
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "Не вдалося змінити ліміт каналу.",
                ephemeral=True,
            )
            return

        text = "без ліміту" if limit == 0 else str(limit)
        await interaction.response.send_message(
            f"Новий ліміт каналу: **{text}**",
            ephemeral=True,
        )

    @app_commands.command(name="lock", description="Закрити канал для нових підключень")
    async def voice_lock(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Це можна використати тільки на сервері.",
                ephemeral=True,
            )
            return

        channel = self._get_member_temp_channel(interaction.user)
        if channel is None:
            await interaction.response.send_message(
                "Ти маєш бути у своєму тимчасовому голосовому каналі.",
                ephemeral=True,
            )
            return

        if not self._is_owner(interaction.user, channel):
            await interaction.response.send_message(
                "Тільки власник каналу може змінювати статус. Якщо був рестарт, використай `/voice claim`.",
                ephemeral=True,
            )
            return

        ok = await self._lock_channel(channel)
        if not ok:
            await interaction.response.send_message(
                "Не вдалося закрити канал.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Канал закрито. Нові користувачі не зможуть підключатися.",
            ephemeral=True,
        )

    @app_commands.command(name="unlock", description="Відкрити канал для нових підключень")
    async def voice_unlock(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Це можна використати тільки на сервері.",
                ephemeral=True,
            )
            return

        channel = self._get_member_temp_channel(interaction.user)
        if channel is None:
            await interaction.response.send_message(
                "Ти маєш бути у своєму тимчасовому голосовому каналі.",
                ephemeral=True,
            )
            return

        if not self._is_owner(interaction.user, channel):
            await interaction.response.send_message(
                "Тільки власник каналу може змінювати статус. Якщо був рестарт, використай `/voice claim`.",
                ephemeral=True,
            )
            return

        ok = await self._unlock_channel(channel)
        if not ok:
            await interaction.response.send_message(
                "Не вдалося відкрити канал.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            "Канал відкрито. Тепер інші можуть підключатися.",
            ephemeral=True,
        )

    @app_commands.command(name="claim", description="Забрати собі керування каналом")
    async def voice_claim(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Це можна використати тільки на сервері.",
                ephemeral=True,
            )
            return

        channel = self._get_member_temp_channel(interaction.user)
        if channel is None:
            await interaction.response.send_message(
                "Ти маєш бути у тимчасовому голосовому каналі.",
                ephemeral=True,
            )
            return

        current_owner_id = self.temp_channel_owners.get(channel.id)

        if current_owner_id:
            current_owner = interaction.guild.get_member(current_owner_id)
            if current_owner and current_owner in channel.members and current_owner.id != interaction.user.id:
                await interaction.response.send_message(
                    "У цього каналу вже є власник, і він зараз у каналі.",
                    ephemeral=True,
                )
                return

        try:
            await channel.set_permissions(
                interaction.user,
                view_channel=True,
                connect=True,
                speak=True,
                stream=True,
                use_voice_activation=True,
                move_members=True,
                manage_channels=True,
                manage_permissions=True,
                reason=f"Temp voice claimed by {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "Не вдалося передати канал.",
                ephemeral=True,
            )
            return

        self.temp_channel_owners[channel.id] = interaction.user.id

        await interaction.response.send_message(
            "Тепер ти власник цього тимчасового каналу.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TempVoiceCog(bot))
