import discord
from discord import app_commands
from discord.ext import commands

import io
import json
from datetime import datetime, timezone


class ServerAuditCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def serialize_permissions(self, permissions: discord.Permissions):
        return [
            name
            for name, enabled in permissions
            if enabled
        ]

    def serialize_overwrite(self, overwrite: discord.PermissionOverwrite):
        allow, deny = overwrite.pair()

        return {
            "allow": [
                name
                for name, enabled in allow
                if enabled
            ],
            "deny": [
                name
                for name, enabled in deny
                if enabled
            ]
        }

    def serialize_target(self, target):
        if isinstance(target, discord.Role):
            target_type = "role"
            name = target.name

        elif isinstance(target, discord.Member):
            target_type = "member"
            name = str(target)

        else:
            target_type = type(target).__name__
            name = str(target)

        return {
            "type": target_type,
            "id": target.id,
            "name": name
        }

    def serialize_channel(self, channel):
        data = {
            "id": channel.id,
            "name": channel.name,
            "type": str(channel.type),
            "position": channel.position,

            "category": (
                {
                    "id": channel.category.id,
                    "name": channel.category.name
                }
                if getattr(channel, "category", None)
                else None
            ),

            "permissions_synced": (
                channel.permissions_synced
                if hasattr(channel, "permissions_synced")
                else None
            ),

            "overwrites": []
        }

        if hasattr(channel, "overwrites"):
            for target, overwrite in channel.overwrites.items():

                entry = self.serialize_target(target)
                entry.update(self.serialize_overwrite(overwrite))

                data["overwrites"].append(entry)

        # Додаткові дані залежно від типу каналу

        if isinstance(channel, discord.TextChannel):
            data.update({
                "topic": channel.topic,
                "nsfw": channel.nsfw,
                "slowmode_delay": channel.slowmode_delay,
                "default_auto_archive_duration":
                    channel.default_auto_archive_duration
            })

        elif isinstance(channel, discord.VoiceChannel):
            data.update({
                "bitrate": channel.bitrate,
                "user_limit": channel.user_limit
            })

        elif isinstance(channel, discord.ForumChannel):
            data.update({
                "topic": channel.topic,
                "nsfw": channel.nsfw
            })

        return data

    @app_commands.command(
        name="server_audit",
        description="Export server structure for audit"
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    async def server_audit(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.defer(
            ephemeral=True
        )

        guild = interaction.guild

        if guild is None:
            await interaction.followup.send(
                "Команда працює тільки на сервері.",
                ephemeral=True
            )
            return

        audit = {
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),

            "guild": {
                "id": guild.id,
                "name": guild.name,
                "owner_id": guild.owner_id,

                "member_count": guild.member_count,

                "verification_level":
                    str(guild.verification_level),

                "default_notifications":
                    str(guild.default_notifications),

                "explicit_content_filter":
                    str(guild.explicit_content_filter),

                "mfa_level":
                    guild.mfa_level,

                "premium_tier":
                    guild.premium_tier,

                "premium_subscription_count":
                    guild.premium_subscription_count
            },

            "statistics": {
                "roles": len(guild.roles),
                "categories": len(guild.categories),
                "text_channels": len(guild.text_channels),
                "voice_channels": len(guild.voice_channels),
                "forums": len(guild.forums),
                "members_cached": len(guild.members),
                "bots": sum(
                    1 for member in guild.members
                    if member.bot
                )
            },

            "roles": [],

            "categories": [],

            "channels": [],

            "bots": []
        }

        # --------------------------
        # ROLES
        # --------------------------

        for role in reversed(guild.roles):

            member_count = sum(
                1
                for member in guild.members
                if role in member.roles
            )

            audit["roles"].append({
                "id": role.id,
                "name": role.name,

                "position": role.position,

                "color": str(role.color),

                "hoist": role.hoist,
                "mentionable": role.mentionable,
                "managed": role.managed,

                "is_default": role.is_default(),

                "member_count": member_count,

                "permissions":
                    self.serialize_permissions(
                        role.permissions
                    )
            })

        # --------------------------
        # CATEGORIES
        # --------------------------

        for category in guild.categories:

            category_data = {
                "id": category.id,
                "name": category.name,
                "position": category.position,

                "overwrites": []
            }

            for target, overwrite in category.overwrites.items():

                entry = self.serialize_target(target)
                entry.update(
                    self.serialize_overwrite(overwrite)
                )

                category_data["overwrites"].append(entry)

            audit["categories"].append(
                category_data
            )

        # --------------------------
        # CHANNELS
        # --------------------------

        for channel in guild.channels:

            if isinstance(
                channel,
                discord.CategoryChannel
            ):
                continue

            audit["channels"].append(
                self.serialize_channel(channel)
            )

        # --------------------------
        # BOTS
        # --------------------------

        for member in guild.members:

            if not member.bot:
                continue

            audit["bots"].append({
                "id": member.id,
                "name": str(member),

                "roles": [
                    {
                        "id": role.id,
                        "name": role.name
                    }
                    for role in reversed(member.roles)
                    if not role.is_default()
                ]
            })

        # --------------------------
        # JSON FILE
        # --------------------------

        json_text = json.dumps(
            audit,
            indent=2,
            ensure_ascii=False
        )

        file_buffer = io.BytesIO(
            json_text.encode("utf-8")
        )

        filename = (
            f"server_audit_"
            f"{guild.id}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            f".json"
        )

        discord_file = discord.File(
            fp=file_buffer,
            filename=filename
        )

        await interaction.followup.send(
            "Готово. Це лише читання сервера, "
            "нічого не змінено.",
            file=discord_file,
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(
        ServerAuditCog(bot)
    )
