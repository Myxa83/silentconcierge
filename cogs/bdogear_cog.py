# -*- coding: utf-8 -*-
# _bdogear_cog.py — MongoDB версія

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import re
import shutil
import time
from datetime import datetime, timezone

from data.gear_store import load_gear, save_gear

# ─── Cog ──────────────────────────────────────────────────────────────────────

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot              = bot
        self.delays           = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]
        self.target_channel_id = 1358443998603120824
        self.update_lock = asyncio.Lock()
        self.collect_running = False
        self.collect_stop_requested = False
        self.collect_stop_event = asyncio.Event()
        self.collect_owner_id = None
        self.last_scrape_error: str | None = None

    @staticmethod
    def _extract_garmoth_link(content: str) -> str | None:
        pattern = (
            r"https?://(?:www\.)?garmoth\.com/character/"
            r"[A-Za-z0-9_-]+"
        )
        links = re.findall(pattern, content or "")
        return links[-1] if links else None

    @staticmethod
    def _gear_entry(member, link: str, stats: dict) -> dict:
        return {
            "display_name": member.display_name,
            "link": link,
            "gs": stats["gs"],
            "ap": stats["ap"],
            "aap": stats["aap"],
            "dp": stats["dp"],
            "user_id": member.id,
            "updated": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "updated_at": datetime.now(timezone.utc),
        }

    @staticmethod
    def _clean_stat_value(value) -> str | None:
        """Повертає чисте числове значення стату."""
        match = re.search(r"\b(\d{2,4})\b", str(value or ""))
        return match.group(1) if match else None

    @classmethod
    def _stats_from_sequence(cls, values) -> dict | None:
        """
        Шукає AP/AAP/DP/GS у послідовності чисел.

        Garmoth час від часу змінює Tailwind-класи, тому не покладаємося
        лише на один CSS-селектор. Для перевірки кандидата використовуємо
        співвідношення GS ≈ середнє AP/AAP + DP.
        """
        numbers: list[int] = []
        for value in values or []:
            cleaned = cls._clean_stat_value(value)
            if not cleaned:
                continue
            number = int(cleaned)
            if numbers and numbers[-1] == number:
                continue
            numbers.append(number)

        best = None
        best_delta = 10_000

        for index in range(max(0, len(numbers) - 3)):
            ap, aap, dp, gs = numbers[index:index + 4]

            if not (100 <= ap <= 500 and 100 <= aap <= 500):
                continue
            if not (150 <= dp <= 700 and 300 <= gs <= 1200):
                continue

            expected_gs = ((ap + aap) // 2) + dp
            delta = abs(gs - expected_gs)

            if delta < best_delta and delta <= 25:
                best_delta = delta
                best = {
                    "ap": str(ap),
                    "aap": str(aap),
                    "dp": str(dp),
                    "gs": str(gs),
                }

        return best

    @classmethod
    def _stats_from_labelled_text(cls, body_text: str) -> dict | None:
        """Фолбек: читає значення біля підписів AP/AAP/DP/GS."""
        lines = [
            " ".join(line.split()).strip()
            for line in (body_text or "").splitlines()
            if line.strip()
        ]

        aliases = {
            "ap": {"AP", "ATTACK POWER"},
            "aap": {"AAP", "AWAKENING AP", "AWAKENING ATTACK POWER"},
            "dp": {"DP", "DEFENSE POWER"},
            "gs": {"GS", "GEAR SCORE", "GEARSCORE"},
        }
        found: dict[str, str] = {}

        for key, names in aliases.items():
            for index, line in enumerate(lines):
                if line.upper() not in names:
                    continue

                nearby = []
                if index > 0:
                    nearby.append(lines[index - 1])
                if index + 1 < len(lines):
                    nearby.append(lines[index + 1])
                if index + 2 < len(lines):
                    nearby.append(lines[index + 2])

                for candidate in nearby:
                    value = cls._clean_stat_value(candidate)
                    if value:
                        found[key] = value
                        break

                if key in found:
                    break

        if set(found) == {"ap", "aap", "dp", "gs"}:
            return found
        return None

    @staticmethod
    def _system_chromium_path() -> str | None:
        """Шукає Chromium/Chrome, якщо Playwright browser cache недоступний."""
        candidates = (
            os.getenv("CHROME_BIN"),
            os.getenv("GOOGLE_CHROME_BIN"),
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        )
        return next(
            (
                path
                for path in candidates
                if path and os.path.exists(path)
            ),
            None,
        )

    async def fetch_stats_selenium(self, url: str) -> dict | None:
        """
        Зчитує AP/AAP/DP/GS через Playwright.

        Назву методу залишено для сумісності зі старими викликами cog-а.
        """
        self.last_scrape_error = None

        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            self.last_scrape_error = (
                "Playwright не встановлено: "
                f"{type(error).__name__}: {error}"
            )
            print(f"[GEAR][ERROR] {self.last_scrape_error}")
            return None

        browser = None
        context = None

        try:
            async with async_playwright() as playwright:
                launch_kwargs = {
                    "headless": True,
                    "args": [
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--disable-extensions",
                        "--disable-blink-features=AutomationControlled",
                    ],
                }

                system_browser = self._system_chromium_path()
                playwright_browser = playwright.chromium.executable_path

                if system_browser:
                    launch_kwargs["executable_path"] = system_browser
                elif playwright_browser and os.path.exists(playwright_browser):
                    launch_kwargs["executable_path"] = playwright_browser

                browser = await playwright.chromium.launch(**launch_kwargs)
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/152.0.0.0 Safari/537.36"
                    ),
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )

                await context.add_init_script(
                    """
                    Object.defineProperty(
                        navigator,
                        'webdriver',
                        {get: () => undefined}
                    );
                    """
                )

                page = await context.new_page()
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=90_000,
                )

                # Garmoth є SPA: даємо сторінці час підтягнути build.
                for _ in range(20):
                    await page.wait_for_timeout(1_000)

                    legacy_count = await page.locator(
                        ".grid-cols-4 .text-2xl"
                    ).count()
                    if legacy_count >= 4:
                        break

                    body_now = await page.locator("body").inner_text()
                    if any(
                        marker in body_now.lower()
                        for marker in (
                            "just a moment",
                            "verify you are human",
                            "checking your browser",
                        )
                    ):
                        continue

                    if (
                        "gear builder" in body_now.lower()
                        and len(body_now) > 500
                    ):
                        break

                title = await page.title()
                body_text = await page.locator("body").inner_text()
                body_lower = body_text.lower()

                if any(
                    marker in body_lower
                    for marker in (
                        "just a moment",
                        "verify you are human",
                        "checking your browser",
                    )
                ):
                    raise RuntimeError(
                        "Garmoth показав перевірку Cloudflare "
                        "замість профілю"
                    )

                # 1. Старий layout, якщо Garmoth його ще віддає.
                legacy_values = await page.locator(
                    ".grid-cols-4 .text-2xl"
                ).all_inner_texts()
                stats = self._stats_from_sequence(legacy_values)
                if stats:
                    return stats

                # 2. Новий layout: шукаємо значення біля AP/AAP/DP/GS.
                stats = self._stats_from_labelled_text(body_text)
                if stats:
                    return stats

                # 3. Останній фолбек: числа з leaf-елементів у DOM.
                leaf_values = await page.locator("body *").evaluate_all(
                    """
                    (elements) => elements
                        .filter((el) =>
                            el.children.length === 0 &&
                            /^\\s*\\d{2,4}\\s*$/.test(
                                el.textContent || ''
                            )
                        )
                        .map((el) => (el.textContent || '').trim())
                    """
                )
                stats = self._stats_from_sequence(leaf_values)
                if stats:
                    return stats

                sample = ", ".join(leaf_values[:30])
                raise RuntimeError(
                    "сторінка відкрилась, але AP/AAP/DP/GS не знайдені; "
                    f"title={title!r}; числа={sample or 'немає'}"
                )

        except Exception as error:
            self.last_scrape_error = (
                f"{type(error).__name__}: {error}"
            )
            print(
                f"[GEAR][ERROR] Garmoth {url}: "
                f"{self.last_scrape_error}"
            )
            return None
        finally:
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def update_member_gear(
        self,
        member,
        link: str,
    ) -> dict | None:
        """Зчитує Garmoth і зберігає актуальний гір за Discord ID."""
        async with self.update_lock:
            stats = await self.fetch_stats_selenium(link)
            if not stats:
                return None

            gear_data = load_gear()
            gear_data[str(member.id)] = self._gear_entry(
                member,
                link,
                stats,
            )
            return stats if save_gear(gear_data) else None

    async def run_mass_collect(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Масовий збір статсів."""
        await interaction.followup.send(f"⚙️ **Запуск...** Отримую дані з #{channel.name}")

        gear_data = load_gear()
        count     = 0
        stopped   = False

        messages = [msg async for msg in channel.history(limit=500)]
        valid_messages = [
            message
            for message in messages
            if self._extract_garmoth_link(message.content)
        ]
        valid_messages.reverse()

        try:
            for message in valid_messages:
                if self.collect_stop_requested:
                    stopped = True
                    break

                link = self._extract_garmoth_link(message.content)
                if not link:
                    continue

                author_name = message.author.display_name
                count      += 1
                stats       = await self.fetch_stats_selenium(link)
                unix_time   = int(time.time())
                wait_time   = self.delays[
                    (count - 1) % len(self.delays)
                ]

                embed = discord.Embed(
                    title="✨ Garmoth Profile Updated",
                    description=(
                        f"Дані гравця **{author_name}** оновлено."
                    ),
                    color=discord.Color.blue(),
                    timestamp=datetime.now(),
                )

                if stats:
                    embed.add_field(
                        name="⚔️ AP/AAP",
                        value=f"{stats['ap']} / {stats['aap']}",
                        inline=True,
                    )
                    embed.add_field(
                        name="🛡️ DP",
                        value=stats["dp"],
                        inline=True,
                    )
                    embed.add_field(
                        name="🌟 GS",
                        value=f"**{stats['gs']}**",
                        inline=True,
                    )
                    gear_data[str(message.author.id)] = (
                        self._gear_entry(
                            message.author,
                            link,
                            stats,
                        )
                    )
                else:
                    embed.add_field(
                        name="Статус",
                        value=(
                            "❌ Не вдалося зчитати Garmoth. "
                            "Це технічна помилка, а не ознака "
                            "приватного профілю."
                        ),
                        inline=False,
                    )

                embed.add_field(
                    name="🕒 Час",
                    value=f"<t:{unix_time}:f>",
                    inline=False,
                )
                embed.add_field(
                    name="🔗 Посилання",
                    value=f"[Garmoth]({link})",
                    inline=False,
                )
                embed.set_footer(
                    text=(
                        f"Прогрес: {count} | "
                        f"Очікування: {wait_time}с"
                    ),
                    icon_url=message.author.display_avatar.url,
                )

                await interaction.channel.send(embed=embed)

                if self.collect_stop_requested:
                    stopped = True
                    break

                try:
                    await asyncio.wait_for(
                        self.collect_stop_event.wait(),
                        timeout=wait_time,
                    )
                    stopped = True
                    break
                except asyncio.TimeoutError:
                    pass
        finally:
            save_gear(gear_data)
            self.collect_running = False
            self.collect_stop_requested = False
            self.collect_stop_event.clear()
            self.collect_owner_id = None

        players_count = len(load_gear())
        if stopped:
            await interaction.channel.send(
                f"⏹️ **Збір зупинено.** Оброблено профілів: "
                f"{count}. У базі гравців: {players_count}"
            )
        else:
            await interaction.channel.send(
                f"✅ **Парсинг завершено!** В базі тепер гравців: "
                f"{players_count}"
            )

    # ── Slash команди ────────────────────────────────────────────────────────

    @app_commands.command(name="collect", description="Масовий збір статсів гільдії")
    async def collect(self, interaction: discord.Interaction):
        if self.collect_running:
            await interaction.response.send_message(
                "⚠️ Збір уже працює. Для зупинки використай "
                "`/collect_stop`.",
                ephemeral=True,
            )
            return

        self.collect_running = True
        self.collect_stop_requested = False
        self.collect_stop_event.clear()
        self.collect_owner_id = interaction.user.id
        await interaction.response.defer()
        try:
            channel = (
                self.bot.get_channel(self.target_channel_id)
                or await self.bot.fetch_channel(
                    self.target_channel_id
                )
            )
            await self.run_mass_collect(interaction, channel)
        except Exception:
            self.collect_running = False
            self.collect_stop_requested = False
            self.collect_stop_event.clear()
            self.collect_owner_id = None
            raise

    @app_commands.command(
        name="collect_stop",
        description="Безпечно зупинити поточний збір Garmoth",
    )
    async def collect_stop(self, interaction: discord.Interaction):
        if not self.collect_running:
            await interaction.response.send_message(
                "ℹ️ Збір зараз не запущений.",
                ephemeral=True,
            )
            return

        permissions = getattr(
            interaction.user,
            "guild_permissions",
            None,
        )
        can_stop = (
            interaction.user.id == self.collect_owner_id
            or bool(
                permissions
                and permissions.manage_guild
            )
        )
        if not can_stop:
            await interaction.response.send_message(
                "❌ Зупинити збір може той, хто його запустив, "
                "або адміністратор.",
                ephemeral=True,
            )
            return

        self.collect_stop_requested = True
        self.collect_stop_event.set()
        await interaction.response.send_message(
            "⏹️ Зупинку прийнято. Завершую поточний профіль, "
            "зберігаю дані й не переходжу до наступного.",
            ephemeral=True,
        )

    @app_commands.command(name="gear_find", description="Знайти ГС гравця за нікнеймом")
    @app_commands.describe(nickname="Нікнейм гравця в Discord")
    async def gear_find(self, interaction: discord.Interaction, nickname: str):
        gear_data = load_gear()
        nickname_key = nickname.casefold()
        user_info = next(
            (
                value
                for value in gear_data.values()
                if str(value.get("display_name", "")).casefold()
                == nickname_key
            ),
            None,
        )

        if not user_info:
            await interaction.response.send_message(
                f"❌ Гравця **{nickname}** не знайдено. Запустіть `/collect` спочатку.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title = f"🛡️ Gear Info: {user_info['display_name']}",
            color = discord.Color.green(),
            url   = user_info["link"],
        )
        embed.add_field(name="⚔️ AP/AAP",           value=f"{user_info.get('ap','??')} / {user_info.get('aap','??')}", inline=True)
        embed.add_field(name="🛡️ DP",               value=user_info.get("dp", "??"),                                   inline=True)
        embed.add_field(name="🌟 Gearscore",         value=f"**{user_info.get('gs','??')}**",                           inline=True)
        embed.add_field(name="📅 Останнє оновлення", value=user_info.get("updated", "Невідомо"),                        inline=False)
        embed.set_footer(text=f"ID: {user_info.get('user_id')}")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="gear_list", description="Показати всіх гравців у базі")
    async def gear_list(self, interaction: discord.Interaction):
        gear_data = load_gear()
        if not gear_data:
            await interaction.response.send_message("ℹ️ База порожня. Запустіть `/collect`.", ephemeral=True)
            return

        sorted_players = sorted(
            gear_data.values(),
            key=lambda x: int(x.get("gs", "0").replace(",", "").replace(".", "") or "0"),
            reverse=True,
        )

        lines = []
        for i, p in enumerate(sorted_players, 1):
            lines.append(f"`{i:02}.` **{p['display_name']}** — GS: **{p.get('gs','??')}** | AP: {p.get('ap','??')}/{p.get('aap','??')} | DP: {p.get('dp','??')}")

        # Розбиваємо на частини якщо більше 20 гравців
        chunk_size = 20
        chunks     = [lines[i:i+chunk_size] for i in range(0, len(lines), chunk_size)]

        for idx, chunk in enumerate(chunks):
            embed = discord.Embed(
                title       = f"🌟 Gear List ({idx*chunk_size+1}-{idx*chunk_size+len(chunk)} з {len(lines)})",
                description = "\n".join(chunk),
                color       = discord.Color.gold(),
            )
            if idx == 0:
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.followup.send(embed=embed)

    @app_commands.command(name="gear_update", description="Оновити дані одного гравця за посиланням")
    @app_commands.describe(посилання="Посилання на Garmoth профіль")
    async def gear_update(self, interaction: discord.Interaction, посилання: str):
        await interaction.response.defer(ephemeral=True)

        if "garmoth.com/character/" not in посилання:
            await interaction.followup.send("❌ Невірне посилання. Потрібно garmoth.com/character/...", ephemeral=True)
            return

        stats = await self.update_member_gear(
            interaction.user,
            посилання,
        )
        if not stats:
            detail = self.last_scrape_error or "невідома помилка"
            await interaction.followup.send(
                "❌ Не вдалося зчитати Garmoth.\n"
                f"Причина: \`{detail[:1200]}\`",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Твої дані оновлено!\n"
            f"⚔️ AP/AAP: {stats['ap']}/{stats['aap']} | 🛡️ DP: {stats['dp']} | 🌟 GS: **{stats['gs']}**",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(BdoGear(bot))
    print("[COG] BdoGear завантажено")
