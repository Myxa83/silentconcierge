# -*- coding: utf-8 -*-
# bdo_stats_cog.py
#
# Читає скріни результатів BBF з каналу, парсить через OCR.space,
# зберігає статистику в MongoDB і впливає на пріоритет у реєстрації BBF.

import os
import json
import re
import aiohttp
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from pymongo import MongoClient

# ─── MongoDB ──────────────────────────────────────────────────────────────────

_mongo_client = None
_mongo_db = None


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
    name = re.sub(r"^\[.*?\]\s*", "", display_name).strip()
    name = re.sub(r"^\(.*?\)\s*", "", name).strip()

    if "|" in name:
        name = name.split("|")[0].strip()
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


# ─── OCR.space — читання скріну ───────────────────────────────────────────────

def _normalise_ocr_text(text: str) -> str:
    """Легка чистка тексту після OCR."""
    text = text.replace("\r", "\n")
    text = text.replace("—", "-")
    text = text.replace("–", "-")
    text = text.replace("|", " ")
    text = text.replace("☠", " ")
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def _clean_family_name(raw: str) -> str:
    """Чистить Family Name, який OCR витягнув перед числами."""
    raw = raw.strip()

    # Прибираємо очевидні заголовки / маркери
    raw = re.sub(r"\b(Family|Name|Guild|Member|Player|Форти|Ships|Death|Deaths)\b", "", raw, flags=re.I)
    raw = re.sub(r"[^A-Za-z0-9_\-А-Яа-яІіЇїЄєҐґ'’ ]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()

    # Якщо OCR приклеїв зайві слова, беремо останній схожий токен
    parts = raw.split()
    if len(parts) > 1:
        # Family name у BDO зазвичай один токен
        raw = parts[-1]

    return raw.strip(" -_.")


def _parse_ocr_lines_to_players(ocr_text: str) -> list[dict]:
    """
    OCR.space повертає просто текст.
    Очікуємо рядки виду:
    Myxa 0 1 0 2 0 0 3

    Після Family Name має бути 7 числових стовпців:
    1 forts
    2-5 ships
    6 ignore
    7 ignore
    """
    text = _normalise_ocr_text(ocr_text)
    players: list[dict] = []

    for line in text.splitlines():
        original_line = line.strip()
        if not original_line:
            continue

        # Пропускаємо заголовки
        low = original_line.lower()
        if any(word in low for word in ["family", "name", "форти", "death", "deaths"]):
            continue

        # Витягуємо всі числа в рядку
        nums = re.findall(r"\b\d+\b", original_line)
        if len(nums) < 7:
            continue

        # Беремо останні 7 чисел як стовпці таблиці
        cols = [int(x) for x in nums[-7:]]

        # Family name = текст до першого числа з останнього блоку
        first_num = nums[-7]
        idx = original_line.find(first_num)
        if idx <= 0:
            continue

        family_name = _clean_family_name(original_line[:idx])
        if not family_name:
            continue

        forts = cols[0]
        ships = cols[1] + cols[2] + cols[3] + cols[4]

        players.append({
            "family_name": family_name,
            "forts": forts,
            "ships": ships,
        })

    # Прибираємо дублікати, якщо OCR повторив рядок
    unique: dict[str, dict] = {}
    for p in players:
        key = p["family_name"].lower()
        if key not in unique:
            unique[key] = p
        else:
            unique[key]["forts"] = max(unique[key]["forts"], p["forts"])
            unique[key]["ships"] = max(unique[key]["ships"], p["ships"])

    return list(unique.values())


async def _parse_screenshot(image_bytes: bytes, mime_type: str = "image/png") -> list[dict] | None:
    """
    Безкоштовний варіант: надсилає скрін в OCR.space,
    отримує текст і парсить таблицю без OpenAI / Gemini.
    """
    api_key = (
        os.environ.get("OCR_SPACE_API_KEY")
        or os.environ.get("OCRSPACE_API_KEY")
        or ""
    )

    if not api_key:
        print("[BDO_STATS][ERROR] OCR_SPACE_API_KEY не задано!")
        return None

    # OCR.space нормально приймає png/jpg/jpeg/webp як файл.
    file_ext = "png"
    if mime_type in ("image/jpeg", "image/jpg"):
        file_ext = "jpg"
    elif mime_type == "image/webp":
        file_ext = "webp"

    form = aiohttp.FormData()
    form.add_field("apikey", api_key)
    form.add_field("language", "eng")
    form.add_field("isOverlayRequired", "false")
    form.add_field("isTable", "true")
    form.add_field("scale", "true")
    form.add_field("OCREngine", "2")
    form.add_field(
        "file",
        image_bytes,
        filename=f"bbf_result.{file_ext}",
        content_type=mime_type or "image/png",
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.ocr.space/parse/image",
                data=form,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                raw = await resp.text()

                if resp.status != 200:
                    print(f"[BDO_STATS][ERROR] OCR.space HTTP {resp.status}: {raw[:1500]}")
                    return None

                data = json.loads(raw)

        if data.get("IsErroredOnProcessing"):
            print(f"[BDO_STATS][ERROR] OCR.space processing error: {data.get('ErrorMessage')}")
            return None

        parsed_results = data.get("ParsedResults") or []
        if not parsed_results:
            print(f"[BDO_STATS][ERROR] OCR.space не повернув ParsedResults: {raw[:1500]}")
            return None

        ocr_text = "\n".join(
            str(item.get("ParsedText", ""))
            for item in parsed_results
        ).strip()

        if not ocr_text:
            print("[BDO_STATS][ERROR] OCR.space повернув порожній текст")
            return None

        print("[BDO_STATS][OCR RAW]")
        print(ocr_text[:3000])

        players = _parse_ocr_lines_to_players(ocr_text)

        if not players:
            print("[BDO_STATS][ERROR] Не вдалося розпарсити гравців з OCR тексту")
            return None

        print(f"[BDO_STATS] OCR.space розпізнав {len(players)} гравців")
        return players

    except Exception as e:
        print(f"[BDO_STATS][ERROR] OCR.space помилка: {type(e).__name__}: {e}")
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
                    "weeks_forts": 0,
                    "weeks_ships": 0,
                    "weeks_active": 0,
                }
            scores[fn]["forts_total"] += p.get("forts", 0)
            scores[fn]["ships_total"] += p.get("ships", 0)
            scores[fn]["weeks_active"] += 1
            if p.get("forts", 0) > 0:
                scores[fn]["weeks_forts"] += 1
            if p.get("ships", 0) > SHIPS_TOP_THRESHOLD:
                scores[fn]["weeks_ships"] += 1

    total_weeks = len(history)
    for fn, s in scores.items():
        s["is_fort_top"] = s["weeks_forts"] >= max(1, total_weeks // 2)
        s["is_ship_top"] = s["weeks_ships"] >= max(1, total_weeks // 2)

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

        attachment = None
        for att in message.attachments:
            content_type = att.content_type or ""
            filename = (att.filename or "").lower()

            is_image = (
                content_type.startswith("image/")
                or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))
            )

            if is_image:
                attachment = att
                break

        if not attachment:
            print("[BDO_STATS] У повідомленні є вкладення, але це не схоже на картинку")
            return

        await message.add_reaction("⏳")

        try:
            image_bytes = await attachment.read()
        except Exception as e:
            print(f"[BDO_STATS][ERROR] Не вдалось прочитати зображення: {e}")
            await message.add_reaction("❌")
            return

        mime_type = attachment.content_type or "image/png"
        if mime_type == "image/jpg":
            mime_type = "image/jpeg"

        players = await _parse_screenshot(image_bytes, mime_type)

        if not players:
            try:
                await message.remove_reaction("⏳", self.bot.user)
            except Exception:
                pass
            await message.add_reaction("❌")
            await message.reply(
                "❌ Не вдалось розпізнати таблицю. Спробуй чіткіший скрін або обріж зайві краї.",
                mention_author=False,
            )
            return

        week_key = _get_week_key()
        _save_week_stats(message.guild.id, week_key, players)

        embed = discord.Embed(
            title=f"📊 Статистика BBF - {week_key}",
            description=f"Розпізнано **{len(players)}** гравців",
            color=discord.Color.from_rgb(45, 60, 110),
        )

        fort_lines = []
        ship_lines = []
        other_lines = []

        for p in sorted(players, key=lambda x: (-x.get("forts", 0), -x.get("ships", 0))):
            fn = p["family_name"]
            forts = p.get("forts", 0)
            ships = p.get("ships", 0)

            member = _find_discord_member(message.guild, fn)
            name = member.mention if member else f"`{fn}`"

            if forts > 0:
                fort_lines.append(f"🏰 {name} - форти: **{forts}**, кораблі: {ships}")
            elif ships > SHIPS_TOP_THRESHOLD:
                ship_lines.append(f"⛵ {name} - кораблі: **{ships}**")
            else:
                other_lines.append(f"➖ {name} - форти: {forts}, кораблі: {ships}")

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

        try:
            await message.remove_reaction("⏳", self.bot.user)
        except Exception:
            pass
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

        fort_tops = [(fn, s) for fn, s in scores.items() if s["is_fort_top"]]
        ship_tops = [
            (fn, s)
            for fn, s in scores.items()
            if s["is_ship_top"] and not s["is_fort_top"]
        ]

        embed = discord.Embed(
            title="📊 Накопичена статистика BBF",
            description=f"Аналіз за останні **{len(history)}** тижнів",
            color=discord.Color.gold(),
        )

        if fort_tops:
            lines = []
            for fn, s in sorted(fort_tops, key=lambda x: -x[1]["forts_total"]):
                member = _find_discord_member(interaction.guild, fn)
                name = member.mention if member else f"`{fn}`"
                lines.append(
                    f"🏰 {name} - {s['forts_total']} фортів за {s['weeks_forts']} тижнів"
                )
            embed.add_field(
                name="🏰 Топ по фортах (пріоритет 2)",
                value="\n".join(lines),
                inline=False,
            )

        if ship_tops:
            lines = []
            for fn, s in sorted(ship_tops, key=lambda x: -x[1]["ships_total"]):
                member = _find_discord_member(interaction.guild, fn)
                name = member.mention if member else f"`{fn}`"
                lines.append(
                    f"⛵ {name} - {s['ships_total']} кораблів за {s['weeks_ships']} тижнів"
                )
            embed.add_field(
                name="⛵ Топ по кораблях (пріоритет 3)",
                value="\n".join(lines),
                inline=False,
            )

        embed.set_footer(text="Silent Concierge by Myxa  |  🍾 Ром, Ром, РОМ!")
        await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(
        name="bdo_пріоритет",
        description="Показати пріоритет гравців для наступного BBF",
    )
    async def bdo_priority(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        db = _get_db()
        bbf_doc = db["bbf"].find_one({"_id": "main"})
        bbf_points = bbf_doc.get("points", {}) if bbf_doc else {}

        history = _get_history(interaction.guild.id)
        scores = _calc_player_scores(history) if history else {}

        members_data = []
        for member in interaction.guild.members:
            if member.bot:
                continue

            fn = _extract_family_name(member.display_name)
            is_lead = _is_leader(member)
            pts = bbf_points.get(str(member.id), 0)

            priority, reason = _get_player_priority(
                str(member.id),
                fn,
                is_lead,
                scores,
                pts,
            )

            members_data.append((member, fn, priority, reason))

        members_data.sort(key=lambda x: (x[2], -bbf_points.get(str(x[0].id), 0)))

        lines = []
        for member, fn, priority, reason in members_data[:25]:
            fn_str = f" `[{fn}]`" if fn else ""
            lines.append(f"{member.mention}{fn_str} - {reason}")

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

        result = db["bdo_stats"].delete_one(
            {"_id": f"{interaction.guild.id}_{week_key}"}
        )

        if result.deleted_count:
            await interaction.followup.send(
                f"✅ Статистику тижня `{week_key}` видалено.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"ℹ️ Тиждень `{week_key}` не знайдено.",
                ephemeral=True,
            )


# ─── Setup ────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BDOStatsCog(bot))
    print("[COG] BDOStatsCog завантажено ✅")
