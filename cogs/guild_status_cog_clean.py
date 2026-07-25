# -*- coding: utf-8 -*-
"""Перевірка складу SilentCove на офіційному сайті BDO."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from data.mongo_store import append_event


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


DISCORD_GUILD_ID = env_int("GUILD_ID", 1323454227816906802)

BDO_GUILD_NAME = os.getenv("BDO_GUILD_NAME", "SilentCove").strip() or "SilentCove"
BDO_GUILD_REGION = os.getenv("BDO_GUILD_REGION", "EU").strip().upper() or "EU"
BDO_GUILD_URL = (
    "https://www.naeu.playblackdesert.com/en-US/Adventure/Guild/"
    f"GuildProfile?guildName={BDO_GUILD_NAME}&region={BDO_GUILD_REGION}"
)

ROLE_CHECKED_MEMBERS = env_int(
    "BDO_CHECKED_MEMBERS_ROLE_ID",
    1383410423704846396,
)
ROLE_GUEST = env_int(
    "BDO_GUEST_ROLE_ID",
    1325118787019866253,
)

MEMBER_LINK_SELECTOR = (
    'article .guild_name .character_desc .text '
    'a[href*="/Adventure/Profile?profileTarget="]'
)
GUILD_NAME_SELECTOR = "article .profile_detail .guild_name p"
GUILD_INFO_SELECTOR = "article .line_list.guild_info li"
AUDIT_COLLECTION = "guild_membership_audits"

FAMILY_NAME_PATTERN = re.compile(
    r"^\s*\[\s*SC\s*\]\s*(?P<family>.+?)(?:\s*\|\s*.+)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GuildRoster:
    guild_name: str
    expected_members: int
    family_names: tuple[str, ...]
    source_url: str


@dataclass
class MembershipCheckResult:
    roster_members: int
    discord_members: int
    present: list[tuple[discord.Member, str]]
    absent: list[tuple[discord.Member, str]]
    skipped: list[discord.Member]
    guest_added: list[tuple[discord.Member, str]]
    already_guest: list[tuple[discord.Member, str]]
    failed: list[tuple[discord.Member, str, str]]


def normalize_family_name(value: str) -> str:
    """Нормалізує звичайні й декоративні Unicode-літери для порівняння."""
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return "".join(character for character in normalized if character.isalnum())


def extract_family_name(display_name: str) -> str | None:
    """Дістає Family Name з ніку формату ``[SC] Family | Ім'я``."""
    match = FAMILY_NAME_PATTERN.match(display_name or "")
    if not match:
        return None

    family_name = match.group("family").strip()
    return family_name or None


def compare_members(
    members: list[discord.Member],
    roster_family_names: tuple[str, ...],
) -> tuple[
    list[tuple[discord.Member, str]],
    list[tuple[discord.Member, str]],
    list[discord.Member],
]:
    """Порівнює Discord-ніки зі списком Family Name з сайту BDO."""
    roster_keys = {
        normalize_family_name(name)
        for name in roster_family_names
        if normalize_family_name(name)
    }

    present: list[tuple[discord.Member, str]] = []
    absent: list[tuple[discord.Member, str]] = []
    skipped: list[discord.Member] = []

    for member in members:
        if member.bot:
            continue

        family_name = extract_family_name(member.display_name)
        family_key = normalize_family_name(family_name or "")
        if not family_name or not family_key:
            skipped.append(member)
        elif family_key in roster_keys:
            present.append((member, family_name))
        else:
            absent.append((member, family_name))

    return present, absent, skipped


