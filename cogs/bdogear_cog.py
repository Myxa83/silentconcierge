# -*- coding: utf-8 -*-
# _bdogear_cog.py — MongoDB версія

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import gc
import os
import re
import shutil
import subprocess
import sys
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
        self.browser_install_lock = asyncio.Lock()

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
        """Читає значення біля підписів AP/AAP/DP/GS."""
        lines = [
            " ".join(line.split()).strip()
            for line in (body_text or "").splitlines()
            if line.strip()
        ]

        aliases = {
            "ap": ("AP", "ATTACK POWER"),
            "aap": (
                "AAP",
                "AWAKENING AP",
                "AWAKENING ATTACK POWER",
            ),
            "dp": ("DP", "DEFENSE POWER", "DEFENCE POWER"),
            "gs": ("GS", "GEAR SCORE", "GEARSCORE"),
        }
        found: dict[str, str] = {}

        # Новий Garmoth часто тримає "AP 336" в одному рядку.
        for key, names in aliases.items():
            for line in lines:
                upper = line.upper()
                for name in names:
                    pattern = (
                        r"(?:^|\b)"
                        + re.escape(name)
                        + r"(?:\b|\s*[:=])[^0-9]{0,30}(\d{2,4})"
                    )
                    match = re.search(pattern, upper)
                    if match:
                        found[key] = match.group(1)
                        break
                if key in found:
                    break

        # Старий layout: label і число були сусідніми елементами.
        for key, names in aliases.items():
            if key in found:
                continue
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

        if {"ap", "aap", "dp"}.issubset(found):
            ap = int(found["ap"])
            aap = int(found["aap"])
            dp = int(found["dp"])
            gs = int(found.get("gs") or ((ap + aap) // 2 + dp))
            return cls._stats_from_sequence(
                [str(ap), str(aap), str(dp), str(gs)]
            )
        return None

    @staticmethod
    def _normalise_stat_key(value) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

    @classmethod
    def _stats_from_json(cls, payload) -> dict | None:
        """Шукає sheet AP/AAP/DP/GS у JSON, який повертає Garmoth."""
        aliases = {
            "ap": {
                "ap",
                "sheetap",
                "mainap",
                "mainhandap",
                "attackpower",
            },
            "aap": {
                "aap",
                "sheetaap",
                "awakeningap",
                "awakeningattackpower",
                "awakeningpower",
            },
            "dp": {
                "dp",
                "sheetdp",
                "defensepower",
                "defencepower",
            },
            "gs": {
                "gs",
                "sheetgs",
                "gearscore",
                "gearscoretotal",
            },
        }

        def scalar(value):
            if isinstance(value, bool):
                return None
            if isinstance(value, (int, float)):
                return str(int(value))
            if isinstance(value, str):
                return cls._clean_stat_value(value)
            return None

        def direct_dict(candidate):
            if not isinstance(candidate, dict):
                return None

            found = {}
            for raw_key, raw_value in candidate.items():
                key = cls._normalise_stat_key(raw_key)
                value = scalar(raw_value)
                if not value:
                    continue
                for stat, names in aliases.items():
                    if key in names:
                        found[stat] = value
                        break

            if {"ap", "aap", "dp"}.issubset(found):
                ap = int(found["ap"])
                aap = int(found["aap"])
                dp = int(found["dp"])
                gs = int(found.get("gs") or ((ap + aap) // 2 + dp))
                return cls._stats_from_sequence(
                    [str(ap), str(aap), str(dp), str(gs)]
                )
            return None

        def labelled_list(candidate):
            if not isinstance(candidate, list):
                return None

            found = {}
            for item in candidate:
                if not isinstance(item, dict):
                    continue

                label = None
                value = None
                for key in ("name", "label", "key", "title", "type", "stat"):
                    if key in item:
                        label = item.get(key)
                        break
                for key in ("value", "val", "amount", "total", "number"):
                    if key in item:
                        value = item.get(key)
                        break

                norm = cls._normalise_stat_key(label)
                number = scalar(value)
                if not norm or not number:
                    continue

                for stat, names in aliases.items():
                    if norm in names:
                        found[stat] = number
                        break

            if {"ap", "aap", "dp"}.issubset(found):
                ap = int(found["ap"])
                aap = int(found["aap"])
                dp = int(found["dp"])
                gs = int(found.get("gs") or ((ap + aap) // 2 + dp))
                return cls._stats_from_sequence(
                    [str(ap), str(aap), str(dp), str(gs)]
                )
            return None

        stack = [payload]
        visited = 0

        while stack and visited < 25_000:
            current = stack.pop()
            visited += 1

            if isinstance(current, dict):
                stats = direct_dict(current)
                if stats:
                    return stats
                stack.extend(current.values())

            elif isinstance(current, list):
                stats = labelled_list(current)
                if stats:
                    return stats
                stack.extend(current)

            elif isinstance(current, str):
                text = current.strip()
                if (
                    len(text) < 200_000
                    and text[:1] in ("{", "[")
                ):
                    try:
                        import json
                        stack.append(json.loads(text))
                    except Exception:
                        pass

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

    async def _install_playwright_chromium(self) -> bool:
        """Встановлює Chromium у runtime Render, якщо cache зник після deploy."""
        async with self.browser_install_lock:
            try:
                from playwright.async_api import async_playwright

                async with async_playwright() as playwright:
                    executable = playwright.chromium.executable_path
                    if executable and os.path.exists(executable):
                        return True
            except Exception:
                pass

            print("[GEAR] Chromium відсутній у runtime. Встановлюю Playwright Chromium...")

            def _install():
                return subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "playwright",
                        "install",
                        "chromium",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=360,
                    check=False,
                )

            try:
                result = await asyncio.to_thread(_install)
            except Exception as error:
                self.last_scrape_error = (
                    "Не вдалося встановити Chromium у runtime: "
                    f"{type(error).__name__}: {error}"
                )
                print(f"[GEAR][ERROR] {self.last_scrape_error}")
                return False

            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                self.last_scrape_error = (
                    "Playwright install chromium завершився помилкою: "
                    f"{detail[-1500:]}"
                )
                print(f"[GEAR][ERROR] {self.last_scrape_error}")
                return False

            print("[GEAR] Playwright Chromium встановлено у runtime")
            return True

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
                        "--disable-background-networking",
                        "--disable-component-update",
                        "--disable-default-apps",
                        "--disable-sync",
                        "--metrics-recording-only",
                        "--mute-audio",
                        "--no-first-run",
                        "--disable-blink-features=AutomationControlled",
                    ],
                }

                system_browser = self._system_chromium_path()
                playwright_browser = playwright.chromium.executable_path

                if system_browser:
                    launch_kwargs["executable_path"] = system_browser
                elif playwright_browser and os.path.exists(playwright_browser):
                    launch_kwargs["executable_path"] = playwright_browser

                try:
                    browser = await playwright.chromium.launch(**launch_kwargs)
                except Exception as launch_error:
                    launch_text = str(launch_error)
                    if (
                        "Executable doesn't exist" not in launch_text
                        and "executable doesn't exist" not in launch_text.lower()
                    ):
                        raise

                    installed = await self._install_playwright_chromium()
                    if not installed:
                        raise RuntimeError(
                            self.last_scrape_error
                            or "Chromium не вдалося встановити"
                        ) from launch_error

                    # Після runtime-install Playwright уже бачить свій Chromium.
                    browser = await playwright.chromium.launch(
                        headless=True,
                        args=launch_kwargs["args"],
                    )

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

                async def block_heavy_resources(route, request):
                    if request.resource_type in {"image", "media", "font"}:
                        await route.abort()
                    else:
                        await route.continue_()

                await context.route("**/*", block_heavy_resources)

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

                api_capture = {
                    "stats": None,
                    "url": None,
                    "json_count": 0,
                }
                response_errors = []
                capture_tasks = set()

                async def capture_response(response):
                    try:
                        content_type = (
                            response.headers.get("content-type", "")
                            .casefold()
                        )
                        if response.status >= 400 and "garmoth" in response.url:
                            if len(response_errors) < 20:
                                response_errors.append(
                                    f"{response.status} {response.url}"
                                )

                        if (
                            api_capture["stats"] is None
                            and (
                                "json" in content_type
                                or "/api/" in response.url
                            )
                        ):
                            try:
                                payload = await response.json()
                            except Exception:
                                return

                            api_capture["json_count"] += 1
                            stats = self._stats_from_json(payload)
                            if stats:
                                api_capture["stats"] = stats
                                api_capture["url"] = response.url

                            # Не зберігаємо JSON у пам'яті: payload може бути
                            # дуже великим на Garmoth.
                            del payload
                    except Exception:
                        return

                def schedule_capture(response):
                    task = asyncio.create_task(capture_response(response))
                    capture_tasks.add(task)
                    task.add_done_callback(capture_tasks.discard)

                page.on("response", schedule_capture)

                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=90_000,
                )

                # Не виходимо лише через появу оболонки Gear Builder.
                # Чекаємо сам build/API максимум 35 секунд.
                for _ in range(35):
                    await page.wait_for_timeout(1_000)

                    legacy_values_now = await page.locator(
                        ".grid-cols-4 .text-2xl"
                    ).all_inner_texts()
                    if self._stats_from_sequence(legacy_values_now):
                        break

                    body_now = await page.locator("body").inner_text()
                    if self._stats_from_labelled_text(body_now):
                        break

                    if api_capture["stats"]:
                        break

                if capture_tasks:
                    await asyncio.gather(
                        *list(capture_tasks),
                        return_exceptions=True,
                    )

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

                # 1. Дані з API/JSON Garmoth — найстабільніше після редизайну.
                if api_capture["stats"]:
                    print(
                        "[GEAR] Stats from Garmoth JSON: "
                        f"{api_capture['url']}"
                    )
                    return api_capture["stats"]

                # 2. Старий layout.
                legacy_values = await page.locator(
                    ".grid-cols-4 .text-2xl"
                ).all_inner_texts()
                stats = self._stats_from_sequence(legacy_values)
                if stats:
                    return stats

                # 3. Текст сторінки.
                stats = self._stats_from_labelled_text(body_text)
                if stats:
                    return stats

                # 4. Новий layout може тримати цифри в input/value/aria,
                # а не в textContent. Беремо контекст елементів AP/AAP/DP/GS.
                stat_contexts = await page.locator("body *").evaluate_all(
                    """
                    (elements) => {
                        const labels = new Set([
                            'AP', 'AAP', 'DP', 'GS',
                            'ATTACK POWER',
                            'AWAKENING AP',
                            'DEFENSE POWER',
                            'DEFENCE POWER',
                            'GEAR SCORE',
                            'GEARSCORE'
                        ]);
                        const out = [];
                        for (const el of elements) {
                            const own = (el.textContent || '').trim().toUpperCase();
                            if (!labels.has(own)) continue;

                            let node = el;
                            for (let depth = 0; depth < 4 && node; depth++) {
                                const inputs = Array.from(
                                    node.querySelectorAll('input')
                                ).map((input) => input.value || '').join(' ');
                                const attrs = [
                                    node.getAttribute('aria-label') || '',
                                    node.getAttribute('title') || '',
                                    node.getAttribute('data-value') || '',
                                    node.getAttribute('value') || ''
                                ].join(' ');
                                out.push(
                                    [
                                        node.innerText || '',
                                        inputs,
                                        attrs
                                    ].join(' ')
                                );
                                node = node.parentElement;
                            }
                        }
                        return out.slice(0, 100);
                    }
                    """
                )
                stats = self._stats_from_labelled_text(
                    "\n".join(stat_contexts)
                )
                if stats:
                    return stats

                # 5. Nuxt/JSON script payloads.
                script_texts = await page.locator(
                    "script[type='application/json'], "
                    "script#__NUXT_DATA__, script[id*='nuxt']"
                ).all_text_contents()
                for script_text in script_texts:
                    stats = self._stats_from_json(script_text)
                    if stats:
                        return stats

                # 6. Останній DOM-фолбек.
                leaf_values = await page.locator("body *").evaluate_all(
                    """
                    (elements) => elements
                        .flatMap((el) => {
                            const values = [];
                            if (
                                el.children.length === 0 &&
                                /^\\s*\\d{2,4}\\s*$/.test(
                                    el.textContent || ''
                                )
                            ) {
                                values.push(
                                    (el.textContent || '').trim()
                                );
                            }
                            if (
                                el instanceof HTMLInputElement &&
                                /^\\s*\\d{2,4}\\s*$/.test(
                                    el.value || ''
                                )
                            ) {
                                values.push(el.value.trim());
                            }
                            return values;
                        })
                    """
                )
                stats = self._stats_from_sequence(leaf_values)
                if stats:
                    return stats

                api_error_sample = "; ".join(response_errors[-5:])
                raise RuntimeError(
                    "профіль відкрився, але build-стати не отримані; "
                    f"title={title!r}; "
                    f"JSON={api_capture['json_count']}; "
                    f"API errors={api_error_sample or 'немає'}"
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

        # history() повертає нові повідомлення першими. Зберігаємо лише
        # останнє Garmoth-посилання кожного користувача, а не 500 Message
        # об'єктів у RAM.
        latest_profiles = {}
        async for message in channel.history(limit=500):
            link = self._extract_garmoth_link(message.content)
            if not link or message.author.id in latest_profiles:
                continue
            latest_profiles[message.author.id] = (
                message.author,
                link,
            )

        profiles = list(latest_profiles.values())
        profiles.reverse()
        del latest_profiles

        try:
            for author, link in profiles:
                if self.collect_stop_requested:
                    stopped = True
                    break

                author_name = author.display_name
                count      += 1
                stats       = await self.fetch_stats_selenium(link)
                gc.collect()
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
                        name="🌟 Gearscore",
                        value=f"**{stats['gs']}**",
                        inline=True,
                    )
                    gear_data[str(author.id)] = (
                        self._gear_entry(
                            author,
                            link,
                            stats,
                        )
                    )
                else:
                    embed.add_field(
                        name="Статус",
                        value="❌ Не вдалося зчитати (Private?)",
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
                    icon_url=author.display_avatar.url,
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
