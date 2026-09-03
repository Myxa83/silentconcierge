from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
import discord
from discord.ext import commands


ASSET_DIR = Path("assets/icons/guild_league")
ROLE_ASSETS = {
    "tank": ("gl_tank_small", ASSET_DIR / "tank.png"),
    "dps": ("gl_dps_small", ASSET_DIR / "dps.png"),
    "shai": ("gl_shai_small", ASSET_DIR / "shai.png"),
}

# Discord renders a custom emoji in a fixed inline box. To make the visible
# symbol smaller we put the artwork inside a transparent 64x64 canvas.
VISIBLE_ICON_PX = 40
CANVAS_PX = 64


def _small_emoji_bytes(asset_path: Path) -> bytes:
    image = Image.open(asset_path).convert("RGBA")
    bbox = image.getchannel("A").getbbox()
    if bbox:
        image = image.crop(bbox)

    image.thumbnail(
        (VISIBLE_ICON_PX, VISIBLE_ICON_PX),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (CANVAS_PX, CANVAS_PX), (0, 0, 0, 0))
    x = (CANVAS_PX - image.width) // 2
    y = (CANVAS_PX - image.height) // 2
    canvas.alpha_composite(image, (x, y))

    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


class GuildLeagueRoleIconsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def _resolve_role_emojis(bot, league):
    guild = bot.get_guild(league.GUILD_ID)
    if guild is None:
        try:
            guild = await bot.fetch_guild(league.GUILD_ID)
        except Exception as exc:
            print(
                f"[GUILD_LEAGUE][ROLE_ICONS][GUILD] "
                f"{type(exc).__name__}: {exc}"
            )
            return {}

    try:
        emojis = list(await guild.fetch_emojis())
    except Exception:
        emojis = list(getattr(guild, "emojis", []) or [])

    by_name = {emoji.name: emoji for emoji in emojis}

    me = getattr(guild, "me", None)
    if me is None and bot.user is not None:
        try:
            me = guild.get_member(bot.user.id)
        except Exception:
            me = None

    permissions = getattr(me, "guild_permissions", None)
    can_manage = bool(
        permissions
        and (
            getattr(permissions, "manage_emojis_and_stickers", False)
            or getattr(permissions, "manage_expressions", False)
            or getattr(permissions, "administrator", False)
        )
    )

    resolved = {}
    for role_key, (emoji_name, asset_path) in ROLE_ASSETS.items():
        emoji = by_name.get(emoji_name)

        if emoji is None and can_manage and asset_path.exists():
            try:
                emoji = await guild.create_custom_emoji(
                    name=emoji_name,
                    image=_small_emoji_bytes(asset_path),
                    reason="Silent Concierge Guild League compact role icon",
                )
                by_name[emoji_name] = emoji
                print(
                    f"[GUILD_LEAGUE][ROLE_ICONS] created {emoji_name} "
                    f"id={emoji.id}"
                )
            except Exception as exc:
                print(
                    f"[GUILD_LEAGUE][ROLE_ICONS][CREATE] {emoji_name}: "
                    f"{type(exc).__name__}: {exc}"
                )

        if emoji is not None:
            resolved[role_key] = emoji
        elif not can_manage:
            print(
                f"[GUILD_LEAGUE][ROLE_ICONS] missing {emoji_name}; "
                "bot needs Manage Expressions/Emojis permission to create it"
            )

    return resolved


async def setup(bot):
    """Use compact Tank/DPS/Shai custom emojis in Guild League tables."""
    from cogs import guild_league_cog as league

    resolved = await _resolve_role_emojis(bot, league)
    if resolved:
        for role_key, emoji in resolved.items():
            old = league.ROLES.get(role_key)
            label = old[1] if old else role_key.title()
            league.ROLES[role_key] = (emoji, label)

        print(
            "[GUILD_LEAGUE][ROLE_ICONS] compact active: "
            + ", ".join(sorted(resolved))
        )

        dated_cog = bot.get_cog("GuildLeagueDatedPosts")
        if dated_cog is not None:
            for day_iso, event in list(dated_cog.data.get("events", {}).items()):
                if not isinstance(event, dict) or not event.get("message_id"):
                    continue
                try:
                    await dated_cog.refresh_date(day_iso)
                except Exception as exc:
                    print(
                        f"[GUILD_LEAGUE][ROLE_ICONS][REFRESH_DATE] {day_iso}: "
                        f"{type(exc).__name__}: {exc}"
                    )

        main_cog = bot.get_cog("GuildLeagueCog")
        if main_cog is not None:
            try:
                await main_cog.refresh()
            except Exception as exc:
                print(
                    f"[GUILD_LEAGUE][ROLE_ICONS][REFRESH_MAIN] "
                    f"{type(exc).__name__}: {exc}"
                )

    await bot.add_cog(GuildLeagueRoleIconsCog(bot))
