# -*- coding: utf-8 -*-
# bdo_stats_cog.py
#
# Читає скріни результатів BBF з каналу, парсить через Claude Vision,
# зберігає статистику в MongoDB і впливає на пріоритет у реєстрації BBF.

import os
import base64
import json
import re
import aiohttp
from datetime import datetime, timezone, timedelta
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from pymongo import MongoClient

# ─── MongoDB ──────────────────────────────────────────────────────────────────

_mongo_client = None
_mongo_db     = None

def _get_db():
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        url = os.environ.get("MONGODB_URL", "")
        _mongo_client = MongoClient(url, serverSelectionTimeoutMS=10000)
        _mongo_db = _mongo_client["silentconcierge"]
    return _mongo_db

# ─── Налаштування ─────────────────────────────────────────────────────────────

# Канал куди кидаєш скріни BDO
BDO_STATS_CHANNEL_ID = 1419243900140392498

# Мінімальний поріг для "топового" по кораблях (сума 4 стовпців)
SHIPS_TOP_THRESHOLD = 10

# Скільки тижнів зберігати в історії
HISTORY_WEEKS = 8

# Ролі керівників (завжди топ пріоритет)
LEADER_ROLE_IDS = [
    1375070910138028044,  # Leader
    1425974196181270671,  # Officer
    1323454517664157736,  # Moderator
    1516104235215880272,  # СтарПом
]

# ─── Парсинг Family Name з Discord нікнейму ──────────────────────────────────

def _extract_family_name(display_name: str) -> str | None:
    """
    З '[SC] Myxa | Галя' витягує 'Myxa'
    З '[SC] Lanvarvin майже' витягує 'Lanvarvin'
    """
    # Прибираємо префікс [SC] або (SC) тощо
    name = re.sub(r'^\[.*?\]\s*', '', display_name).strip()
    name = re.sub(r'^\(.*?\)\s*', '', name).strip()

    # Беремо все до '|' або пробілу
    if '|' in name:
        name = name.split('|')[0].strip()
    else:
        name = name.split()[0].strip() if name.split() else name

    return name if name else None


def _find_discord_member(guild: discord.Guild, family_name: str) -> discord.Member | None:
    """Шукає Discord юзера по Family Name (без урахування регістру)."""
    family_name_lower = family_name.lower()
    for member in guild.members:
        fn = _extract_family_name(member.display_name)
        if fn and fn.lower() == family_name_lower:
            return member
    return None


def _is_leader(member: discord.Member) -> bool:
    return any(r.id in LEADER_ROLE_IDS for r in member.roles)

# ─── Claude Vision — парсинг скріну ──────────────────────────────────────────

async def _parse_screenshot(image_bytes: bytes) -> list[dict] | None:
    """
    Надсилає скрін до OpenAI GPT-4o і отримує розпізнану таблицю.
    Повертає список: [{"family_name": str, "forts": int, "ships": int}, ...]
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[BDO_STATS][ERROR] GEMINI_API_KEY не задано!")
        return None

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    prompt = """Це скріншот результатів Black Desert Online Морської Битви (BBF).

Таблиця містить рівно 7 числових стовпців після Family Name, зліва направо:
1. Форти — ВРАХОВУЙ як "forts"
2. Галера — ВРАХОВУЙ
3. Каравела — ВРАХОВУЙ
4. Галеон — ВРАХОВУЙ
5. Панаксіон — ВРАХОВУЙ
6. Рибальський човник — ІГНОРУЙ
7. Смерті (череп ☠️) — ІГНОРУЙ

