# -*- coding: utf-8 -*-
# bdo_stats_cog.py
# BBF stats cog. Free OCR.space version with image preprocessing and split-column OCR.

import os
import json
import re
import aiohttp
from datetime import datetime, timezone
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageOps, ImageEnhance

import discord
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
    1375070910138028044,
    1425974196181270671,
    1323454517664157736,
    1516104235215880272,
]


# ─── Discord family name helpers ──────────────────────────────────────────────

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


# ─── Image / OCR helpers ──────────────────────────────────────────────────────

def _image_bytes_to_pil(image_bytes: bytes) -> Image.Image:
    return Image.open(BytesIO(image_bytes)).convert("RGB")


def _pil_to_png_bytes(img: Image.Image) -> bytes:
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _crop_ratio(img: Image.Image, box: tuple[float, float, float, float]) -> Image.Image:
    w, h = img.size
    left = max(0, min(w, int(w * box[0])))
    top = max(0, min(h, int(h * box[1])))
    right = max(0, min(w, int(w * box[2])))
    bottom = max(0, min(h, int(h * box[3])))
    if right <= left or bottom <= top:
        return img.copy()
    return img.crop((left, top, right, bottom))


def _prepare_for_ocr(img: Image.Image, scale: int = 4, mode: str = "text") -> bytes:
    img = img.convert("RGB")
    img = ImageOps.expand(img, border=10, fill=(25, 25, 25))

    arr = np.array(img)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    threshold = 125 if mode == "numbers" else 115
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)

    # BDO table is light text on dark background. OCR likes dark text on light background.
    binary = 255 - binary

    if mode == "numbers":
        kernel = np.ones((2, 2), np.uint8)
        binary = cv2.dilate(binary, kernel, iterations=1)
    else:
        kernel = np.ones((1, 1), np.uint8)
        binary = cv2.dilate(binary, kernel, iterations=1)

    out = Image.fromarray(binary).convert("RGB")
    out = ImageEnhance.Sharpness(out).enhance(1.8)
    return _pil_to_png_bytes(out)


