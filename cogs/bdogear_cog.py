# -*- coding: utf-8 -*-
# MASTER SPEC: /BDOGEAR_MAIN.md
# Read BDOGEAR_MAIN.md before changing this cog.
# _bdogear_cog.py — MongoDB версія

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import re
import time
from datetime import datetime, timedelta, timezone

from data.gear_store import count_members, load_gear, upsert_member_gear
from data.mongo_store import get_database
from pymongo.errors import DuplicateKeyError
from services.garmoth_client import GarmothClient

# ─── Cog ──────────────────────────────────────────────────────────────────────

class BdoGear(commands.Cog):
    PARSER_VERSION = GarmothClient.VERSION

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
        self.garmoth_client = GarmothClient()

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

    def _release_process_memory(self) -> None:
        self.garmoth_client.release_process_memory()

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

    async def fetch_stats(self, url: str) -> dict | None:
        """Отримує стати через окремий Garmoth service."""
        result = await self.garmoth_client.get_stats(url)

        if result.ok and result.stats:
            self.last_scrape_error = None
            print(
                f"[GEAR] parser={self.PARSER_VERSION} "
                f"source={result.source} stats={result.stats}"
            )
            return result.stats

        diagnostics = str(result.diagnostics or {})
        self.last_scrape_error = (
            f"{result.error or 'Garmoth data unavailable'}; "
            f"source={result.source or 'unknown'}; "
            f"diagnostics={diagnostics[:900]}"
        )
        print(
            f"[GEAR][ERROR] parser={self.PARSER_VERSION}: "
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
            stats = await self.fetch_stats(link)
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
        failed = False

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
                stats = await self.fetch_stats(link)
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
            failed = True
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
        if failed:
            return

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
