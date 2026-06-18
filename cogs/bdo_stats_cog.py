# -*- coding: utf-8 -*-
# bdo_stats_cog.py
#
# Читає скріни результатів BBF з каналу, готує картинку через Pillow/OpenCV,
# парсить через OCR.space, зберігає статистику в MongoDB
# і впливає на пріоритет у реєстрації BBF.

import os
import json
import re
from datetime import datetime, timezone
from io import BytesIO

import aiohttp
import cv2
import discord
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
from discord import app_commands
from discord.ext import commands
from pymongo import MongoClient


_mongo_client = None
_mongo_db = None


def _get_db():
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        url = os.environ.get("MONGODB_URL", "")
        _mongo_client = MongoClient(url, serverSelectionTimeoutMS=10000)
        _mongo_db = _mongo_client["silentconcierge"]
    return _mongo_db


BDO_STATS_CHANNEL_ID = 1419243900140392498
SHIPS_TOP_THRESHOLD = 10
HISTORY_WEEKS = 8

LEADER_ROLE_IDS = [
    1375070910138028044,  # Leader
    1425974196181270671,  # Officer
    1323454517664157736,  # Moderator
    1516104235215880272,  # СтарПом
]


def _extract_family_name(display_name: str) -> str | None:
    name = re.sub(r"^\[.*?\]\s*", "", display_name).strip()
    name = re.sub(r"^\(.*?\)\s*", "", name).strip()

    if "|" in name:
        name = name.split("|")[0].strip()
    else:
        name = name.split()[0].strip() if name.split() else name

    return name if name else None


def _find_discord_member(guild: discord.Guild, family_name: str) -> discord.Member | None:
    family_name_lower = family_name.lower()
    for member in guild.members:
        fn = _extract_family_name(member.display_name)
        if fn and fn.lower() == family_name_lower:
            return member
    return None


def _is_leader(member: discord.Member) -> bool:
    return any(r.id in LEADER_ROLE_IDS for r in member.roles)


def _detect_file_ext(mime_type: str) -> str:
    if mime_type in ("image/jpeg", "image/jpg"):
        return "jpg"
    if mime_type == "image/webp":
        return "webp"
    return "png"


def _convert_any_image_to_png(image_bytes: bytes) -> bytes:
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _crop_bdo_table(img: Image.Image) -> Image.Image:
    width, height = img.size
    left = int(width * 0.02)
    top = int(height * 0.04)
    right = int(width * 0.99)
    bottom = int(height * 0.98)
    if right <= left or bottom <= top:
        return img
    return img.crop((left, top, right, bottom))


def _prepare_image_for_ocr(image_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        print(f"[BDO_STATS][ERROR] Не вдалося відкрити картинку Pillow: {e}")
        return image_bytes, mime_type or "image/png"

    try:
        img = _crop_bdo_table(img)

        scale = 3
        img = img.resize((img.width * scale, img.height * scale), Image.Resampling.LANCZOS)
        img = ImageEnhance.Sharpness(img).enhance(1.8)
        img = ImageEnhance.Contrast(img).enhance(1.7)
        img = img.filter(ImageFilter.SHARPEN)

        arr = np.array(img)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)

        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        if np.mean(bw) < 127:
            bw = cv2.bitwise_not(bw)

        kernel = np.ones((2, 2), np.uint8)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel, iterations=1)

        out = Image.fromarray(bw).convert("RGB")
        buf = BytesIO()
        out.save(buf, format="PNG", optimize=True)

        print(f"[BDO_STATS] Картинку підготовлено для OCR: {img.width}x{img.height}")
        return buf.getvalue(), "image/png"

    except Exception as e:
        print(f"[BDO_STATS][ERROR] Preprocess failed, відправляю PNG без обробки: {e}")
        try:
            png = _convert_any_image_to_png(image_bytes)
            return png, "image/png"
        except Exception:
            return image_bytes, mime_type or "image/png"


