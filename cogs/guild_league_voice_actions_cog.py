from __future__ import annotations

from datetime import datetime

import discord


VOICE_CHANNEL_ID = 1534906417495146587


def _next_party(league):
    """Найближче актуальне паті. Якщо майбутніх немає, беремо щойно почате."""
    now_ts = int(datetime.now(league.TZ).timestamp())
    parties = [
        party
        for party in league_state_packs(league)
        if party.get("start_ts")
    ]
    if not parties:
        return None

    future = [p for p in parties if int(p["start_ts"]) >= now_ts]
    if future:
        return min(future, key=lambda p: int(p["start_ts"]))

    # Дозволяємо пінг поточного матчу ще 20 хв після його старту.
    recent = [
        p for p in parties
        if 0 <= now_ts - int(p["start_ts"]) <= 20 * 60
    ]
    return max(recent, key=lambda p: int(p["start_ts"])) if recent else None


def league_state_packs(league):
    cog = getattr(league, "_voice_actions_cog_instance", None)
    if cog is None:
        return []
    return cog.state.get("packs", [])


async def setup(bot):
    # Завантажується після guild_league_cog.py і додає дві дії до того ж PL dropdown.
    from cogs import guild_league_cog as league

    if getattr(league, "_voice_actions_installed", False):
        return
    league._voice_actions_installed = True

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][VOICE] GuildLeagueCog not found")
        return
    league._voice_actions_cog_instance = cog

    class VoicePLMenu(discord.ui.Select):
        def __init__(self, league_cog):
            actions = [
                ("🔄", "Оновити повідомлення", "refresh"),
                ("💤", "Пінг відсутніх у голосовому", "ping_missing_voice"),
                ("🔔", "Пінг усіх наступного паті", "ping_all_next"),
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
                    discord.SelectOption(emoji=emoji, label=label, value=value)
                    for emoji, label, value in actions
                ],
            )
            self.cog = league_cog

        async def callback(self, interaction: discord.Interaction):
            await self.cog.pl_action(interaction, self.values[0])

    # MainView шукає PLMenu у globals під час побудови, тому наступне оновлення
    # панелі одразу отримає нові пункти меню.
    league.PLMenu = VoicePLMenu

    original_pl_action = league.GuildLeagueCog.pl_action

    async def voice_pl_action(self, interaction: discord.Interaction, action: str):
        if action not in ("ping_missing_voice", "ping_all_next"):
            return await original_pl_action(self, interaction, action)

        if not await self.ok_channel(interaction):
            return
        if not self.is_pl(interaction):
            await interaction.response.send_message(
                "Це меню доступне тільки PL.",
                ephemeral=True,
            )
            return

        party = _next_party(league)
        if not party:
            await interaction.response.send_message(
                "Немає найближчого актуального паті.",
                ephemeral=True,
            )
            return

        members = party.get("members", [])
        if not members:
            await interaction.response.send_message(
                f"У **Паті {party['number']}** ще немає учасників.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(VOICE_CHANNEL_ID)
        if channel is None:
            try:
                channel = await interaction.guild.fetch_channel(VOICE_CHANNEL_ID)
            except Exception:
                channel = None

        if action == "ping_missing_voice":
            if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                await interaction.response.send_message(
                    f"Не можу прочитати голосовий канал <#{VOICE_CHANNEL_ID}>.",
                    ephemeral=True,
                )
                return

            present_ids = {member.id for member in channel.members}
            missing = [
                entry
                for entry in members
                if int(entry.get("user_id", 0)) not in present_ids
            ]

            if not missing:
                await interaction.response.send_message(
                    f"Усі учасники **Паті {party['number']}** вже в <#{VOICE_CHANNEL_ID}>.",
                    ephemeral=True,
                )
                return

            mentions = " ".join(f"<@{entry['user_id']}>" for entry in missing)
            await interaction.response.send_message(
                (
                    f"💤 **Паті {party['number']} • {league.discord_date_time(party['start_ts'])}**\n"
                    f"Ще не в <#{VOICE_CHANNEL_ID}>: {mentions}"
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
            return

        mentions = " ".join(f"<@{entry['user_id']}>" for entry in members)
        await interaction.response.send_message(
            (
                f"🔔 **Паті {party['number']} • {league.discord_date_time(party['start_ts'])}**\n"
                f"Учасники: {mentions}\n"
                f"Голосовий: <#{VOICE_CHANNEL_ID}>"
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )

    league.GuildLeagueCog.pl_action = voice_pl_action

    # Перемальовуємо існуючу панель, щоб нове меню з'явилося одразу після деплою.
    try:
        await cog.refresh()
    except Exception as exc:
        print(f"[GUILD_LEAGUE][VOICE][REFRESH] {type(exc).__name__}: {exc}")

    print(
        "[GUILD_LEAGUE] voice actions enabled: "
        f"missing/all for channel {VOICE_CHANNEL_ID}"
    )
