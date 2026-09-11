# -*- coding: utf-8 -*-
# One-time migration: remove the current newest BDF article from seen links
# so bdf_news_cog republishes it after the broken embed is deleted.

import aiohttp
from bs4 import BeautifulSoup

from data.mongo_store import load_state, save_state


BDF_NEWS_URL = "https://www.blackdesertfoundry.com/category/all-news/"
STATE_COLLECTION = "bdf_news_state"
MIGRATION_COLLECTION = "bdf_repost_latest_2026_09_11"


async def _get_latest_bdf_link() -> str | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        async with session.get(BDF_NEWS_URL) as resp:
            resp.raise_for_status()
            html = await resp.text(errors="ignore")

    soup = BeautifulSoup(html, "lxml")

    for node in soup.select("article, .post, .type-post, .entry"):
        title_tag = node.find(["h1", "h2", "h3"])
        link_tag = title_tag.find("a", href=True) if title_tag else None
        if not link_tag:
            link_tag = node.find("a", href=True)

        if not link_tag:
            continue

        link = (link_tag.get("href") or "").strip()
        if link.startswith("http") and "blackdesertfoundry.com" in link:
            return link

    return None


async def setup(bot) -> None:
    # Run exactly once. The marker is stored in Mongo, so later restarts do nothing.
    already_done = load_state(MIGRATION_COLLECTION, False)
    if already_done:
        print("[BDFRepostOnce] already completed")
        return

    try:
        latest_link = await _get_latest_bdf_link()
        if not latest_link:
            print("[BDFRepostOnce] latest BDF link not found; migration not marked done")
            return

        links = load_state(
            STATE_COLLECTION,
            [],
            legacy_path="data/bdf_news_seen.json",
        )

        if not isinstance(links, list):
            links = []

        if latest_link in links:
            links = [link for link in links if link != latest_link]
            save_state(STATE_COLLECTION, sorted(set(links)))
            print(f"[BDFRepostOnce] removed latest seen link: {latest_link}")
        else:
            print(f"[BDFRepostOnce] latest link was already not seen: {latest_link}")

        save_state(MIGRATION_COLLECTION, True)
        print("[BDFRepostOnce] migration completed")

    except Exception as e:
        # Do not set the marker on failure. A later restart can try again.
        print(f"[BDFRepostOnce] failed: {type(e).__name__}: {e}")
