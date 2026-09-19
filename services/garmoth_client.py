# -*- coding: utf-8 -*-
"""Garmoth client for BDO gear parsing.

MASTER SPEC: /BDOGEAR_MAIN.md

The Discord cog should not know how Garmoth is fetched.
This client tries a light HTTP path first, then Selenium as a fallback.
"""

from __future__ import annotations

import asyncio
import ctypes
import gc
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp
from bs4 import BeautifulSoup


@dataclass(slots=True)
class GarmothResult:
    ok: bool
    stats: dict[str, str] | None = None
    error: str | None = None
    source: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)


class GarmothClient:
    VERSION = "garmoth-client-v2"

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/152.0.0.0 Safari/537.36"
    )

    @staticmethod
    def release_process_memory() -> None:
        gc.collect()
        try:
            libc = ctypes.CDLL("libc.so.6")
            libc.malloc_trim(0)
        except Exception:
            pass

    @staticmethod
    def clean_stat_value(value) -> str | None:
        match = re.search(r"\b(\d{2,4})\b", str(value or ""))
        return match.group(1) if match else None

    @classmethod
    def stats_from_sequence(cls, values) -> dict[str, str] | None:
        numbers: list[int] = []

        for value in values or []:
            cleaned = cls.clean_stat_value(value)
            if not cleaned:
                continue
            numbers.append(int(cleaned))

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
    def stats_from_labelled_text(
        cls,
        body_text: str,
    ) -> dict[str, str] | None:
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
            "dp": (
                "DP",
                "DEFENSE POWER",
                "DEFENCE POWER",
            ),
            "gs": (
                "GS",
                "GEAR SCORE",
                "GEARSCORE",
            ),
        }

        found: dict[str, str] = {}

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
                    value = cls.clean_stat_value(candidate)
                    if value:
                        found[key] = value
                        break

                if key in found:
                    break

        if not {"ap", "aap", "dp"}.issubset(found):
            return None

        ap = int(found["ap"])
        aap = int(found["aap"])
        dp = int(found["dp"])
        gs = int(
            found.get("gs")
            or ((ap + aap) // 2 + dp)
        )

        return cls.stats_from_sequence(
            [str(ap), str(aap), str(dp), str(gs)]
        )

    @staticmethod
    def normalise_stat_key(value) -> str:
        return re.sub(
            r"[^a-z0-9]",
            "",
            str(value or "").casefold(),
        )

    @classmethod
    def stats_from_json(cls, payload) -> dict[str, str] | None:
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
                return cls.clean_stat_value(value)
            return None

        def candidate_dict(value):
            if not isinstance(value, dict):
                return None

            found = {}

            for raw_key, raw_value in value.items():
                key = cls.normalise_stat_key(raw_key)
                number = scalar(raw_value)

                if not number:
                    continue

                for stat, names in aliases.items():
                    if key in names:
                        found[stat] = number
                        break

            if not {"ap", "aap", "dp"}.issubset(found):
                return None

            ap = int(found["ap"])
            aap = int(found["aap"])
            dp = int(found["dp"])
            gs = int(
                found.get("gs")
                or ((ap + aap) // 2 + dp)
            )

            return cls.stats_from_sequence(
                [str(ap), str(aap), str(dp), str(gs)]
            )

        def candidate_list(value):
            if not isinstance(value, list):
                return None

            found = {}

            for item in value:
                if not isinstance(item, dict):
                    continue

                label = None
                number = None

                for key in (
                    "name",
                    "label",
                    "key",
                    "title",
                    "type",
                    "stat",
                ):
                    if key in item:
                        label = item.get(key)
                        break

                for key in (
                    "value",
                    "val",
                    "amount",
                    "total",
                    "number",
                ):
                    if key in item:
                        number = scalar(item.get(key))
                        break

                norm = cls.normalise_stat_key(label)
                if not norm or not number:
                    continue

                for stat, names in aliases.items():
                    if norm in names:
                        found[stat] = number
                        break

            if not {"ap", "aap", "dp"}.issubset(found):
                return None

            ap = int(found["ap"])
            aap = int(found["aap"])
            dp = int(found["dp"])
            gs = int(
                found.get("gs")
                or ((ap + aap) // 2 + dp)
            )

            return cls.stats_from_sequence(
                [str(ap), str(aap), str(dp), str(gs)]
            )

        stack = [payload]
        visited = 0

        while stack and visited < 25_000:
            current = stack.pop()
            visited += 1

            if isinstance(current, dict):
                stats = candidate_dict(current)
                if stats:
                    return stats
                stack.extend(current.values())

            elif isinstance(current, list):
                stats = candidate_list(current)
                if stats:
                    return stats
                stack.extend(current)

            elif isinstance(current, str):
                text = current.strip()
                if (
                    len(text) < 250_000
                    and text[:1] in ("{", "[")
                ):
                    try:
                        stack.append(json.loads(text))
                    except Exception:
                        pass

        return None

    async def _try_http(self, url: str) -> GarmothResult:
        timeout = aiohttp.ClientTimeout(total=20)

        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/json;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with aiohttp.ClientSession(
                timeout=timeout,
                headers=headers,
            ) as session:
                async with session.get(
                    url,
                    allow_redirects=True,
                ) as response:
                    text = await response.text(
                        errors="replace"
                    )
                    final_url = str(response.url)
                    status = response.status

            soup = BeautifulSoup(text, "html.parser")

            page_text = soup.get_text("\n", strip=True)
            stats = self.stats_from_labelled_text(page_text)
            if stats:
                return GarmothResult(
                    ok=True,
                    stats=stats,
                    source="http-html",
                    diagnostics={
                        "status": status,
                        "final_url": final_url,
                    },
                )

            script_candidates = []

            for script in soup.find_all("script"):
                script_type = (
                    script.get("type")
                    or ""
                ).casefold()
                script_id = (
                    script.get("id")
                    or ""
                ).casefold()

                if (
                    "json" in script_type
                    or "nuxt" in script_id
                    or "__nuxt" in str(script)
                ):
                    raw = script.string or script.get_text()
                    if raw:
                        script_candidates.append(
                            html.unescape(raw)
                        )

            for raw in script_candidates[:40]:
                try:
                    payload = json.loads(raw)
                except Exception:
                    payload = raw

                stats = self.stats_from_json(payload)
                if stats:
                    return GarmothResult(
                        ok=True,
                        stats=stats,
                        source="http-embedded-json",
                        diagnostics={
                            "status": status,
                            "final_url": final_url,
                        },
                    )

            return GarmothResult(
                ok=False,
                error=(
                    "HTTP сторінка відкрилась, але AP/AAP/DP "
                    "у HTML/embedded JSON не знайдені"
                ),
                source="http",
                diagnostics={
                    "status": status,
                    "final_url": final_url,
                    "scripts": len(script_candidates),
                },
            )

        except Exception as error:
            return GarmothResult(
                ok=False,
                error=(
                    f"HTTP {type(error).__name__}: {error}"
                ),
                source="http",
            )

    @staticmethod
    def _system_chromium_path() -> str | None:
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

    @staticmethod
    def _playwright_chromium_binary() -> str | None:
        roots = [
            Path.home() / ".cache" / "ms-playwright",
            Path("/opt/render/.cache/ms-playwright"),
        ]

        patterns = (
            "chromium-*/chrome-linux64/chrome",
            "chromium-*/chrome-linux/chrome",
            (
                "chromium_headless_shell-*/"
                "chrome-headless-shell-linux64/"
                "chrome-headless-shell"
            ),
        )

        for root in roots:
            if not root.exists():
                continue

            for pattern in patterns:
                for match in sorted(
                    root.glob(pattern),
                    reverse=True,
                ):
                    if match.is_file():
                        return str(match)

        return None

    @classmethod
    def _selenium_options(cls):
        from selenium.webdriver.chrome.options import Options

        options = Options()
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
            "--user-agent=" + cls.USER_AGENT
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
                    "[GARMOTH][ERROR] Chromium install: "
                    + (result.stderr or result.stdout or "")[-1500:]
                )
                return None

        except Exception as error:
            print(
                "[GARMOTH][ERROR] Chromium install: "
                f"{type(error).__name__}: {error}"
            )
            return None

        return cls._playwright_chromium_binary()

    @classmethod
    def _open_driver(cls):
        from selenium import webdriver

        options = cls._selenium_options()

        try:
            driver = webdriver.Chrome(options=options)
        except Exception as first_error:
            print(
                "[GARMOTH] Selenium first launch failed: "
                f"{type(first_error).__name__}: {first_error}"
            )

            browser_binary = (
                cls._install_runtime_chromium_sync()
            )

            if browser_binary:
                options = cls._selenium_options()
                options.binary_location = browser_binary

                try:
                    driver = webdriver.Chrome(
                        options=options
                    )
                except Exception as second_error:
                    print(
                        "[GARMOTH] Selenium retry failed: "
                        f"{type(second_error).__name__}: "
                        f"{second_error}"
                    )
                    driver = None
            else:
                driver = None

            if driver is None:
                from selenium.webdriver.chrome.service import Service
                from webdriver_manager.chrome import ChromeDriverManager

                driver = webdriver.Chrome(
                    service=Service(
                        ChromeDriverManager().install()
                    ),
                    options=options,
                )

        try:
            client_config = getattr(
                driver.command_executor,
                "_client_config",
                None,
            )
            if client_config is not None:
                client_config.timeout = 30
        except Exception:
            pass

        return driver

    def _fetch_selenium_sync(self, url: str) -> GarmothResult:
        from selenium.common.exceptions import (
            JavascriptException,
            StaleElementReferenceException,
            TimeoutException,
            WebDriverException,
        )
        driver = None
        seen_api_urls: list[str] = []
        seen_network: list[str] = []
        last_error = None
        last_ready_state = None
        body_seen = False

        try:
            driver = self._open_driver()
            driver.set_page_load_timeout(12)

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

            driver.get(url)
            deadline = time.time() + 40

            while time.time() < deadline:
                try:
                    try:
                        entries = driver.get_log(
                            "performance"
                        )
                    except Exception:
                        entries = []

                    for raw_entry in entries:
                        try:
                            outer = json.loads(
                                raw_entry.get(
                                    "message",
                                    "{}",
                                )
                            )
                            message = outer.get(
                                "message",
                                {},
                            )

                            if (
                                message.get("method")
                                != "Network.responseReceived"
                            ):
                                continue

                            params = message.get(
                                "params",
                                {},
                            )
                            response = params.get(
                                "response",
                                {},
                            )
                            response_url = str(
                                response.get(
                                    "url",
                                    "",
                                )
                            )
                            mime_type = str(
                                response.get(
                                    "mimeType",
                                    "",
                                )
                            ).casefold()
                            request_id = params.get(
                                "requestId"
                            )

                            interesting = (
                                "api.garmoth.com"
                                in response_url
                                or "/api/"
                                in response_url
                                or "character"
                                in response_url.casefold()
                                or "build"
                                in response_url.casefold()
                            )

                            if not interesting:
                                continue

                            if response_url:
                                network_line = (
                                    f"{int(response.get('status', 0) or 0)} "
                                    f"{mime_type or '?'} "
                                    f"{response_url}"
                                )
                                if (
                                    network_line not in seen_network
                                    and len(seen_network) < 40
                                ):
                                    seen_network.append(network_line)

                            if (
                                response_url
                                and response_url
                                not in seen_api_urls
                                and len(seen_api_urls) < 30
                            ):
                                seen_api_urls.append(
                                    response_url
                                )

                            if not request_id:
                                continue

                            if (
                                "json" not in mime_type
                                and "/api/"
                                not in response_url
                                and "api.garmoth.com"
                                not in response_url
                            ):
                                continue

                            try:
                                body_result = (
                                    driver.execute_cdp_cmd(
                                        "Network.getResponseBody",
                                        {
                                            "requestId":
                                            request_id
                                        },
                                    )
                                )
                            except Exception:
                                continue

                            body = body_result.get(
                                "body",
                                "",
                            )

                            if not body:
                                continue

                            try:
                                payload = json.loads(body)
                            except Exception:
                                payload = body

                            stats = self.stats_from_json(
                                payload
                            )
                            if stats:
                                return GarmothResult(
                                    ok=True,
                                    stats=stats,
                                    source="selenium-network",
                                    diagnostics={
                                        "network_url":
                                        response_url,
                                    },
                                )

                        except Exception:
                            continue

                    # Nuxt може знищувати execution context під час
                    # внутрішньої навігації. Не шукаємо <body> locator-ом.
                    # Читаємо DOM тільки якщо document.body вже існує.
                    dom_state = driver.execute_script(
                        """
                        return {
                            ready: document.readyState || null,
                            hasBody: !!document.body,
                            text: document.body
                                ? (document.body.innerText || '')
                                : '',
                            html: document.documentElement
                                ? (document.documentElement.outerHTML || '')
                                : ''
                        };
                        """
                    ) or {}

                    last_ready_state = dom_state.get("ready")
                    body_text = dom_state.get("text") or ""
                    page_html = dom_state.get("html") or ""
                    body_seen = body_seen or bool(
                        dom_state.get("hasBody")
                    )

                    if body_text:
                        stats = self.stats_from_labelled_text(
                            body_text
                        )
                        if stats:
                            return GarmothResult(
                                ok=True,
                                stats=stats,
                                source="selenium-dom-text",
                            )

                    if page_html:
                        # Старий selector та SSR/Nuxt HTML без Selenium locators.
                        soup = BeautifulSoup(
                            page_html,
                            "html.parser",
                        )

                        legacy_values = [
                            element.get_text(
                                " ",
                                strip=True,
                            )
                            for element in soup.select(
                                ".grid-cols-4 .text-2xl"
                            )
                        ]
                        stats = self.stats_from_sequence(
                            legacy_values
                        )
                        if stats:
                            return GarmothResult(
                                ok=True,
                                stats=stats,
                                source="selenium-html-old",
                            )

                        html_text = soup.get_text(
                            "\n",
                            strip=True,
                        )
                        stats = self.stats_from_labelled_text(
                            html_text
                        )
                        if stats:
                            return GarmothResult(
                                ok=True,
                                stats=stats,
                                source="selenium-html-text",
                            )

                        for script in soup.find_all("script"):
                            raw = (
                                script.string
                                or script.get_text()
                            )
                            if not raw:
                                continue
                            stats = self.stats_from_json(raw)
                            if stats:
                                return GarmothResult(
                                    ok=True,
                                    stats=stats,
                                    source="selenium-html-json",
                                )

                    if any(
                        marker in body_text.casefold()
                        for marker in (
                            "just a moment",
                            "verify you are human",
                            "checking your browser",
                        )
                    ):
                        last_error = "Cloudflare verification"

                except (
                    StaleElementReferenceException,
                    JavascriptException,
                    WebDriverException,
                ) as error:
                    # Не тягнемо величезний Selenium stacktrace у Discord.
                    message = str(error).splitlines()[0][:300]
                    last_error = (
                        f"{type(error).__name__}: {message}"
                    )

                time.sleep(1)

            try:
                title = driver.title
                final_url = driver.current_url
            except Exception:
                title = "?"
                final_url = url

            return GarmothResult(
                ok=False,
                error=(
                    "Selenium: профіль відкрився, "
                    "але стати не зчитані"
                ),
                source="selenium",
                diagnostics={
                    "title": title,
                    "final_url": final_url,
                    "ready_state": last_ready_state,
                    "body_seen": body_seen,
                    "last_error": last_error,
                    "network_urls": seen_api_urls[-8:],
                    "network": seen_network[-12:],
                },
            )

        except TimeoutException as error:
            return GarmothResult(
                ok=False,
                error=(
                    f"Selenium TimeoutException: {error}"
                ),
                source="selenium",
                diagnostics={
                    "ready_state": last_ready_state,
                    "body_seen": body_seen,
                    "network_urls": seen_api_urls[-8:],
                    "network": seen_network[-12:],
                },
            )

        except Exception as error:
            return GarmothResult(
                ok=False,
                error=(
                    f"Selenium {type(error).__name__}: "
                    f"{error}"
                ),
                source="selenium",
                diagnostics={
                    "network_urls":
                    seen_api_urls[-8:]
                },
            )

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

            self.release_process_memory()

    async def get_stats(self, url: str) -> GarmothResult:
        """HTTP first; Selenium only if lightweight parsing cannot read stats."""
        http_result = await self._try_http(url)

        if http_result.ok:
            print(
                f"[GARMOTH] success source={http_result.source} "
                f"stats={http_result.stats}"
            )
            return http_result

        print(
            "[GARMOTH] HTTP path did not find stats; "
            "falling back to Selenium"
        )

        selenium_result = await asyncio.to_thread(
            self._fetch_selenium_sync,
            url,
        )

        if selenium_result.ok:
            print(
                f"[GARMOTH] success source={selenium_result.source} "
                f"stats={selenium_result.stats}"
            )
            return selenium_result

        diagnostics = {
            "http": http_result.diagnostics,
            "selenium": selenium_result.diagnostics,
        }

        return GarmothResult(
            ok=False,
            error=(
                selenium_result.error
                or http_result.error
                or "Garmoth data unavailable"
            ),
            source=selenium_result.source or http_result.source,
            diagnostics=diagnostics,
        )
