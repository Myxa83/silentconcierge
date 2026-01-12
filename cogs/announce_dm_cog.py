# -*- coding: utf-8 -*-
import asyncio
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands


# ---------------- CONFIG ----------------
ROLE_ALLOWED = [
    1375070910138028044,  # Leader
    1425974196181270671,  # Officer
    1323454517664157736,  # Moderator
]
FOOTER_TEXT = "Silent Concierge by Myxa"

# Anti rate limit. 0.6-1.2 сек зазвичай ок.
DM_DELAY_SECONDS = 1.0

LOG_DIR = Path("logs")
# ----------------------------------------


def _now_ts() -> int:
    return int(datetime.utcnow().timestamp())


def _write_json_log(entry: dict) -> None:
    """
    Пише в logs/YYYY-MM-DD.json (список записів).
    Якщо logs/ нема, створює.
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fn = LOG_DIR / f"{datetime.utcnow().strftime('%Y-%m-%d')}.json"

        if fn.exists():
            try:
                data = json.loads(fn.read_text(encoding="utf-8"))
                if not isinstance(data, list):
                    data = []
            except Exception:
                data = []
        else:
            data = []

        data.append(entry)
        fn.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # Логер не повинен валити бота
        pass


class AnnounceDMCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[COG][OK] Loaded cogs.announce_dm_cog")

    def _convert_github_link(self, url: str) -> str:
        # Конвертує GitHub blob у raw
        if "github.com" in url and "/blob/" in url:
            url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
        return url

    def _is_allowed(self, member: discord.Member) -> bool:
        return any(r.id in ROLE_ALLOWED for r in getattr(member, "roles", []))

    async def _safe_followup(self, interaction: discord.Interaction, text: str, ephemeral: bool = True) -> None:
        try:
            await interaction.followup.send(text, ephemeral=ephemeral)
        except Exception:
            # Якщо interaction вже помер, нічого не зробиш
            pass

    # ---------------- COMMAND ----------------
    @app_commands.command(
        name="announce_dm",
        description="Розіслати приватне повідомлення всім учасникам обраної ролі."
    )
    @app_commands.describe(
        role="Роль, якій потрібно відправити DM",
        text="Текст повідомлення",
        image_url="URL зображення (необов'язково, підтримує GitHub)",
        attachment="Завантажене зображення (необов'язково)"
    )
    async def announce_dm(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        text: str,
        image_url: Optional[str] = None,
        attachment: Optional[discord.Attachment] = None,
    ):
        ts = _now_ts()
        sender = interaction.user

        # ВАЖЛИВО: defer одразу, щоб не було "не відповідає"
        await interaction.response.defer(ephemeral=True, thinking=True)

        # Права
        if not isinstance(sender, discord.Member) or not self._is_allowed(sender):
            await self._safe_followup(interaction, "⛔ У вас немає прав для використання цієї команди.", ephemeral=True)
            _write_json_log({
                "ts": ts,
                "cog": "announce_dm_cog",
                "cmd": "announce_dm",
                "status": "denied",
                "user_id": getattr(sender, "id", None),
                "role_id": getattr(role, "id", None),
            })
            return

        # Build embed
        embed = discord.Embed(
            title="📢 Оголошення",
            description=text,
            color=discord.Color.gold(),
        )

        # Зображення
        if image_url:
            fixed_url = self._convert_github_link(image_url)
            if fixed_url.startswith(("http://", "https://")):
                embed.set_image(url=fixed_url)
        elif attachment:
            try:
                embed.set_image(url=attachment.url)
            except Exception:
                pass

        # Footer
        bot_avatar = self.bot.user.display_avatar.url if self.bot.user else None
        embed.set_footer(text=FOOTER_TEXT, icon_url=bot_avatar)

        # Автор
        try:
            author_avatar = sender.display_avatar.url
            author_link = f"https://discord.com/users/{sender.id}"
            author_markdown = f"[{sender.display_name}]({author_link})"
            embed.add_field(name="Автор:", value=author_markdown, inline=False)
            embed.set_thumbnail(url=author_avatar)
        except Exception:
            pass

        members = list(getattr(role, "members", []))
        total = len(members)

        await self._safe_followup(
            interaction,
            f"🔄 Розсилка запущена для ролі **{role.name}** ({total} користувачів).",
            ephemeral=True,
        )

        sent = 0
        failed_forbidden = 0
        failed_other = 0

        # Лог старту
        _write_json_log({
            "ts": ts,
            "cog": "announce_dm_cog",
            "cmd": "announce_dm",
            "status": "started",
            "user_id": sender.id,
            "guild_id": getattr(interaction.guild, "id", None),
            "role_id": role.id,
            "role_name": role.name,
            "total_members": total,
        })

        for idx, member in enumerate(members, start=1):
            try:
                await member.send(embed=embed)
                sent += 1

            except discord.Forbidden:
                failed_forbidden += 1

            except Exception as e:
                failed_other += 1
                tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                # В консоль коротко, щоб не шуміти
                print(f"[announce_dm][ERR] member_id={getattr(member,'id',None)} {type(e).__name__}: {e}")
                # В json детально
                _write_json_log({
                    "ts": _now_ts(),
                    "cog": "announce_dm_cog",
                    "cmd": "announce_dm",
                    "status": "error",
                    "user_id": sender.id,
                    "target_id": getattr(member, "id", None),
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "traceback": tb,
                })

            # Пауза проти rate limit
            if DM_DELAY_SECONDS > 0:
                await asyncio.sleep(DM_DELAY_SECONDS)

            # Прогрес кожні 25, щоб ти бачила що воно живе
            if idx % 25 == 0:
                await self._safe_followup(
                    interaction,
                    f"⏳ Прогрес: {idx}/{total}. Успішно: {sent}, заблоковано: {failed_forbidden}, інше: {failed_other}.",
                    ephemeral=True,
                )

        await self._safe_followup(
            interaction,
            f"✅ Розсилка завершена.\n"
            f"Успішно: **{sent}**\n"
            f"Не вдалося (DM закриті): **{failed_forbidden}**\n"
            f"Інші помилки: **{failed_other}**",
            ephemeral=True,
        )

        _write_json_log({
            "ts": _now_ts(),
            "cog": "announce_dm_cog",
            "cmd": "announce_dm",
            "status": "finished",
            "user_id": sender.id,
            "role_id": role.id,
            "sent": sent,
            "failed_forbidden": failed_forbidden,
            "failed_other": failed_other,
        })


# ---------------- SETUP -----------------
async def setup(bot: commands.Bot):
    await bot.add_cog(AnnounceDMCog(bot))
