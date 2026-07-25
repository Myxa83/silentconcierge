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

    @classmethod
    def _fetch_stats_selenium_sync(cls, url: str) -> dict | None:
        """Синхронно читає AP, AAP, DP і GS через Selenium."""
        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.support.ui import WebDriverWait
        except ImportError as error:
            print(f"[GEAR][ERROR] Selenium import: {error}")
            return None

        driver = None
        try:
            try:
                driver = webdriver.Chrome(options=cls._chrome_options())
            except Exception as selenium_manager_error:
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager

                print(
                    "[GEAR] Selenium Manager fallback: "
                    f"{type(selenium_manager_error).__name__}: "
                    f"{selenium_manager_error}"
                )
                driver = webdriver.Chrome(
                    service=Service(ChromeDriverManager().install()),
                    options=cls._chrome_options(),
                )

            driver.set_page_load_timeout(60)
            driver.get(url)

            values = WebDriverWait(driver, 30).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, ".grid-cols-4 .text-2xl")
                )
            )
            texts = [value.text.strip() for value in values]
            if len(texts) >= 4 and all(texts[:4]):
                return {
                    "ap": texts[0],
                    "aap": texts[1],
                    "dp": texts[2],
                    "gs": texts[3],
                }
        except Exception as error:
            print(
                f"[GEAR][ERROR] Selenium {url}: "
                f"{type(error).__name__}: {error}"
            )
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

        return None

    async def fetch_stats_selenium(self, url: str) -> dict | None:
        """Не блокує Discord під час роботи Selenium."""
        return await asyncio.to_thread(
            self._fetch_stats_selenium_sync,
            url,
        )

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
            await interaction.followup.send(
                "❌ Не вдалося зчитати Garmoth через технічну помилку. "
                "Профіль може бути публічним.",
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