async def _call_ocr_space(session: aiohttp.ClientSession, png_bytes: bytes, label: str) -> str:
    api_key = os.environ.get("OCR_SPACE_API_KEY") or os.environ.get("OCRSPACE_API_KEY") or ""
    if not api_key:
        print("[BDO_STATS][ERROR] OCR_SPACE_API_KEY не задано!")
        return ""

    form = aiohttp.FormData()
    form.add_field("apikey", api_key)
    form.add_field("language", "eng")
    form.add_field("isOverlayRequired", "false")
    form.add_field("isTable", "false")
    form.add_field("scale", "false")
    form.add_field("detectOrientation", "false")
    form.add_field("OCREngine", "2")
    form.add_field("file", png_bytes, filename=f"{label}.png", content_type="image/png")

    try:
        async with session.post(
            "https://api.ocr.space/parse/image",
            data=form,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as resp:
            raw = await resp.text()
            if resp.status != 200:
                print(f"[BDO_STATS][ERROR] OCR.space HTTP {resp.status} [{label}]: {raw[:1200]}")
                return ""
            data = json.loads(raw)

        if data.get("IsErroredOnProcessing"):
            print(f"[BDO_STATS][ERROR] OCR.space processing error [{label}]: {data.get('ErrorMessage')}")
            return ""

        parsed = data.get("ParsedResults") or []
        text = "\n".join(str(x.get("ParsedText", "")) for x in parsed).strip()
        print(f"[BDO_STATS][OCR {label}] {text[:1000] if text else '<empty>'}")
        return text

    except Exception as e:
        print(f"[BDO_STATS][ERROR] OCR.space call failed [{label}]: {type(e).__name__}: {e}")
        return ""


def _clean_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = text.replace("|", " ")
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def _clean_name(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(
        r"\b(Family|Name|View|Results|Blue|Battlefield|Balenos|Occupation|Success|Failed)\b",
        "",
        raw,
        flags=re.I,
    )
    raw = re.sub(r"[^A-Za-z0-9_\-А-Яа-яІіЇїЄєҐґ'’ ]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return ""

    parts = [p.strip(" -_.") for p in raw.split() if len(p.strip(" -_.")) >= 3]
    if not parts:
        return ""
    return max(parts, key=len)


def _extract_names(text: str) -> list[str]:
    text = _clean_text(text)
    names: list[str] = []
    bad = {"family", "name", "view", "results", "blue", "battlefield", "balenos", "occupation", "success", "failed"}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if any(b in low for b in bad):
            continue
        if re.fullmatch(r"[0-9\s.,:;\-]+", line):
            continue
        name = _clean_name(line)
        if len(name) < 3:
            continue
        if name.lower() in bad:
            continue
        names.append(name)

    result = []
    seen = set()
    for name in names:
        key = name.lower()
        if key not in seen:
            seen.add(key)
            result.append(name)
    return result


def _extract_numbers(text: str, expected: int) -> list[int]:
    if not text:
        return []

    text = _clean_text(text)
    for a, b in {"O": "0", "o": "0", "Q": "0", "D": "0", "l": "1", "I": "1"}.items():
        text = text.replace(a, b)

    nums = re.findall(r"\b\d+\b", text)
    values = []
    for n in nums:
        try:
            values.append(int(n))
        except ValueError:
            pass

    # If OCR glued the whole column into one long string.
    if len(values) < max(3, expected // 2):
        compact = re.sub(r"\D+", "", text)
        if len(compact) >= expected:
            values = [int(ch) for ch in compact[:expected]]

    return values


def _fit(values: list[int], n: int) -> list[int]:
    if len(values) >= n:
        return values[:n]
    return values + [0] * (n - len(values))


def _fallback_parse(text: str) -> list[dict]:
    text = _clean_text(text or "")
    players = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if any(x in low for x in ["family", "view results", "battlefield", "occupation"]):
            continue
        nums = re.findall(r"\b\d+\b", line)
        if len(nums) < 7:
            continue
        cols = [int(x) for x in nums[-7:]]
        idx = line.find(nums[-7])
        if idx <= 0:
            continue
        name = _clean_name(line[:idx])
        if not name:
            continue
        players.append({"family_name": name, "forts": cols[0], "ships": cols[1] + cols[2] + cols[3] + cols[4]})

    return players


async def _parse_screenshot(image_bytes: bytes, mime_type: str = "image/png") -> list[dict] | None:
    try:
        img = _image_bytes_to_pil(image_bytes)
    except Exception as e:
        print(f"[BDO_STATS][ERROR] PIL open failed: {e}")
        return None

    w, h = img.size
    print(f"[BDO_STATS] Image size: {w}x{h}, mime={mime_type}")

    # Coordinates for BDO BBF result table. They scale with image size.
    # Rows with data start below header.
    data_top = 0.295
    data_bottom = 0.970

    names_box = (0.145, data_top, 0.475, data_bottom)

    # Narrow crops around 7 numeric columns.
    col_boxes = [
        (0.555, data_top, 0.600, data_bottom),
        (0.625, data_top, 0.670, data_bottom),
        (0.692, data_top, 0.737, data_bottom),
        (0.760, data_top, 0.805, data_bottom),
        (0.828, data_top, 0.873, data_bottom),
        (0.895, data_top, 0.940, data_bottom),
        (0.948, data_top, 0.995, data_bottom),
    ]

    full_box = (0.100, 0.150, 0.998, 0.985)

    names_png = _prepare_for_ocr(_crop_ratio(img, names_box), scale=4, mode="text")
    full_png = _prepare_for_ocr(_crop_ratio(img, full_box), scale=3, mode="text")
    col_pngs = [_prepare_for_ocr(_crop_ratio(img, b), scale=5, mode="numbers") for b in col_boxes]

    async with aiohttp.ClientSession() as session:
        names_text = await _call_ocr_space(session, names_png, "names")
        names = _extract_names(names_text)
        print(f"[BDO_STATS] Names parsed: {names}")

        if not names:
            full_text = await _call_ocr_space(session, full_png, "full_fallback")
            players = _fallback_parse(full_text)
            if players:
                print(f"[BDO_STATS] Fallback parsed {len(players)} players")
                return players
            print("[BDO_STATS][ERROR] Не вдалося прочитати імена")
            return None

        expected = len(names)
        columns: list[list[int]] = []
        for i, png in enumerate(col_pngs, start=1):
            text = await _call_ocr_space(session, png, f"col_{i}")
            values = _fit(_extract_numbers(text, expected), expected)
            columns.append(values)
            print(f"[BDO_STATS] Column {i}: {values}")

    players = []
    for row_index, name in enumerate(names):
        cols = [columns[c][row_index] for c in range(7)]
        players.append({
            "family_name": name,
            "forts": cols[0],
            "ships": cols[1] + cols[2] + cols[3] + cols[4],
        })

    players = [p for p in players if p["family_name"] and len(p["family_name"]) >= 3]

    if not players:
        print("[BDO_STATS][ERROR] Не вдалося зібрати players після split OCR")
        return None

    print(f"[BDO_STATS] Split OCR parsed {len(players)} players")
    print(json.dumps(players, ensure_ascii=False, indent=2))
    return players


# ─── MongoDB stats ────────────────────────────────────────────────────────────

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
    return list(db["bdo_stats"].find({"guild_id": guild_id}).sort("week", -1).limit(weeks))


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
    for s in scores.values():
        s["is_fort_top"] = s["weeks_forts"] >= max(1, total_weeks // 2)
        s["is_ship_top"] = s["weeks_ships"] >= max(1, total_weeks // 2)

    return scores


def _get_player_priority(uid: str, family_name: str | None, is_leader: bool, scores: dict[str, dict], bbf_points: int) -> tuple[int, str]:
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
        if message.author.bot:
            return

        print(f"[BDO_STATS][DEBUG] message channel={message.channel.id}, attachments={len(message.attachments)}")

        if message.channel.id != BDO_STATS_CHANNEL_ID:
            return
        if not message.attachments:
            return

        attachment = None
        for att in message.attachments:
            content_type = att.content_type or ""
            filename = (att.filename or "").lower()
            is_image = content_type.startswith("image/") or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))
            print(f"[BDO_STATS][DEBUG] attachment filename={filename}, content_type={content_type}, is_image={is_image}")
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