class GuildStatusCog(commands.Cog):
    """Звіряє роль SilentCove з офіційним списком гільдії."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_lock = asyncio.Lock()
        self.scheduled_check.start()

    def cog_unload(self) -> None:
        self.scheduled_check.cancel()

    @staticmethod
    def _chrome_options():
        from selenium.webdriver.chrome.options import Options

        options = Options()
        options.page_load_strategy = "eager"
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--lang=en-US")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

        browser_binary = (
            os.getenv("CHROME_BIN")
            or os.getenv("GOOGLE_CHROME_BIN")
            or shutil.which("google-chrome")
            or shutil.which("google-chrome-stable")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
        )
        if browser_binary:
            options.binary_location = browser_binary

        return options

    @staticmethod
    def _read_expected_member_count(driver) -> int | None:
        from selenium.webdriver.common.by import By

        for item in driver.find_elements(By.CSS_SELECTOR, GUILD_INFO_SELECTOR):
            text = " ".join(item.text.split())
            if "Members" not in text:
                continue
            match = re.search(r"(\d+)\s*Members", text, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    @classmethod
    def _fetch_roster_selenium_sync(cls) -> GuildRoster:
        """Відкриває офіційний профіль гільдії та читає Family Name."""
        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as error:
            raise RuntimeError(
                "Selenium не встановлено в середовищі бота"
            ) from error

        driver = None
        try:
            try:
                driver = webdriver.Chrome(options=cls._chrome_options())
            except Exception as selenium_manager_error:
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager

                print(
                    "[GUILD_MEMBERSHIP] Selenium Manager fallback: "
                    f"{type(selenium_manager_error).__name__}: "
                    f"{selenium_manager_error}"
                )
                driver = webdriver.Chrome(
                    service=Service(ChromeDriverManager().install()),
                    options=cls._chrome_options(),
                )

            driver.set_page_load_timeout(60)
            driver.get(BDO_GUILD_URL)

            def roster_is_complete(current_driver):
                expected = cls._read_expected_member_count(current_driver)
                found = current_driver.find_elements(
                    By.CSS_SELECTOR,
                    MEMBER_LINK_SELECTOR,
                )
                return bool(expected and len(found) >= expected)

            WebDriverWait(driver, 45).until(roster_is_complete)

            guild_name_element = driver.find_element(
                By.CSS_SELECTOR,
                GUILD_NAME_SELECTOR,
            )
            page_guild_name = guild_name_element.text.strip()
            if normalize_family_name(page_guild_name) != normalize_family_name(
                BDO_GUILD_NAME
            ):
                raise RuntimeError(
                    "Сайт відкрив іншу гільдію: "
                    f"очікувалась {BDO_GUILD_NAME}, отримано {page_guild_name}"
                )

            expected_members = cls._read_expected_member_count(driver)
            if not expected_members:
                raise RuntimeError(
                    "Не вдалося прочитати кількість учасників гільдії"
                )

            family_names: list[str] = []
            seen: set[str] = set()
            for link in driver.find_elements(
                By.CSS_SELECTOR,
                MEMBER_LINK_SELECTOR,
            ):
                family_name = link.text.strip()
                family_key = normalize_family_name(family_name)
                if family_name and family_key and family_key not in seen:
                    seen.add(family_key)
                    family_names.append(family_name)

            if len(family_names) != expected_members:
                raise RuntimeError(
                    "Список BDO завантажився не повністю: "
                    f"очікується {expected_members}, прочитано {len(family_names)}"
                )

            return GuildRoster(
                guild_name=page_guild_name,
                expected_members=expected_members,
                family_names=tuple(family_names),
                source_url=BDO_GUILD_URL,
            )
        except Exception as error:
            raise RuntimeError(
                f"{type(error).__name__}: {error}"
            ) from error
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    async def fetch_roster(self) -> GuildRoster:
        """Запускає Selenium в окремому потоці та не блокує Discord."""
        return await asyncio.to_thread(self._fetch_roster_selenium_sync)

    async def run_membership_check(
        self,
        guild: discord.Guild,
        *,
        apply_guest_roles: bool,
        trigger: str,
        requested_by: int | None = None,
    ) -> MembershipCheckResult:
        if self.check_lock.locked():
            raise RuntimeError("Перевірка складу гільдії вже виконується")

        async with self.check_lock:
            roster = await self.fetch_roster()

            checked_members_role = guild.get_role(ROLE_CHECKED_MEMBERS)
            guest_role = guild.get_role(ROLE_GUEST)
            if checked_members_role is None:
                raise RuntimeError(
                    "На сервері не знайдено роль для перевірки "
                    f"`{ROLE_CHECKED_MEMBERS}`"
                )
            if guest_role is None:
                raise RuntimeError(
                    f"На сервері не знайдено роль Гість `{ROLE_GUEST}`"
                )

            candidates = list(checked_members_role.members)
            present, absent, skipped = compare_members(
                candidates,
                roster.family_names,
            )

            result = MembershipCheckResult(
                roster_members=len(roster.family_names),
                discord_members=len(candidates),
                present=present,
                absent=absent,
                skipped=skipped,
                guest_added=[],
                already_guest=[],
                failed=[],
            )

            for member, family_name in absent:
                if guest_role in member.roles:
                    result.already_guest.append((member, family_name))
                    continue
                if not apply_guest_roles:
                    continue

                try:
                    await member.add_roles(
                        guest_role,
                        reason=(
                            f"Family Name {family_name} відсутній у "
                            f"{BDO_GUILD_NAME} на офіційному сайті BDO"
                        ),
                    )
                    result.guest_added.append((member, family_name))
                except Exception as error:
                    result.failed.append(
                        (
                            member,
                            family_name,
                            f"{type(error).__name__}: {error}",
                        )
                    )

            append_event(
                AUDIT_COLLECTION,
                {
                    "guild_id": guild.id,
                    "bdo_guild": roster.guild_name,
                    "bdo_region": BDO_GUILD_REGION,
                    "source_url": roster.source_url,
                    "trigger": trigger,
                    "requested_by": requested_by,
                    "apply_guest_roles": apply_guest_roles,
                    "roster_members": result.roster_members,
                    "discord_members": result.discord_members,
                    "present": [
                        {"user_id": member.id, "family": family}
                        for member, family in result.present
                    ],
                    "absent": [
                        {"user_id": member.id, "family": family}
                        for member, family in result.absent
                    ],
                    "skipped": [
                        {
                            "user_id": member.id,
                            "display_name": member.display_name,
                        }
                        for member in result.skipped
                    ],
                    "guest_added": [
                        {"user_id": member.id, "family": family}
                        for member, family in result.guest_added
                    ],
                    "already_guest": [
                        {"user_id": member.id, "family": family}
                        for member, family in result.already_guest
                    ],
                    "failed": [
                        {
                            "user_id": member.id,
                            "family": family,
                            "error": error,
                        }
                        for member, family, error in result.failed
                    ],
                    "checked_at": datetime.now(timezone.utc),
                },
            )
            return result

    @staticmethod
    def _format_result(
        result: MembershipCheckResult,
        apply_guest_roles: bool,
    ) -> str:
        lines = [
            "✅ **Перевірку SilentCove завершено**",
            f"Офіційний сайт BDO: **{result.roster_members}** учасників",
            f"Discord із роллю для перевірки: **{result.discord_members}**",
            f"Знайдено в гільдії: **{len(result.present)}**",
            f"Не знайдено: **{len(result.absent)}**",
            f"Не вдалося прочитати Family Name з ніку: **{len(result.skipped)}**",
        ]

        if apply_guest_roles:
            lines.append(
                f"Роль «Гість» додано: **{len(result.guest_added)}**"
            )
        else:
            lines.append("Режим перегляду, ролі не змінювалися.")

        if result.already_guest:
            lines.append(
                f"Уже мали роль «Гість»: **{len(result.already_guest)}**"
            )
        if result.failed:
            lines.append(
                f"Помилки видачі ролі: **{len(result.failed)}**"
            )

        if result.absent:
            names = ", ".join(
                f"{member.mention} (`{family}`)"
                for member, family in result.absent[:20]
            )
            if len(result.absent) > 20:
                names += f", ще {len(result.absent) - 20}"
            lines.extend(["", "**Відсутні на сайті:**", names])

        if result.skipped:
            names = ", ".join(
                member.mention
                for member in result.skipped[:20]
            )
            if len(result.skipped) > 20:
                names += f", ще {len(result.skipped) - 20}"
            lines.extend(
                [
                    "",
                    "**Нік не відповідає формату `[SC] Family | Ім'я`:**",
                    names,
                ]
            )

        return "\n".join(lines)[:4000]

    @app_commands.command(
        name="guild_members_check",
        description="Звірити SilentCove з офіційним сайтом BDO",
    )
    @app_commands.describe(
        apply_guest_roles=(
            "Додати роль «Гість» тим, кого немає у списку гільдії"
        )
    )
    @app_commands.default_permissions(manage_guild=True)
    async def guild_members_check(
        self,
        interaction: discord.Interaction,
        apply_guest_roles: bool = True,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Ця команда працює лише на сервері.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.run_membership_check(
                interaction.guild,
                apply_guest_roles=apply_guest_roles,
                trigger="manual",
                requested_by=interaction.user.id,
            )
        except Exception as error:
            await interaction.followup.send(
                "❌ Перевірку зупинено без зміни ролей.\n"
                f"`{type(error).__name__}: {error}`",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            self._format_result(result, apply_guest_roles),
            ephemeral=True,
        )

    @tasks.loop(hours=6)
    async def scheduled_check(self) -> None:
        guild = self.bot.get_guild(DISCORD_GUILD_ID)
        if guild is None:
            print(
                f"[GUILD_MEMBERSHIP][WARN] Discord guild "
                f"{DISCORD_GUILD_ID} not found"
            )
            return

        try:
            result = await self.run_membership_check(
                guild,
                apply_guest_roles=True,
                trigger="scheduled",
            )
            print(
                "[GUILD_MEMBERSHIP][OK] "
                f"site={result.roster_members} "
                f"discord={result.discord_members} "
                f"absent={len(result.absent)} "
                f"guest_added={len(result.guest_added)}"
            )
        except Exception as error:
            print(
                "[GUILD_MEMBERSHIP][ERROR] "
                f"{type(error).__name__}: {error}"
            )

    @scheduled_check.before_loop
    async def before_scheduled_check(self) -> None:
        await self.bot.wait_until_ready()
        await asyncio.sleep(120)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GuildStatusCog(bot))