def _normalise_ocr_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = text.replace("—", "-")
    text = text.replace("–", "-")
    text = text.replace("|", " ")
    text = text.replace("☠", " ")
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def _clean_family_name(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(
        r"\b(Family|Name|Guild|Member|Player|Форти|Ships|Death|Deaths|View|Results|Balenos|Occupation|Failed)\b",
        "",
        raw,
        flags=re.I,
    )
    raw = re.sub(r"[^A-Za-z0-9_\-А-Яа-яІіЇїЄєҐґ'’ ]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()

    parts = raw.split()
    if len(parts) > 1:
        raw = parts[-1]

    return raw.strip(" -_.")


def _looks_like_player_name(line: str) -> bool:
    line = line.strip()
    if not line:
        return False

    low = line.lower()
    bad_words = [
        "family",
        "name",
        "view results",
        "occupation",
        "failed",
        "blue battlefield",
        "balenos",
        "wednesday",
    ]
    if any(x in low for x in bad_words):
        return False

    if re.search(r"\d", line):
        return True

    cleaned = _clean_family_name(line)
    return bool(re.fullmatch(r"[A-Za-z0-9_\-А-Яа-яІіЇїЄєҐґ'’]{2,32}", cleaned))


def _parse_line_based(ocr_text: str) -> list[dict]:
    text = _normalise_ocr_text(ocr_text)
    players: list[dict] = []

    for line in text.splitlines():
        original_line = line.strip()
        if not original_line:
            continue

        low = original_line.lower()
        if any(word in low for word in ["family name", "view results", "occupation failed", "blue battlefield"]):
            continue

        nums = re.findall(r"\b\d+\b", original_line)
        if len(nums) < 7:
            continue

        cols = [int(x) for x in nums[-7:]]
        first_num = nums[-7]
        idx = original_line.find(first_num)
        if idx <= 0:
            continue

        family_name = _clean_family_name(original_line[:idx])
        if not family_name:
            continue

        players.append({
            "family_name": family_name,
            "forts": cols[0],
            "ships": cols[1] + cols[2] + cols[3] + cols[4],
        })

    return players


def _parse_split_name_number_blocks(ocr_text: str) -> list[dict]:
    text = _normalise_ocr_text(ocr_text)
    lines = [x.strip() for x in text.splitlines() if x.strip()]

    names: list[str] = []
    numeric_rows: list[list[int]] = []

    for line in lines:
        nums = re.findall(r"\b\d+\b", line)

        if len(nums) >= 7:
            numeric_rows.append([int(x) for x in nums[-7:]])
            continue

        if _looks_like_player_name(line):
            name = _clean_family_name(line)
            if name and name.lower() not in ["family", "name"]:
                names.append(name)

    if not names or not numeric_rows:
        return []

    count = min(len(names), len(numeric_rows))
    players = []

    for i in range(count):
        cols = numeric_rows[i]
        players.append({
            "family_name": names[i],
            "forts": cols[0],
            "ships": cols[1] + cols[2] + cols[3] + cols[4],
        })

    return players


def _dedupe_players(players: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}

    for p in players:
        name = str(p.get("family_name", "")).strip()
        if not name:
            continue

        key = name.lower()
        forts = int(p.get("forts", 0) or 0)
        ships = int(p.get("ships", 0) or 0)

        if key not in unique:
            unique[key] = {"family_name": name, "forts": forts, "ships": ships}
        else:
            unique[key]["forts"] = max(unique[key]["forts"], forts)
            unique[key]["ships"] = max(unique[key]["ships"], ships)

    return list(unique.values())


def _parse_ocr_lines_to_players(ocr_text: str) -> list[dict]:
    players = _parse_line_based(ocr_text)
    if not players:
        players = _parse_split_name_number_blocks(ocr_text)
    return _dedupe_players(players)


async def _ocr_space_request(image_bytes: bytes, mime_type: str) -> str | None:
    api_key = os.environ.get("OCR_SPACE_API_KEY") or os.environ.get("OCRSPACE_API_KEY") or ""
    if not api_key:
        print("[BDO_STATS][ERROR] OCR_SPACE_API_KEY не задано!")
        return None

    file_ext = _detect_file_ext(mime_type)

    form = aiohttp.FormData()
    form.add_field("apikey", api_key)
    form.add_field("language", "eng")
    form.add_field("isOverlayRequired", "false")
    form.add_field("isTable", "true")
    form.add_field("scale", "true")
    form.add_field("detectOrientation", "false")
    form.add_field("OCREngine", "2")
    form.add_field(
        "file",
        image_bytes,
        filename=f"bbf_result.{file_ext}",
        content_type=mime_type or "image/png",
    )

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.ocr.space/parse/image",
            data=form,
            timeout=aiohttp.ClientTimeout(total=80),
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

    ocr_text = "\n".join(str(item.get("ParsedText", "")) for item in parsed_results).strip()
    if not ocr_text:
        print("[BDO_STATS][ERROR] OCR.space повернув порожній текст")
        return None

    return ocr_text


async def _parse_screenshot(image_bytes: bytes, mime_type: str = "image/png") -> list[dict] | None:
    if mime_type == "image/jpg":
        mime_type = "image/jpeg"

    prepared_bytes, prepared_mime = _prepare_image_for_ocr(image_bytes, mime_type)

    try:
        ocr_text = await _ocr_space_request(prepared_bytes, prepared_mime)
        if not ocr_text:
            return None

        print("[BDO_STATS][OCR RAW]")
        print(ocr_text[:4000])

        players = _parse_ocr_lines_to_players(ocr_text)
        if not players:
            print("[BDO_STATS][ERROR] Не вдалося розпарсити гравців з OCR тексту")
            return None

        print(f"[BDO_STATS] OCR.space розпізнав {len(players)} гравців")
        return players

    except Exception as e:
        print(f"[BDO_STATS][ERROR] OCR.space помилка: {type(e).__name__}: {e}")
        return None


def _get_week_key() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


def _save_week_stats(guild_id: int, week_key: str, players: list[dict]) -> None:
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
    db = _get_db()
    docs = list(
        db["bdo_stats"]
        .find({"guild_id": guild_id})
        .sort("week", -1)
        .limit(weeks)
    )
    return docs


def _calc_player_scores(history: list[dict]) -> dict[str, dict]:
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
    if is_leader:
        return (1, "👑 Керівник")

    if family_name and family_name in scores:
        s = scores[family_name]
        if s["is_fort_top"]:
            return (2, f"🏰 Топ по фортах ({s['weeks_forts']} тижнів)")
        if s["is_ship_top"]:
            return (3, f"⛵ Топ по кораблях ({s['weeks_ships']} тижнів)")

    return (4, f"🏅 Очки пріоритету: {bbf_points}")


class BDOStatsCog(commands.Cog, name="BDOStats"):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        print("[COG][OK] BDOStatsCog завантажено")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
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
            is_image = content_type.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))
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
            embed.add_field(name="🏰 Топ по фортах", value="\n".join(fort_lines), inline=False)
        if ship_lines:
            embed.add_field(name=f"⛵ Топ по кораблях (>{SHIPS_TOP_THRESHOLD})", value="\n".join(ship_lines), inline=False)
        if other_lines:
            embed.add_field(name="➖ Інші", value="\n".join(other_lines), inline=False)

        embed.set_footer(text=f"Silent Concierge by Myxa  |  Тиждень {week_key}")

        try:
            await message.remove_reaction("⏳", self.bot.user)
        except Exception:
            pass

        await message.add_reaction("✅")
        await message.reply(embed=embed, mention_author=False)

    @app_commands.command(name="bdo_статистика", description="Показати накопичену статистику гравців по BBF")
    async def bdo_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        history = _get_history(interaction.guild.id)
        if not history:
            await interaction.followup.send("ℹ️ Статистики ще немає. Відправ скрін результатів BBF в канал.", ephemeral=True)
            return

        scores = _calc_player_scores(history)
        fort_tops = [(fn, s) for fn, s in scores.items() if s["is_fort_top"]]
        ship_tops = [(fn, s) for fn, s in scores.items() if s["is_ship_top"] and not s["is_fort_top"]]

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
                lines.append(f"🏰 {name} - {s['forts_total']} фортів за {s['weeks_forts']} тижнів")
            embed.add_field(name="🏰 Топ по фортах (пріоритет 2)", value="\n".join(lines), inline=False)

        if ship_tops:
            lines = []
            for fn, s in sorted(ship_tops, key=lambda x: -x[1]["ships_total"]):
                member = _find_discord_member(interaction.guild, fn)
                name = member.mention if member else f"`{fn}`"
                lines.append(f"⛵ {name} - {s['ships_total']} кораблів за {s['weeks_ships']} тижнів")
            embed.add_field(name="⛵ Топ по кораблях (пріоритет 3)", value="\n".join(lines), inline=False)

        embed.set_footer(text="Silent Concierge by Myxa  |  🍾 Ром, Ром, РОМ!")
        await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(name="bdo_пріоритет", description="Показати пріоритет гравців для наступного BBF")
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
            priority, reason = _get_player_priority(str(member.id), fn, is_lead, scores, pts)
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
        embed.set_footer(text="1=Керівник → 2=Топ форти → 3=Топ кораблі → 4=Очки")
        await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(name="bdo_видалити_тиждень", description="[Офіцер] Видалити статистику конкретного тижня")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(week="Тиждень у форматі 2026-W24 (залиш порожнім = поточний)")
    async def bdo_delete_week(self, interaction: discord.Interaction, week: str | None = None):
        await interaction.response.defer(ephemeral=True)

        week_key = week or _get_week_key()
        db = _get_db()
        result = db["bdo_stats"].delete_one({"_id": f"{interaction.guild.id}_{week_key}"})

        if result.deleted_count:
            await interaction.followup.send(f"✅ Статистику тижня `{week_key}` видалено.", ephemeral=True)
        else:
            await interaction.followup.send(f"ℹ️ Тиждень `{week_key}` не знайдено.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BDOStatsCog(bot))
    print("[COG] BDOStatsCog завантажено ✅")
