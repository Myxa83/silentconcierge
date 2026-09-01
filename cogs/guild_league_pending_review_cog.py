from __future__ import annotations

import discord


async def setup(bot):
    from cogs import guild_league_cog as league

    if getattr(league, "_pending_review_installed", False):
        return
    league._pending_review_installed = True

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][PENDING] GuildLeagueCog not found")
        return

    def pending_text(party):
        pending = party.get("pending", [])
        lines = [
            f"{league.role_text(x.get('role'))} <@{x['user_id']}>"
            for x in pending
        ]
        body = "\n".join(lines) if lines else "Заявок немає."
        return (
            f"**Паті {party['number']} • заявки**\n"
            f"{league.discord_date_time(party['start_ts'])}\n\n"
            f"{body}"
        )

    class ApplicationReviewView(discord.ui.View):
        def __init__(self, league_cog, party_number: int):
            super().__init__(timeout=180)
            self.cog = league_cog
            self.party_number = party_number
            self.selected_user_id = None

            party = league.get_party(self.cog.state, party_number)
            pending = party.get("pending", []) if party else []

            options = []
            for entry in pending[:25]:
                member = None
                guild = self.cog.bot.get_guild(league.GUILD_ID)
                if guild:
                    member = guild.get_member(int(entry["user_id"]))
                display_name = member.display_name if member else str(entry["user_id"])
                options.append(
                    discord.SelectOption(
                        label=(
                            f"{display_name} • "
                            f"{league.role_text(entry.get('role'))}"
                        )[:100],
                        value=str(entry["user_id"]),
                    )
                )

            if options:
                select = discord.ui.Select(
                    placeholder="Оберіть заявку",
                    options=options,
                    min_values=1,
                    max_values=1,
                )

                async def selected(interaction: discord.Interaction):
                    if not self.cog.is_pl(interaction):
                        await interaction.response.send_message(
                            "Це меню доступне тільки PL.",
                            ephemeral=True,
                        )
                        return
                    self.selected_user_id = select.values[0]
                    party_now = league.get_party(
                        self.cog.state,
                        self.party_number,
                    )
                    if not party_now:
                        await interaction.response.edit_message(
                            content="Паті вже немає.",
                            view=None,
                        )
                        return
                    await interaction.response.edit_message(
                        content=(
                            pending_text(party_now)
                            + f"\n\nОбрано: <@{self.selected_user_id}>"
                        ),
                        view=self,
                    )

                select.callback = selected
                self.add_item(select)

        async def process(
            self,
            interaction: discord.Interaction,
            approve: bool,
        ):
            if not self.cog.is_pl(interaction):
                await interaction.response.send_message(
                    "Це меню доступне тільки PL.",
                    ephemeral=True,
                )
                return

            if not self.selected_user_id:
                await interaction.response.send_message(
                    "Спочатку оберіть заявку зі списку.",
                    ephemeral=True,
                )
                return

            party = league.get_party(self.cog.state, self.party_number)
            if not party:
                await interaction.response.edit_message(
                    content="Паті вже немає.",
                    view=None,
                )
                return

            uid = str(self.selected_user_id)
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
                    content=(
                        pending_text(party)
                        + "\n\nЦієї заявки вже немає."
                    ),
                    view=(
                        ApplicationReviewView(self.cog, self.party_number)
                        if party.get("pending")
                        else None
                    ),
                )
                return

            party["pending"].remove(entry)

            if approve:
                if league.member_count(party) < league.MAX_MEMBERS:
                    party.setdefault("members", []).append(entry)
                    result = f"✅ <@{uid}> прийнято в основний склад."
                else:
                    party.setdefault("waitlist", []).append(entry)
                    result = f"✅ <@{uid}> додано до листа очікування."
            else:
                result = f"❌ Заявку <@{uid}> відхилено."

            self.cog.save()
            await self.cog.refresh()

            if party.get("pending"):
                await interaction.response.edit_message(
                    content=(
                        pending_text(party)
                        + f"\n\n{result}\nОберіть наступну заявку."
                    ),
                    view=ApplicationReviewView(
                        self.cog,
                        self.party_number,
                    ),
                )
            else:
                await interaction.response.edit_message(
                    content=(
                        f"{result}\n\n"
                        f"**Паті {self.party_number}: заявок більше немає.**"
                    ),
                    view=None,
                )

        @discord.ui.button(
            label="Прийняти",
            emoji="✅",
            style=discord.ButtonStyle.success,
            row=1,
        )
        async def approve_button(
            self,
            interaction: discord.Interaction,
            _button: discord.ui.Button,
        ):
            await self.process(interaction, True)

        @discord.ui.button(
            label="Відхилити",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            row=1,
        )
        async def reject_button(
            self,
            interaction: discord.Interaction,
            _button: discord.ui.Button,
        ):
            await self.process(interaction, False)

    original_pl_party_selected = league.GuildLeagueCog.pl_party_selected

    async def pl_party_selected(self, interaction, number, action):
        if action != "pending":
            return await original_pl_party_selected(
                self,
                interaction,
                number,
                action,
            )

        if not self.is_pl(interaction):
            await interaction.response.send_message(
                "Це меню доступне тільки PL.",
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

        if not party.get("pending"):
            await interaction.response.send_message(
                "Заявок немає.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            pending_text(party)
            + "\n\nОберіть людину та натисніть **Прийняти** або **Відхилити**.",
            view=ApplicationReviewView(self, number),
            ephemeral=True,
        )

    league.GuildLeagueCog.pl_party_selected = pl_party_selected

    print(
        "[GUILD_LEAGUE] pending review enabled: "
        "single live application window"
    )