Поверни ТІЛЬКИ JSON масив без жодного тексту до або після, без ```json блоків:
[
  {"family_name": "Myxa", "forts": 0, "ships": 3},
  {"family_name": "Mizrock", "forts": 0, "ships": 10}
]

Де "ships" = стовпець 2 (Галера) + стовпець 3 (Каравела) + стовпець 4 (Галеон) + стовпець 5 (Панаксіон).
НЕ додавай стовпці 6, 7 до підрахунку.
Якщо клітинка порожня або 0 — це 0.
Порахуй уважно кожен рядок."""

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": image_b64,
                        }
                    },
                    {"text": prompt},
                ]
            }
        ]
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"]

        text = text.strip()
        # Прибираємо можливі markdown блоки
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)

        parsed = json.loads(text)
        print(f"[BDO_STATS] Claude розпізнав {len(parsed)} гравців")
        return parsed

    except Exception as e:
        print(f"[BDO_STATS][ERROR] Claude Vision помилка: {type(e).__name__}: {e}")
        return None

# ─── MongoDB: збереження статистики ──────────────────────────────────────────

def _get_week_key() -> str:
    """Повертає ключ поточного тижня: '2026-W24'"""
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


def _save_week_stats(guild_id: int, week_key: str, players: list[dict]) -> None:
    """Зберігає статистику тижня в MongoDB."""
    db = _get_db()
    doc = {
        "_id": f"{guild_id}_{week_key}",
        "guild_id": guild_id,
        "week": week_key,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "players": players,
    }
    db["bdo_stats"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    print(f"[BDO_STATS] Збережено статистику тижня {week_key}: {len(players)} гравців")


def _get_history(guild_id: int, weeks: int = HISTORY_WEEKS) -> list[dict]:
    """Повертає статистику за останні N тижнів."""
    db = _get_db()
    docs = list(
        db["bdo_stats"]
        .find({"guild_id": guild_id})
        .sort("week", -1)
        .limit(weeks)
    )
    return docs


def _calc_player_scores(history: list[dict]) -> dict[str, dict]:
    """
    Рахує накопичену статистику по гравцях за всю історію.
    Повертає: {family_name: {forts_total, ships_total, weeks_active, is_fort_top, is_ship_top}}
    """
    scores: dict[str, dict] = {}

    for week_doc in history:
        for p in week_doc.get("players", []):
            fn = p["family_name"]
            if fn not in scores:
                scores[fn] = {
                    "forts_total": 0,
                    "ships_total": 0,
                    "weeks_forts": 0,   # скільки тижнів мав > 0 фортів
                    "weeks_ships": 0,   # скільки тижнів мав > SHIPS_TOP_THRESHOLD кораблів
                    "weeks_active": 0,
                }
            scores[fn]["forts_total"]  += p.get("forts", 0)
            scores[fn]["ships_total"]  += p.get("ships", 0)
            scores[fn]["weeks_active"] += 1
            if p.get("forts", 0) > 0:
                scores[fn]["weeks_forts"] += 1
            if p.get("ships", 0) > SHIPS_TOP_THRESHOLD:
                scores[fn]["weeks_ships"] += 1

    # Визначаємо топових
    total_weeks = len(history)
    for fn, s in scores.items():
        # Топ по фортах: захоплював форти більше ніж в половині тижнів
        s["is_fort_top"]  = s["weeks_forts"] >= max(1, total_weeks // 2)
        # Топ по кораблях: мав > 10 кораблів більше ніж в половині тижнів
        s["is_ship_top"]  = s["weeks_ships"] >= max(1, total_weeks // 2)

    return scores


def _get_player_priority(
    uid: str,
    family_name: str | None,
    is_leader: bool,
    scores: dict[str, dict],
    bbf_points: int,
) -> tuple[int, str]:
    """
    Повертає (пріоритет, причина). Менше число = вищий пріоритет.
    1 = керівник
    2 = топ по фортах
    3 = топ по кораблях
    4 = звичайний (по очках BBF)
    """
    if is_leader:
        return (1, "👑 Керівник")

    if family_name and family_name in scores:
        s = scores[family_name]
        if s["is_fort_top"]:
            return (2, f"🏰 Топ по фортах ({s['weeks_forts']} тижнів)")
        if s["is_ship_top"]:
            return (3, f"⛵ Топ по кораблях ({s['weeks_ships']} тижнів)")

    return (4, f"🏅 Очки пріоритету: {bbf_points}")

# ─── Cog ──────────────────────────────────────────────────────────────────────

class BDOStatsCog(commands.Cog, name="BDOStats"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[COG][OK] BDOStatsCog завантажено")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Слухає канал зі скрінами і автоматично парсить."""
        if message.channel.id != BDO_STATS_CHANNEL_ID:
            return
        if message.author.bot:
            return
        if not message.attachments:
            return

        # Беремо перше зображення
        attachment = None
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                attachment = att
                break

        if not attachment:
            return

        await message.add_reaction("⏳")

        try:
            image_bytes = await attachment.read()
        except Exception as e:
            print(f"[BDO_STATS][ERROR] Не вдалось прочитати зображення: {e}")
            await message.add_reaction("❌")
            return

        players = await _parse_screenshot(image_bytes)

        if not players:
            await message.remove_reaction("⏳", self.bot.user)
            await message.add_reaction("❌")
            await message.reply(
                "❌ Не вдалось розпізнати таблицю. Спробуй ще раз або перевір якість скріну.",
                mention_author=False,
            )
            return

        week_key = _get_week_key()
        _save_week_stats(message.guild.id, week_key, players)

        # Будуємо embed з результатом
        embed = discord.Embed(
            title=f"📊 Статистика BBF — {week_key}",
            description=f"Розпізнано **{len(players)}** гравців",
            color=discord.Color.from_rgb(45, 60, 110),
        )

        fort_lines  = []
        ship_lines  = []
        other_lines = []

        for p in sorted(players, key=lambda x: (-x.get("forts", 0), -x.get("ships", 0))):
            fn    = p["family_name"]
            forts = p.get("forts", 0)
            ships = p.get("ships", 0)

            member = _find_discord_member(message.guild, fn)
            name   = member.mention if member else f"`{fn}`"

            if forts > 0:
                fort_lines.append(f"🏰 {name} — форти: **{forts}**, кораблі: {ships}")
            elif ships > SHIPS_TOP_THRESHOLD:
                ship_lines.append(f"⛵ {name} — кораблі: **{ships}**")
            else:
                other_lines.append(f"➖ {name} — форти: {forts}, кораблі: {ships}")

        if fort_lines:
            embed.add_field(
                name="🏰 Топ по фортах",
                value="\n".join(fort_lines),
                inline=False,
            )
        if ship_lines:
            embed.add_field(
                name=f"⛵ Топ по кораблях (>{SHIPS_TOP_THRESHOLD})",
                value="\n".join(ship_lines),
                inline=False,
            )
        if other_lines:
            embed.add_field(
                name="➖ Інші",
                value="\n".join(other_lines),
                inline=False,
            )

        embed.set_footer(text=f"Silent Concierge by Myxa  |  Тиждень {week_key}")

        await message.remove_reaction("⏳", self.bot.user)
        await message.add_reaction("✅")
        await message.reply(embed=embed, mention_author=False)

    @app_commands.command(
        name="bdo_статистика",
        description="Показати накопичену статистику гравців по BBF",
    )
    async def bdo_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        history = _get_history(interaction.guild.id)
        if not history:
            await interaction.followup.send(
                "ℹ️ Статистики ще немає. Відправ скрін результатів BBF в канал.",
                ephemeral=True,
            )
            return

        scores = _calc_player_scores(history)

        fort_tops  = [(fn, s) for fn, s in scores.items() if s["is_fort_top"]]
        ship_tops  = [(fn, s) for fn, s in scores.items() if s["is_ship_top"] and not s["is_fort_top"]]

        embed = discord.Embed(
            title="📊 Накопичена статистика BBF",
            description=f"Аналіз за останні **{len(history)}** тижнів",
            color=discord.Color.gold(),
        )

        if fort_tops:
            lines = []
            for fn, s in sorted(fort_tops, key=lambda x: -x[1]["forts_total"]):
                member = _find_discord_member(interaction.guild, fn)
                name   = member.mention if member else f"`{fn}`"
                lines.append(
                    f"🏰 {name} — {s['forts_total']} фортів за {s['weeks_forts']} тижнів"
                )
            embed.add_field(name="🏰 Топ по фортах (пріоритет 2)", value="\n".join(lines), inline=False)

        if ship_tops:
            lines = []
            for fn, s in sorted(ship_tops, key=lambda x: -x[1]["ships_total"]):
                member = _find_discord_member(interaction.guild, fn)
                name   = member.mention if member else f"`{fn}`"
                lines.append(
                    f"⛵ {name} — {s['ships_total']} кораблів за {s['weeks_ships']} тижнів"
                )
            embed.add_field(name="⛵ Топ по кораблях (пріоритет 3)", value="\n".join(lines), inline=False)

        embed.set_footer(text="Silent Concierge by Myxa  |  🍾 Ром, Ром, РОМ!")
        await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(
        name="bdo_пріоритет",
        description="Показати пріоритет гравців для наступного BBF",
    )
    async def bdo_priority(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        from pymongo import MongoClient
        db = _get_db()
        bbf_doc = db["bbf"].find_one({"_id": "main"})
        bbf_points = bbf_doc.get("points", {}) if bbf_doc else {}

        history = _get_history(interaction.guild.id)
        scores  = _calc_player_scores(history) if history else {}

        members_data = []
        for member in interaction.guild.members:
            if member.bot:
                continue
            fn       = _extract_family_name(member.display_name)
            is_lead  = _is_leader(member)
            pts      = bbf_points.get(str(member.id), 0)
            priority, reason = _get_player_priority(
                str(member.id), fn, is_lead, scores, pts
            )
            members_data.append((member, fn, priority, reason))

        members_data.sort(key=lambda x: (x[2], -bbf_points.get(str(x[0].id), 0)))

        lines = []
        for member, fn, priority, reason in members_data[:25]:
            fn_str = f" `[{fn}]`" if fn else ""
            lines.append(f"{member.mention}{fn_str} — {reason}")

        embed = discord.Embed(
            title="🏆 Пріоритет для BBF",
            description="\n".join(lines) if lines else "Немає даних",
            color=discord.Color.from_rgb(45, 60, 110),
        )
        embed.set_footer(
            text="1=Керівник → 2=Топ форти → 3=Топ кораблі → 4=Очки",
        )
        await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(
        name="bdo_видалити_тиждень",
        description="[Офіцер] Видалити статистику конкретного тижня",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(week="Тиждень у форматі 2026-W24 (залиш порожнім = поточний)")
    async def bdo_delete_week(
        self,
        interaction: discord.Interaction,
        week: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        week_key = week or _get_week_key()
        db = _get_db()
        result = db["bdo_stats"].delete_one({"_id": f"{interaction.guild.id}_{week_key}"})
        if result.deleted_count:
            await interaction.followup.send(f"✅ Статистику тижня `{week_key}` видалено.", ephemeral=True)
        else:
            await interaction.followup.send(f"ℹ️ Тиждень `{week_key}` не знайдено.", ephemeral=True)


# ─── Setup ────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BDOStatsCog(bot))
    print("[COG] BDOStatsCog завантажено ✅")
