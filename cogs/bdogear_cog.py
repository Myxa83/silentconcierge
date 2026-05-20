# -*- coding: utf-8 -*-
# _bdogear_cog.py — MongoDB версія

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import re
import os
import time
from datetime import datetime

from pymongo import MongoClient

# ─── MongoDB ─────────────────────────────────────────────────────────────────

_mongo_client = None
_mongo_db     = None

def _get_db():
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        url = os.environ.get("MONGODB_URL", "")
        _mongo_client = MongoClient(url, serverSelectionTimeoutMS=10000)
        _mongo_db     = _mongo_client["silentconcierge"]
    return _mongo_db


def _load_gear() -> dict:
    try:
        db  = _get_db()
        doc = db["members_gear"].find_one({"_id": "main"})
        if doc:
            doc.pop("_id", None)
            return doc
    except Exception as e:
        print(f"[GEAR][ERROR] load: {e}")
    return {}


def _save_gear(data: dict) -> None:
    try:
        db = _get_db()
        db["members_gear"].replace_one(
            {"_id": "main"},
            {"_id": "main", **data},
            upsert=True,
        )
        print(f"[GEAR] Збережено гравців: {len(data)}")
    except Exception as e:
        print(f"[GEAR][ERROR] save: {e}")

# ─── Cog ──────────────────────────────────────────────────────────────────────

class BdoGear(commands.Cog):
    def __init__(self, bot):
        self.bot              = bot
        self.delays           = [20, 41, 37, 12, 23, 5, 11, 14, 31, 38]
        self.target_channel_id = 1358443998603120824

    async def fetch_stats_playwright(self, url: str) -> dict | None:
        """Парсинг статсів через Playwright."""
        try:
            from playwright.async_api import async_playwright
            from bs4 import BeautifulSoup
        except ImportError as e:
            print(f"[GEAR] Import error: {e}")
            return None

        async with async_playwright() as p:
            browser = None
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_selector(".grid-cols-4 .text-2xl", timeout=20000)
                await asyncio.sleep(2)

                content = await page.content()
                from bs4 import BeautifulSoup
                soup            = BeautifulSoup(content, "html.parser")
                stats_container = soup.find("div", class_="grid-cols-4")

                if stats_container:
                    values = stats_container.find_all("p", class_="text-2xl")
                    if len(values) >= 4:
                        return {
                            "ap":  values[0].get_text(strip=True),
                            "aap": values[1].get_text(strip=True),
                            "dp":  values[2].get_text(strip=True),
                            "gs":  values[3].get_text(strip=True),
                        }
            except Exception as e:
                print(f"[GEAR] Помилка збору {url}: {e}")
            finally:
                if browser:
                    await browser.close()
        return None

    async def run_mass_collect(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Масовий збір статсів."""
        await interaction.followup.send(f"⚙️ **Запуск...** Отримую дані з #{channel.name}")

        gear_data = _load_gear()
        count     = 0
        pattern   = r"https?://(?:www\.)?garmoth\.com/character/\S+"

        messages       = [msg async for msg in channel.history(limit=500)]
        valid_messages = [m for m in messages if "garmoth.com/character/" in m.content]
        valid_messages.reverse()  # старі → нові

        for message in valid_messages:
            links = re.findall(pattern, message.content)
            if not links:
                continue

            author_name = message.author.display_name
            link        = links[-1]
            count      += 1
            stats       = await self.fetch_stats_playwright(link)
            unix_time   = int(time.time())
            wait_time   = self.delays[(count - 1) % len(self.delays)]

            embed = discord.Embed(
                title       = "✨ Garmoth Profile Updated",
                description = f"Дані гравця **{author_name}** оновлено.",
                color       = discord.Color.blue(),
                timestamp   = datetime.now(),
            )

            if stats:
                embed.add_field(name="⚔️ AP/AAP", value=f"{stats['ap']} / {stats['aap']}", inline=True)
                embed.add_field(name="🛡️ DP",     value=stats["dp"],                        inline=True)
                embed.add_field(name="🌟 GS",      value=f"**{stats['gs']}**",               inline=True)

                gear_data[author_name.lower()] = {
                    "display_name": author_name,
                    "link":         link,
                    "gs":           stats["gs"],
                    "ap":           stats["ap"],
                    "aap":          stats["aap"],
                    "dp":           stats["dp"],
                    "user_id":      message.author.id,
                    "updated":      datetime.now().strftime("%d.%m.%Y %H:%M"),
                }
            else:
                embed.add_field(name="Статус", value="❌ Не вдалося зчитати (Private?)", inline=False)

            embed.add_field(name="🕒 Час",       value=f"<t:{unix_time}:f>",          inline=False)
            embed.add_field(name="🔗 Посилання", value=f"[Garmoth]({link})",          inline=False)
            embed.set_footer(
                text     = f"Прогрес: {count} | Очікування: {wait_time}с",
                icon_url = message.author.display_avatar.url,
            )

            await interaction.channel.send(embed=embed)
            await asyncio.sleep(wait_time)

        _save_gear(gear_data)
        await interaction.channel.send(
            f"✅ **Парсинг завершено!** В базі тепер гравців: {len(gear_data)}"
        )

    # ── Slash команди ────────────────────────────────────────────────────────

    @app_commands.command(name="collect", description="Масовий збір статсів гільдії")
    async def collect(self, interaction: discord.Interaction):
        await interaction.response.defer()
        channel = self.bot.get_channel(self.target_channel_id) or await self.bot.fetch_channel(self.target_channel_id)
        await self.run_mass_collect(interaction, channel)

    @app_commands.command(name="gear_find", description="Знайти ГС гравця за нікнеймом")
    @app_commands.describe(nickname="Нікнейм гравця в Discord")
    async def gear_find(self, interaction: discord.Interaction, nickname: str):
        gear_data = _load_gear()
        user_info = gear_data.get(nickname.lower())

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
        gear_data = _load_gear()
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

        stats = await self.fetch_stats_playwright(посилання)
        if not stats:
            await interaction.followup.send("❌ Не вдалося зчитати дані (профіль приватний?)", ephemeral=True)
            return

        gear_data   = _load_gear()
        author_name = interaction.user.display_name
        gear_data[author_name.lower()] = {
            "display_name": author_name,
            "link":         посилання,
            "gs":           stats["gs"],
            "ap":           stats["ap"],
            "aap":          stats["aap"],
            "dp":           stats["dp"],
            "user_id":      interaction.user.id,
            "updated":      datetime.now().strftime("%d.%m.%Y %H:%M"),
        }
        _save_gear(gear_data)

        await interaction.followup.send(
            f"✅ Твої дані оновлено!\n"
            f"⚔️ AP/AAP: {stats['ap']}/{stats['aap']} | 🛡️ DP: {stats['dp']} | 🌟 GS: **{stats['gs']}**",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(BdoGear(bot))
    print("[COG] BdoGear завантажено")
