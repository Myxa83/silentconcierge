from __future__ import annotations


async def setup(bot):
    # Завантажується останнім серед guild_league_* і гарантує, що головна
    # панель завжди малюється з актуального JSON, а не зі старого стану в RAM.
    from cogs import guild_league_cog as league

    if getattr(league, "_refresh_guard_installed", False):
        return
    league._refresh_guard_installed = True

    cog = bot.get_cog("GuildLeagueCog")
    if cog is None:
        print("[GUILD_LEAGUE][REFRESH] GuildLeagueCog not found")
        return

    original_refresh = league.GuildLeagueCog.refresh

    async def refresh_from_saved_state(self):
        # Усі зміни учасників/заявок/часу спочатку зберігаються в JSON.
        # Перед edit головного повідомлення перечитуємо цей стан, щоб панель
        # не залишалась на старому знімку після прийняття заявки.
        self.reload_from_json()
        await original_refresh(self)

    league.GuildLeagueCog.refresh = refresh_from_saved_state

    # Одразу виправляємо вже існуючу панель після деплою.
    try:
        await cog.refresh()
    except Exception as exc:
        print(
            f"[GUILD_LEAGUE][REFRESH] {type(exc).__name__}: {exc}"
        )

    print("[GUILD_LEAGUE] refresh guard enabled: panel reloads JSON before edit")
