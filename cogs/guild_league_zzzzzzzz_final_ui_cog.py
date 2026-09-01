from __future__ import annotations

import discord


async def setup(bot):
    """Фінальна панель Ліги: роль -> Записатися -> вибір часу.

    Використовує нові custom_id і динамічні callbacks, щоб рання persistent
    view з базового когу не перехоплювала натискання старою логікою.
    """
    from cogs import guild_league_cog as league

    if getattr(league, "_final_ui_installed", False):
        return
    league._final_ui_installed = True

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][FINAL_UI] GuildLeagueCog not found")
        return

    class FinalMainView(discord.ui.View):
        def __init__(self, league_cog):
            super().__init__(timeout=None)
            self.cog = league_cog

            for key, style in (
                ("tank", discord.ButtonStyle.primary),
                ("dps", discord.ButtonStyle.danger),
                ("shai", discord.ButtonStyle.success),
            ):
                button = discord.ui.Button(
                    label=league.ROLES[key][1],
                    emoji=league.ROLES[key][0],
                    style=style,
                    custom_id=f"guild_league_v2_role_{key}",
                    row=0,
                )

                async def choose_role(interaction, selected=key):
                    # Викликаємо метод у момент кліку, а не зберігаємо стару
                    # bound-функцію під час старту бота.
                    await self.cog.set_role(interaction, selected)

                button.callback = choose_role
                self.add_item(button)

            signup = discord.ui.Button(
                label="Записатися",
                emoji="✅",
                style=discord.ButtonStyle.success,
                custom_id="guild_league_v2_signup",
                row=1,
            )
            cant = discord.ui.Button(
                label="Не можу",
                emoji="✖️",
                style=discord.ButtonStyle.danger,
                custom_id="guild_league_v2_cant",
                row=1,
            )
            help_button = discord.ui.Button(
                label="Допомога",
                emoji="❔",
                style=discord.ButtonStyle.secondary,
                custom_id="guild_league_v2_help",
                row=1,
            )

            async def signup_now(interaction):
                # Тут уже встановлений останній begin_signup:
                # відкриває саме список часу з мультивибором.
                await self.cog.begin_signup(interaction)

            async def cant_now(interaction):
                await self.cog.leave(interaction)

            async def help_now(interaction):
                await self.cog.help(interaction)

            signup.callback = signup_now
            cant.callback = cant_now
            help_button.callback = help_now

            self.add_item(signup)
            self.add_item(cant)
            self.add_item(help_button)
            self.add_item(league.PLMenu(league_cog))

    # Усі наступні refresh() та /guild_league_panel використовують фінальну view.
    league.MainView = FinalMainView

    # Реєструємо саме фінальні custom_id як persistent callbacks.
    bot.add_view(FinalMainView(cog))

    # Перемальовуємо вже існуючу панель, щоб на ній були нові custom_id.
    try:
        await cog.refresh()
    except Exception as exc:
        print(
            f"[GUILD_LEAGUE][FINAL_UI][REFRESH] "
            f"{type(exc).__name__}: {exc}"
        )

    print(
        "[GUILD_LEAGUE] final UI enabled: role -> signup -> multi-time selector"
    )
