# -*- coding: utf-8 -*-
# MASTER SPEC: /BDOGEAR_MAIN.md
# Read BDOGEAR_MAIN.md before changing this cog.
# _bdogear_cog.py — MongoDB версія

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import gc
import ctypes
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data.gear_store import count_members, load_gear, upsert_member_gear
from data.mongo_store import get_database
from pymongo.errors import DuplicateKeyError

# ─── Cog ──────────────────────────────────────────────────────────────────────

class BdoGear(commands.Cog):
    PARSER_VERSION = "selenium-v2"

    def __init__(self, bot):
        self.bot              = bot
        self.delays           = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]
        self.target_channel_id = 1358443998603120824
        self.update_lock = asyncio.Lock()
        self.collect_running = False
        self.collect_stop_requested = False
        self.collect_stop_event = asyncio.Event()
        self.collect_owner_id = None
        self.collect_task: asyncio.Task | None = None
        self.last_scrape_error: str | None = None
        self.browser_install_lock = asyncio.Lock()

    async def _claim_interaction(
        self,
        interaction: discord.Interaction,
        action: str,
    ) -> bool:
        """Один Discord interaction виконується лише одним інстансом бота."""
        interaction_id = str(interaction.id)

        def claim() -> bool:
            try:
                get_database()["gear_interaction_claims"].insert_one({
                    "_id": interaction_id,
                    "action": action,
                    "user_id": interaction.user.id,
                    "guild_id": getattr(interaction.guild, "id", None),
                    "created_at": datetime.now(timezone.utc),
                })
                return True
            except DuplicateKeyError:
                return False

        try:
            claimed = await asyncio.to_thread(claim)
        except Exception as error:
            print(
                "[GEAR][CLAIM][WARN] "
                f"{type(error).__name__}: {error}"
            )
            return True

        if not claimed:
            print(
                f"[GEAR][CLAIM] duplicate skipped "
                f"interaction={interaction_id} action={action}"
            )
        return claimed

    async def _acquire_collect_job(
        self,
        owner_id: int,
        token: str,
    ) -> bool:
        """Глобальний lock: лише один /collect на всі Render-інстанси."""
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(hours=2)
        instance_id = (
            os.getenv("RENDER_INSTANCE_ID")
            or os.getenv("HOSTNAME")
            or "unknown"
        )

        def acquire() -> bool:
            jobs = get_database()["gear_jobs"]
            jobs.delete_one({
                "_id": "mass_collect",
                "updated_at": {"$lt": stale_before},
            })
            try:
                jobs.insert_one({
                    "_id": "mass_collect",
                    "token": token,
                    "owner_id": owner_id,
                    "instance_id": instance_id,
                    "started_at": now,
                    "updated_at": now,
                    "stop_requested": False,
                    "processed": 0,
                })
                return True
            except DuplicateKeyError:
                return False

        return await asyncio.to_thread(acquire)

    async def _get_collect_job(self) -> dict | None:
        return await asyncio.to_thread(
            lambda: get_database()["gear_jobs"].find_one(
                {"_id": "mass_collect"}
            )
        )

    async def _heartbeat_collect_job(
        self,
        token: str,
        *,
        processed: int,
    ) -> bool:
        def heartbeat() -> bool:
            result = get_database()["gear_jobs"].update_one(
                {
                    "_id": "mass_collect",
                    "token": token,
                },
                {
                    "$set": {
                        "updated_at": datetime.now(timezone.utc),
                        "processed": processed,
                    }
                },
            )
            return bool(result.matched_count)

        return await asyncio.to_thread(heartbeat)

    async def _collect_should_stop(self, token: str) -> bool:
        if self.collect_stop_requested or self.collect_stop_event.is_set():
            return True

        def read() -> bool:
            document = get_database()["gear_jobs"].find_one(
                {
                    "_id": "mass_collect",
                    "token": token,
                },
                {"stop_requested": 1},
            )
            if not document:
                return True
            return bool(document.get("stop_requested"))

        try:
            return await asyncio.to_thread(read)
        except Exception as error:
            print(
                "[GEAR][JOB][WARN] stop check: "
                f"{type(error).__name__}: {error}"
            )
            return False

    async def _request_collect_stop(self) -> dict | None:
        def request() -> dict | None:
            jobs = get_database()["gear_jobs"]
            document = jobs.find_one({"_id": "mass_collect"})
            if not document:
                return None
            jobs.update_one(
                {"_id": "mass_collect"},
                {
                    "$set": {
                        "stop_requested": True,
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
            )
            return document

        return await asyncio.to_thread(request)

    async def _release_collect_job(self, token: str) -> None:
        def release() -> None:
            get_database()["gear_jobs"].delete_one({
                "_id": "mass_collect",
                "token": token,
            })

        try:
            await asyncio.to_thread(release)
        except Exception as error:
            print(
                "[GEAR][JOB][WARN] release: "
                f"{type(error).__name__}: {error}"
            )

    async def _wait_collect_delay(
        self,
        seconds: int,
        token: str,
    ) -> bool:
        """True якщо під час паузи попросили зупинити збір."""
        deadline = asyncio.get_running_loop().time() + seconds
        while True:
            if await self._collect_should_stop(token):
                return True

            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False

            try:
                await asyncio.wait_for(
                    self.collect_stop_event.wait(),
                    timeout=min(2.0, remaining),
                )
                return True
            except asyncio.TimeoutError:
                pass

    async def _safe_private_result(
        self,
        interaction: discord.Interaction,
        content: str,
        *,
        interaction_alive: bool,
    ) -> None:
        """Ephemeral якщо interaction живий, інакше DM."""
        if interaction_alive:
            try:
                await interaction.followup.send(
                    content,
                    ephemeral=True,
                )
                return
            except (discord.NotFound, discord.HTTPException):
                pass

        try:
            await interaction.user.send(content)
        except (discord.Forbidden, discord.HTTPException):
            channel = interaction.channel
            if channel is not None:
                await channel.send(
                    f"{interaction.user.mention}\n{content}"
                )

    @staticmethod
    def _release_process_memory() -> None:
        """Повертає звільнену Python/glibc пам'ять ОС після Chromium."""
        gc.collect()
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except Exception:
            pass

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

    @staticmethod
    def _playwright_chromium_binary() -> str | None:
        """Шукає вже завантажений Playwright Chromium без запуску Playwright."""
        roots = [
            Path.home() / ".cache" / "ms-playwright",
            Path("/opt/render/.cache/ms-playwright"),
        ]
        patterns = (
            "chromium-*/chrome-linux64/chrome",
            "chromium-*/chrome-linux/chrome",
            "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
        )

        for root in roots:
            if not root.exists():
                continue
            for pattern in patterns:
                matches = sorted(root.glob(pattern), reverse=True)
                for match in matches:
                    if match.is_file():
                        return str(match)
        return None

    @classmethod
    def _selenium_options(cls):
        from selenium.webdriver.chrome.options import Options

        options = Options()
        # Garmoth/Nuxt може тримати навігацію відкритою дуже довго.
        # "none" повертає driver.get() одразу, далі ми самі чекаємо JSON/DOM.
        options.page_load_strategy = "none"
        options.set_capability(
            "goog:loggingPrefs",
            {"performance": "ALL"},
        )

        for argument in (
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-sync",
            "--disable-software-rasterizer",
            "--metrics-recording-only",
            "--mute-audio",
            "--no-first-run",
            "--window-size=900,700",
            "--renderer-process-limit=1",
            "--js-flags=--max-old-space-size=128",
            "--disable-blink-features=AutomationControlled",
        ):
            options.add_argument(argument)

        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/152.0.0.0 Safari/537.36"
        )
        options.add_experimental_option(
            "prefs",
            {
                "profile.managed_default_content_settings.images": 2,
                "profile.default_content_setting_values.notifications": 2,
                "profile.default_content_setting_values.geolocation": 2,
            },
        )

        browser_binary = (
            cls._system_chromium_path()
            or cls._playwright_chromium_binary()
        )
        if browser_binary:
            options.binary_location = browser_binary

        return options

    @classmethod
    def _install_runtime_chromium_sync(cls) -> str | None:
        """Докачує Chromium у runtime і повертає шлях до binary."""
        try:
            result = subprocess.run(
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
            if result.returncode != 0:
                print(
                    "[GEAR][ERROR] Runtime Chromium install: "
                    + (result.stderr or result.stdout or "")[-1500:]
                )
                return None
        except Exception as error:
            print(
                "[GEAR][ERROR] Runtime Chromium install: "
                f"{type(error).__name__}: {error}"
            )
            return None

        return cls._playwright_chromium_binary()

    @classmethod
    def _open_selenium_driver(cls):
        from selenium import webdriver

        options = cls._selenium_options()

        try:
            return webdriver.Chrome(options=options)
        except Exception as first_error:
            print(
                "[GEAR] Selenium Manager first launch failed: "
                f"{type(first_error).__name__}: {first_error}"
            )

        browser_binary = cls._install_runtime_chromium_sync()
        if browser_binary:
            options = cls._selenium_options()
            options.binary_location = browser_binary
            try:
                return webdriver.Chrome(options=options)
            except Exception as second_error:
                print(
                    "[GEAR] Selenium launch after Chromium install failed: "
                    f"{type(second_error).__name__}: {second_error}"
                )

        # Останній fallback для середовищ, де Selenium Manager не знайшов driver.
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        return webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options,
        )

    def _fetch_stats_selenium_sync(self, url: str) -> dict | None:
        """Синхронно читає Garmoth Selenium-ом і переживає SPA-навігації."""
        from selenium.common.exceptions import (
            JavascriptException,
            StaleElementReferenceException,
            TimeoutException,
            WebDriverException,
        )
        from selenium.webdriver.common.by import By

        driver = None
        last_error = None
        self.last_scrape_error = None

        try:
            driver = self._open_selenium_driver()
            driver.set_page_load_timeout(15)

            try:
                driver.execute_cdp_cmd(
                    "Network.enable",
                    {
                        "maxTotalBufferSize": 5_000_000,
                        "maxResourceBufferSize": 1_000_000,
                    },
                )
            except Exception:
                pass

            # page_load_strategy="none": не чекаємо Nuxt navigation.
            driver.get(url)

            deadline = time.time() + 45
            seen_api_urls = []

            while time.time() < deadline:
                try:
                    # 1. Найперше читаємо JSON/XHR із Network performance log.
                    # Це не залежить від того, скільки разів Nuxt перенавігує DOM.
                    try:
                        performance_entries = driver.get_log("performance")
                    except Exception:
                        performance_entries = []

                    for raw_entry in performance_entries:
                        try:
                            outer = json.loads(raw_entry.get("message", "{}"))
                            message = outer.get("message", {})
                            if message.get("method") != "Network.responseReceived":
                                continue

                            params = message.get("params", {})
                            response = params.get("response", {})
                            response_url = str(response.get("url", ""))
                            mime_type = str(
                                response.get("mimeType", "")
                            ).casefold()
                            request_id = params.get("requestId")

                            interesting = (
                                "api.garmoth.com" in response_url
                                or "/api/" in response_url
                                or "character" in response_url.casefold()
                                or "build" in response_url.casefold()
                            )
                            if not interesting:
                                continue

                            if (
                                response_url
                                and response_url not in seen_api_urls
                                and len(seen_api_urls) < 30
                            ):
                                seen_api_urls.append(response_url)

                            if not request_id:
                                continue
                            if (
                                "json" not in mime_type
                                and "/api/" not in response_url
                                and "api.garmoth.com" not in response_url
                            ):
                                continue

                            try:
                                body_result = driver.execute_cdp_cmd(
                                    "Network.getResponseBody",
                                    {"requestId": request_id},
                                )
                            except Exception:
                                continue

                            body = body_result.get("body", "")
                            if not body:
                                continue

                            try:
                                payload = json.loads(body)
                            except Exception:
                                payload = body

                            stats = self._stats_from_json(payload)
                            if stats:
                                print(
                                    "[GEAR][SELENIUM] stats from network "
                                    f"url={response_url}"
                                )
                                return stats
                        except Exception:
                            continue

                    title = driver.title or ""

                    # 1. Старий Garmoth layout.
                    legacy_values = [
                        element.text.strip()
                        for element in driver.find_elements(
                            By.CSS_SELECTOR,
                            ".grid-cols-4 .text-2xl",
                        )
                        if element.text.strip()
                    ]
                    stats = self._stats_from_sequence(legacy_values)
                    if stats:
                        return stats

                    # 2. Видимий текст нового layout.
                    body_text = driver.find_element(By.TAG_NAME, "body").text
                    stats = self._stats_from_labelled_text(body_text)
                    if stats:
                        return stats

                    # 3. Значення біля AP/AAP/DP/GS, включно з input/value/aria.
                    contexts = driver.execute_script(
                        """
                        const labels = new Set([
                            'AP', 'AAP', 'DP', 'GS',
                            'ATTACK POWER',
                            'AWAKENING AP',
                            'AWAKENING ATTACK POWER',
                            'DEFENSE POWER',
                            'DEFENCE POWER',
                            'GEAR SCORE',
                            'GEARSCORE'
                        ]);
                        const out = [];
                        for (const el of document.querySelectorAll('body *')) {
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
                                out.push([
                                    node.innerText || '',
                                    inputs,
                                    attrs
                                ].join(' '));
                                node = node.parentElement;
                            }
                        }
                        return out.slice(0, 100);
                        """
                    ) or []
                    stats = self._stats_from_labelled_text(
                        "\n".join(str(value) for value in contexts)
                    )
                    if stats:
                        return stats

                    # 4. Nuxt/application JSON.
                    script_texts = driver.execute_script(
                        """
                        return Array.from(document.querySelectorAll(
                            "script[type='application/json'], " +
                            "script#__NUXT_DATA__, script[id*='nuxt']"
                        )).map((el) => el.textContent || '').filter(Boolean);
                        """
                    ) or []

                    for script_text in script_texts[:20]:
                        try:
                            payload = json.loads(script_text)
                        except Exception:
                            payload = script_text
                        stats = self._stats_from_json(payload)
                        if stats:
                            return stats

                    # 5. localStorage/sessionStorage іноді містять поточний build.
                    storage_values = driver.execute_script(
                        """
                        const out = [];
                        for (const store of [window.localStorage, window.sessionStorage]) {
                            if (!store) continue;
                            for (let i = 0; i < store.length; i++) {
                                const key = store.key(i);
                                const value = store.getItem(key);
                                if (value && value.length < 250000) out.push(value);
                            }
                        }
                        return out.slice(0, 60);
                        """
                    ) or []

                    for value in storage_values:
                        stats = self._stats_from_json(value)
                        if stats:
                            return stats

                    # 6. Останній DOM fallback: усі чисті числові leaf/input values.
                    numeric_values = driver.execute_script(
                        """
                        const out = [];
                        for (const el of document.querySelectorAll('body *')) {
                            if (
                                el.children.length === 0 &&
                                /^\\s*\\d{2,4}\\s*$/.test(el.textContent || '')
                            ) {
                                out.push((el.textContent || '').trim());
                            }
                            if (
                                el instanceof HTMLInputElement &&
                                /^\\s*\\d{2,4}\\s*$/.test(el.value || '')
                            ) {
                                out.push(el.value.trim());
                            }
                        }
                        return out.slice(0, 500);
                        """
                    ) or []
                    stats = self._stats_from_sequence(numeric_values)
                    if stats:
                        return stats

                    if any(
                        marker in body_text.casefold()
                        for marker in (
                            "just a moment",
                            "verify you are human",
                            "checking your browser",
                        )
                    ):
                        last_error = RuntimeError(
                            "Garmoth показав Cloudflare verification"
                        )

                except (
                    StaleElementReferenceException,
                    JavascriptException,
                    WebDriverException,
                ) as error:
                    # Garmoth SPA може навігувати кілька разів після відкриття.
                    last_error = error

                time.sleep(1)

            try:
                final_title = driver.title
                final_url = driver.current_url
            except Exception:
                final_title = "?"
                final_url = url

            detail = (
                f"{type(last_error).__name__}: {last_error}"
                if last_error
                else "AP/AAP/DP/GS не знайдені"
            )
            api_sample = " | ".join(seen_api_urls[-8:])
            self.last_scrape_error = (
                "Selenium: профіль відкрився, але стати не зчитані; "
                f"title={final_title!r}; url={final_url}; "
                f"{detail}; network={api_sample or 'немає'}"
            )
            print(f"[GEAR][ERROR] {self.last_scrape_error}")
            return None

        except Exception as error:
            self.last_scrape_error = (
                f"Selenium {type(error).__name__}: {error}"
            )
            print(
                f"[GEAR][ERROR] Garmoth {url}: "
                f"{self.last_scrape_error}"
            )
            return None
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            self._release_process_memory()

    async def fetch_stats_selenium(self, url: str) -> dict | None:
        """Не блокує Discord під час Selenium-парсингу."""
        self.last_scrape_error = None
        print(
            f"[GEAR][SELENIUM] start parser={self.PARSER_VERSION} "
            f"url={url}"
        )

        stats = await asyncio.to_thread(
            self._fetch_stats_selenium_sync,
            url,
        )

        if stats:
            print(
                f"[GEAR][SELENIUM] success parser={self.PARSER_VERSION} "
                f"AP={stats.get('ap')} AAP={stats.get('aap')} "
                f"DP={stats.get('dp')} GS={stats.get('gs')}"
            )
            return stats

        if not self.last_scrape_error:
            self.last_scrape_error = "Selenium повернув None без діагностики"

        print(
            f"[GEAR][SELENIUM] failed parser={self.PARSER_VERSION}: "
            f"{self.last_scrape_error}"
        )
        return None

    async def update_member_gear(
        self,
        member,
        link: str,
    ) -> dict | None:
        """Зчитує Garmoth і атомарно зберігає одного Discord user."""
        async with self.update_lock:
            stats = await self.fetch_stats_selenium(link)
            if not stats:
                return None

            entry = self._gear_entry(
                member,
                link,
                stats,
            )
            saved = await asyncio.to_thread(
                upsert_member_gear,
                member.id,
                entry,
            )
            if not saved:
                self.last_scrape_error = (
                    "MongoDB: Garmoth зчитано, але не вдалося "
                    "зберегти гір користувача"
                )
                return None

            return stats

    async def run_mass_collect(
        self,
        channel: discord.TextChannel,
        status_channel,
        *,
        token: str,
    ) -> None:
        """Фонова масова обробка. Interaction тут більше не використовується."""
        count = 0
        stopped = False

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
                if await self._collect_should_stop(token):
                    stopped = True
                    break

                author_name = author.display_name
                count += 1
                stats = await self.fetch_stats_selenium(link)
                self._release_process_memory()
                unix_time = int(time.time())
                wait_time = self.delays[
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
                    entry = self._gear_entry(
                        author,
                        link,
                        stats,
                    )
                    saved = await asyncio.to_thread(
                        upsert_member_gear,
                        author.id,
                        entry,
                    )

                    if saved:
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
                    else:
                        embed.add_field(
                            name="Статус",
                            value="❌ Зчитано, але не збережено в MongoDB",
                            inline=False,
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

                await status_channel.send(embed=embed)
                await self._heartbeat_collect_job(
                    token,
                    processed=count,
                )

                if await self._wait_collect_delay(wait_time, token):
                    stopped = True
                    break

        except Exception as error:
            print(
                f"[GEAR][COLLECT][ERROR] "
                f"{type(error).__name__}: {error}"
            )
            try:
                await status_channel.send(
                    "❌ **Збір аварійно зупинено.** "
                    f"Причина: {type(error).__name__}: {str(error)[:900]}"
                )
            except Exception:
                pass
        finally:
            await self._release_collect_job(token)
            self.collect_running = False
            self.collect_stop_requested = False
            self.collect_stop_event.clear()
            self.collect_owner_id = None
            self.collect_task = None
            self._release_process_memory()

        players_count = await asyncio.to_thread(count_members)
        if stopped:
            await status_channel.send(
                f"⏹️ **Збір зупинено.** Оброблено профілів: "
                f"{count}. У базі гравців: {players_count}"
            )
        else:
            await status_channel.send(
                f"✅ **Парсинг завершено!** В базі тепер гравців: "
                f"{players_count}"
            )

    # ── Slash команди ────────────────────────────────────────────────────────

    @app_commands.command(name="collect", description="Масовий збір статсів гільдії")
    async def collect(self, interaction: discord.Interaction):
        interaction_alive = True
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            interaction_alive = False

        if not await self._claim_interaction(interaction, "collect"):
            return

        token = str(interaction.id)
        acquired = await self._acquire_collect_job(
            interaction.user.id,
            token,
        )
        if not acquired:
            await self._safe_private_result(
                interaction,
                "⚠️ Збір уже працює. Для зупинки використай /collect_stop.",
                interaction_alive=interaction_alive,
            )
            return

        try:
            channel = (
                self.bot.get_channel(self.target_channel_id)
                or await self.bot.fetch_channel(
                    self.target_channel_id
                )
            )
        except Exception as error:
            await self._release_collect_job(token)
            await self._safe_private_result(
                interaction,
                f"❌ Не можу відкрити канал гіру: {type(error).__name__}: {error}",
                interaction_alive=interaction_alive,
            )
            return

        self.collect_running = True
        self.collect_stop_requested = False
        self.collect_stop_event.clear()
        self.collect_owner_id = interaction.user.id

        await (interaction.channel or channel).send(
            f"⚙️ **Запуск...** Отримую дані з #{channel.name}"
        )

        self.collect_task = asyncio.create_task(
            self.run_mass_collect(
                channel,
                interaction.channel or channel,
                token=token,
            )
        )

        await self._safe_private_result(
            interaction,
            "✅ Збір запущено у фоні. /collect_stop зупинить його після поточного профілю.",
            interaction_alive=interaction_alive,
        )

    @app_commands.command(
        name="collect_stop",
        description="Безпечно зупинити поточний збір Garmoth",
    )
    async def collect_stop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        job = await self._get_collect_job()
        if not job:
            await interaction.followup.send(
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
            interaction.user.id == job.get("owner_id")
            or bool(
                permissions
                and permissions.manage_guild
            )
        )
        if not can_stop:
            await interaction.followup.send(
                "❌ Зупинити збір може той, хто його запустив, "
                "або адміністратор.",
                ephemeral=True,
            )
            return

        await self._request_collect_stop()
        self.collect_stop_requested = True
        self.collect_stop_event.set()

        await interaction.followup.send(
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
        interaction_alive = True
        try:
            await interaction.response.defer(ephemeral=True)
        except (discord.NotFound, discord.HTTPException):
            interaction_alive = False
            print(
                f"[GEAR][CMD] interaction expired before defer "
                f"id={interaction.id}; continuing via DM"
            )

        if not await self._claim_interaction(interaction, "gear_update"):
            return

        print(
            f"[GEAR][CMD] gear_update parser={self.PARSER_VERSION} "
            f"user={interaction.user.id} url={посилання} "
            f"interaction_alive={interaction_alive}"
        )

        if "garmoth.com/character/" not in посилання:
            await self._safe_private_result(
                interaction,
                "❌ Невірне посилання. Потрібно garmoth.com/character/...",
                interaction_alive=interaction_alive,
            )
            return

        stats = await self.update_member_gear(
            interaction.user,
            посилання,
        )
        if not stats:
            detail = self.last_scrape_error or "невідома помилка"
            await self._safe_private_result(
                interaction,
                (
                    "❌ Не вдалося зчитати Garmoth.\n"
                    f"Парсер: **{self.PARSER_VERSION}**\n"
                    f"Причина: {detail[:1200]}"
                ),
                interaction_alive=interaction_alive,
            )
            return

        await self._safe_private_result(
            interaction,
            (
                "✅ Твої дані оновлено!\n"
                f"⚔️ AP/AAP: {stats['ap']}/{stats['aap']} | "
                f"🛡️ DP: {stats['dp']} | 🌟 GS: **{stats['gs']}**"
            ),
            interaction_alive=interaction_alive,
        )



async def setup(bot):
    await bot.add_cog(BdoGear(bot))
    print("[COG] BdoGear завантажено")
