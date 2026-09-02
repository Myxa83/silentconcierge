from __future__ import annotations

import asyncio
import re

from discord.ext import commands


DATE_CUSTOM_ID_RE = re.compile(r"^gl_date_(\d{8})_")


def _day_from_message(message) -> str | None:
    for row in getattr(message, "components", []) or []:
        for item in getattr(row, "children", []) or []:
            custom_id = getattr(item, "custom_id", None)
            if not custom_id:
                continue
            match = DATE_CUSTOM_ID_RE.match(str(custom_id))
            if not match:
                continue
            compact = match.group(1)
            return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"
    return None


def _register_saved_views(bot, dated_module, dated_cog) -> int:
    registered = 0
    for day_iso, event in dated_cog.data.get("events", {}).items():
        message_id = event.get("message_id") if isinstance(event, dict) else None
        if not message_id:
            continue
        try:
            bot.add_view(
                dated_module.DatedPanelView(dated_cog, day_iso),
                message_id=int(message_id),
            )
            registered += 1
        except Exception as exc:
            print(
                f"[GUILD_LEAGUE][PERSISTENT][SAVED] {day_iso}: "
                f"{type(exc).__name__}: {exc}"
            )
    return registered


async def _restore_views_from_history(bot, league, dated_module, dated_cog) -> None:
    try:
        await bot.wait_until_ready()
        channel = (
            bot.get_channel(league.CHANNEL_ID)
            or await bot.fetch_channel(league.CHANNEL_ID)
        )

        seen = set()
        restored = 0
        async for message in channel.history(limit=None):
            if bot.user and message.author.id != bot.user.id:
                continue

            day_iso = _day_from_message(message)
            if not day_iso:
                continue

            key = (message.id, day_iso)
            if key in seen:
                continue
            seen.add(key)

            try:
                bot.add_view(
                    dated_module.DatedPanelView(dated_cog, day_iso),
                    message_id=message.id,
                )
                restored += 1
            except Exception as exc:
                print(
                    f"[GUILD_LEAGUE][PERSISTENT][HISTORY] "
                    f"message={message.id} day={day_iso}: "
                    f"{type(exc).__name__}: {exc}"
                )

        print(
            f"[GUILD_LEAGUE][PERSISTENT] restored {restored} "
            "dated panel views from channel history"
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(
            f"[GUILD_LEAGUE][PERSISTENT][HISTORY ERROR] "
            f"{type(exc).__name__}: {exc}"
        )


class GuildLeaguePersistentButtonsPatch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.history_task = None

    def cog_unload(self):
        if self.history_task and not self.history_task.done():
            self.history_task.cancel()


async def setup(bot):
    from cogs import guild_league_cog as league
    from cogs import guild_league_zzzzzzzzz_dated_posts_cog as dated

    patch_cog = GuildLeaguePersistentButtonsPatch(bot)

    main_cog = bot.get_cog("GuildLeagueCog")
    if main_cog is not None:
        try:
            message_id = main_cog.state.get("message_id")
            bot.add_view(
                league.MainView(main_cog),
                message_id=int(message_id) if message_id else None,
            )
            print("[GUILD_LEAGUE][PERSISTENT] main panel view registered")
        except Exception as exc:
            print(
                f"[GUILD_LEAGUE][PERSISTENT][MAIN] "
                f"{type(exc).__name__}: {exc}"
            )

    dated_cog = bot.get_cog("GuildLeagueDatedPosts")
    if dated_cog is not None:
        # Important: register EVERY saved dated panel, including past dates.
        # The original cog only restored today/future panels after a restart.
        count = _register_saved_views(bot, dated, dated_cog)
        print(
            f"[GUILD_LEAGUE][PERSISTENT] registered {count} "
            "saved dated panel views"
        )

        # Also discover old Guild League posts directly in Discord. This makes
        # their persistent custom_ids live again even after bot restarts.
        patch_cog.history_task = asyncio.create_task(
            _restore_views_from_history(bot, league, dated, dated_cog)
        )

    await bot.add_cog(patch_cog)
