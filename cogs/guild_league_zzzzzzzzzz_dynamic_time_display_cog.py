from __future__ import annotations

import discord


async def setup(bot):
    """Показує час у датованих панелях через Discord timestamps.

    У публічному розкладі час більше не зашитий як CET/CEST HH:MM.
    Discord сам показує кожному користувачу його локальний час.
    """
    from cogs import guild_league_zzzzzzzzz_dated_posts_cog as dated

    cog = bot.get_cog("GuildLeagueDatedPosts")
    if cog is None:
        print("[GUILD_LEAGUE][DYNAMIC_TIME] GuildLeagueDatedPosts not found")
        return

    def build_embeds_dynamic(self, day_iso: str):
        event = self.event(day_iso)
        if not event:
            return []

        slots = event.get("slots", [])
        pl = event.get("pl_user_id")

        first_ts = None
        if slots:
            try:
                first_ts = int(slots[0].get("start_ts"))
            except (TypeError, ValueError):
                first_ts = None

        header = discord.Embed(
            title="Ліга гільдій",
            description=(
                "Обери **Tank / DPS / Shai**, натисни **Записатися** і "
                "вибери **один або кілька часів**, коли можеш грати.\n"
                "Час нижче Discord автоматично показує у твоєму часовому поясі."
            ),
            color=self.league.COLOR,
        )
        header.add_field(
            name="Дата",
            value=(f"<t:{first_ts}:D>" if first_ts else day_iso),
            inline=True,
        )
        header.add_field(
            name="PL",
            value=f"<@{pl}>" if pl else "не визначений",
            inline=True,
        )
        header.add_field(
            name="Паті",
            value="максимум 10 + лист очікування",
            inline=True,
        )

        embeds = [header]
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
                    ts = int(slot["start_ts"])

                    lines = [
                        f"**<t:{ts}:t> ({len(members)}/10{extra})**"
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

    dated.GuildLeagueDatedPosts.build_embeds = build_embeds_dynamic

    # Одразу перемальовуємо вже опубліковані майбутні реєстрації.
    for day_iso, event in list(cog.data.get("events", {}).items()):
        if not event.get("message_id"):
            continue
        try:
            await cog.refresh_date(day_iso)
        except Exception as exc:
            print(
                f"[GUILD_LEAGUE][DYNAMIC_TIME][REFRESH] {day_iso} "
                f"{type(exc).__name__}: {exc}"
            )

    print("[GUILD_LEAGUE] dated panels now use Discord-local dynamic time")
