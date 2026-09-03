from __future__ import annotations

import re

import discord
from discord.ext import commands


DATE_BUTTON_RE = re.compile(
    r"^gl_date_(?P<date>\d{8})_(?P<action>role_(?:tank|dps|shai)|signup|cant|help)$"
)


class GuildLeagueDateButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=DATE_BUTTON_RE,
):
    """Catch dated Guild League buttons by custom_id after any restart.

    Unlike message-bound persistent views, DynamicItem does not need the old
    message ID or the old in-memory View instance. If the button still exists
    in Discord and its custom_id matches gl_date_YYYYMMDD_..., this callback is
    recreated on demand.
    """

    def __init__(
        self,
        item: discord.ui.Button,
        day_iso: str,
        action: str,
    ):
        super().__init__(item)
        self.day_iso = day_iso
        self.action = action

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
        /,
    ) -> "GuildLeagueDateButton":
        compact = match.group("date")
        day_iso = f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
        return cls(item, day_iso, match.group("action"))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("GuildLeagueDatedPosts")
        if cog is None:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Модуль Ліги ще завантажується. Спробуй ще раз за кілька секунд.",
                    ephemeral=True,
                )
            return

        try:
            if self.action.startswith("role_"):
                role_key = self.action.removeprefix("role_")
                await cog.set_date_role(interaction, self.day_iso, role_key)
                return

            if self.action == "signup":
                await cog.begin_date_signup(interaction, self.day_iso)
                return

            if self.action == "cant":
                await cog.leave_date(interaction, self.day_iso)
                return

            if self.action == "help":
                await cog.help_date(interaction, self.day_iso)
                return

        except discord.InteractionResponded:
            return
        except Exception as exc:
            print(
                f"[GUILD_LEAGUE][DYNAMIC_BUTTON] {self.day_iso} {self.action}: "
                f"{type(exc).__name__}: {exc}"
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Помилка обробки кнопки. Спробуй ще раз.",
                    ephemeral=True,
                )
            else:
                try:
                    await interaction.followup.send(
                        "Помилка обробки кнопки. Спробуй ще раз.",
                        ephemeral=True,
                    )
                except Exception:
                    pass


class GuildLeagueDynamicButtonsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def cog_unload(self):
        try:
            self.bot.remove_dynamic_items(GuildLeagueDateButton)
        except Exception:
            pass


async def setup(bot):
    # DynamicItem is the durable fallback. It listens by custom_id pattern, so
    # old dated posts remain clickable even after deploys/restarts and even if
    # their original View was not restored from message history.
    bot.add_dynamic_items(GuildLeagueDateButton)
    await bot.add_cog(GuildLeagueDynamicButtonsCog(bot))
    print("[GUILD_LEAGUE] dynamic dated buttons registered")
