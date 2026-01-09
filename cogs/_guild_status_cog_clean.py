# cogs/guild_status_cog.py
import discord
from discord.ext import commands

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from discord import app_commands

from datetime import datetime, timedelta, date
import aiohttp
import csv
import re
import json
import io
import logging
import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, Tuple, List

# ===================== ЛОГИ =====================
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.DEBUG,
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ===================== КОНСТАНТИ =====================
ROWS_PER_PAGE = 30  # показувати по 30 рядків
CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vRIe7yd0uKOzihf-"
    "Gg4CZ_zggJmyb7CP9l0tr-XZEsPi9XAhhNJSVL2Qx0rInY2O3A9xurlbXsQrCWA/"
    "pub?gid=447895140&single=true&output=csv"
)

# Файли локального сховища
OCR_FILE = "guild_ocr.json"         # OCR-дані по тижнях
ALIAS_FILE = "guild_aliases.json"   # мапа перейменувань old(lower) -> New

# Канал модераторів для завантаження скрінів
MOD_CHANNEL_ID = 1370522199873814528

# ===================== ХЕЛПЕРИ =====================

def parse_int(cell) -> int:
    """Повертає ціле з клітинки, незалежно від пробілів/символів."""
    try:
        digits = re.findall(r"\d+", str(cell))
        return int("".join(digits)) if digits else 0
    except Exception:
        return 0


def clean_status(value: str) -> str:
    """Нормалізація статусу -> 'active' | 'vacation' | 'expired' | ''"""
    if not value:
        return ""
    v = (str(value) or "").strip().lower()
    v = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in v)

    if any(k in v for k in ["vac", "vacation", "вак", "відп", "канік", "відпуст"]):
        return "vacation"
    if any(k in v for k in ["contract", "expired", "expire", "вичерп", "закінч", "контракт"]):
        return "expired"
    if any(k in v for k in ["active", "актив", "участь", "particip", "yes"]):
        return "active"
    return ""


def clean_name(raw_name: str) -> str:
    """Прибирає [теги] та все після дужок/дефісів."""
    if not raw_name:
        return "-"
    name = re.sub(r"^\[.*?\]\s*", "", str(raw_name))
    name = re.split(r"[()\-\—]", name)[0].strip()
    return name


def _norm_key(name: str) -> str:
    """
    Агресивна нормалізація ніку для дедуплікації в межах одного завантаження.
    Прибирає регістр, надлишкові пробіли та типові плутанини символів.
    """
    if not name:
        return ""
    s = name.strip().lower()
    s = re.sub(r"\s+", " ", s)

    trans = str.maketrans({
        "о": "o", "О": "o", "0": "o", "°": "o",
        "і": "i", "ї": "i", "ï": "i", "í": "i", "ı": "i", "I": "i", "l": "i", "|": "i", "1": "i",
        "ѕ": "s", "ś": "s", "š": "s", "5": "s", "S": "s",
        "_": " ", "-": " ",
    })
    s = s.translate(trans)
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[guildstatus] Не вдалося зберегти {path}: {e}")


def get_canonical_name(name: str) -> str:
    """Повертає канонічне ім'я, якщо є у мапі alias; інакше саме ім'я."""
    if not name:
        return name
    key = name.lower().strip()
    return ALIASES.get("aliases", {}).get(key, name)


def iso_week_of(date_str: str) -> Optional[int]:
    """Повертає номер тижня ISO для дати у форматі DD.MM.YYYY."""
    try:
        d = datetime.strptime(date_str, "%d.%m.%Y").date()
        return d.isocalendar().week
    except Exception:
        return None

# ====== Дата/тиждень допоміжні =====
def _parse_date_ddmmyyyy(s: Optional[str]) -> date:
    if not s:
        return date.today()
    return datetime.strptime(s.strip(), "%d.%m.%Y").date()

def _week_label_from_date(d: date) -> str:
    """Мітка тижня = понеділок цього ISO-тижня (ДД.ММ.РРРР)."""
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("%d.%m.%Y")

# ===================== CSV =====================
POSSIBLE_HEADERS = {
    "name": ["family (character)", "family", "name", "нік", "ім'я"],
    "activity": ["activity", "актив", "активність"],
    "status": ["status", "participate", "участь", "contract", "контракт"],
}

def _detect_indices(header_row: List[str]) -> Dict[str, int]:
    hdr = [(c or "").strip().lower() for c in header_row]

    def find(keys):
        for k in keys:
            for i, col in enumerate(hdr):
                if k in col:
                    return i
        return None

    idx_name = find(POSSIBLE_HEADERS["name"]) or 1
    idx_activity = find(POSSIBLE_HEADERS["activity"]) or 2
    idx_status = find(POSSIBLE_HEADERS["status"]) or 7
    return {"name": idx_name, "activity": idx_activity, "status": idx_status}


async def fetch_csv_smart() -> Tuple[List[List[str]], Dict[str, int]]:
    """Повертає (rows_wo_header, indices)."""
    logger.debug("[guildstatus] Завантажую CSV (smart)...")
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(CSV_URL) as resp:
                text = await resp.text()
            logger.debug("[guildstatus] CSV завантажено успішно (smart)")
        except Exception as e:
            logger.error(f"[guildstatus] Помилка завантаження CSV (smart): {e}")
            return [], {"name": 1, "activity": 2, "status": 7}

    reader = csv.reader(text.splitlines())
    rows = [row for row in reader if any((cell or "").strip() for cell in row)]
    if len(rows) <= 1:
        logger.warning("[guildstatus] CSV порожній або без заголовка (smart)")
        return [], {"name": 1, "activity": 2, "status": 7}

    header = rows[0]
    indices = _detect_indices(header)
    return rows[1:], indices


async def fetch_csv_direct() -> List[List[str]]:
    """Фолбек: просте читання CSV без аналізу заголовків."""
    logger.debug("[guildstatus] Завантажую CSV...")
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(CSV_URL) as resp:
                text = await resp.text()
            logger.debug("[guildstatus] CSV завантажено успішно")
        except Exception as e:
            logger.error(f"[guildstatus] Помилка завантаження CSV: {e}")
            return []
    reader = csv.reader(text.splitlines())
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if len(rows) <= 1:
        logger.warning("[guildstatus] CSV порожній або без заголовка")
        return []
    return rows[1:]

# ===================== OCR-БАЗА =====================
# Структура OCR_DB:

# ---------------- Google Sheets ----------------
GSHEET_ID = "1Qs53U-GLEQ_FSyRwpr9hsPBF7spiE7b1l2cOF-MM8hk"

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
gs_client = gspread.authorize(creds)
# {
#   "weeks": {
#       "DD.MM.YYYY": {
#           "display_date": "DD.MM.YYYY",  # (нове опційне поле)
#           "aggregate": { name: {"activity": int, "status": str} },
#           "uploads": [
#               {"at": ISO8601, "uploader": user_id_str, "count": N, "data": { name: {..} }}
#           ]
#       }
#   }
# }

OCR_DB = load_json(OCR_FILE, {"weeks": {}})
ALIASES = load_json(ALIAS_FILE, {"aliases": {}})

def _latest_week_key() -> Optional[str]:
    try:
        keys = list(OCR_DB.get("weeks", {}).keys())
        if not keys:
            return None
        def keyer(k):
            try:
                return datetime.strptime(k, "%d.%m.%Y")
            except Exception:
                return k
        return sorted(keys, key=keyer)[-1]
    except Exception:
        return None

def _prev_week_key(current: str) -> Optional[str]:
    try:
        keys = list(OCR_DB.get("weeks", {}).keys())
        if not keys:
            return None
        def keyer(k):
            try:
                return datetime.strptime(k, "%d.%m.%Y")
            except Exception:
                return k
        ordered = sorted(keys, key=keyer)
        if current not in ordered:
            return None
        idx = ordered.index(current)
        return ordered[idx-1] if idx > 0 else None
    except Exception:
        return None

def _parse_ocr_text_to_rows(text: str) -> Dict[str, Dict[str, str]]:
    """Грубий парсер рядків з OCR → {name: {activity, status}}."""
    results: Dict[str, Dict[str, str]] = {}
    if not text:
        return results

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        nums = re.findall(r"\d+", line)
        activity = int(nums[-1]) if nums else 0
        name_only = re.split(r"\d", line, maxsplit=1)[0].strip()
        name_only = clean_name(name_only)
        if not name_only or len(name_only) < 2:
            continue
        status = clean_status(line)
        if not status:
            if "🟡" in line:
                status = "active"
            elif "🔵" in line:
                status = "vacation"
            elif "⚪" in line:
                status = "expired"
        results[name_only] = {"activity": activity, "status": status}

    return results

async def _run_ocr_on_image(att: discord.Attachment) -> Optional[str]:
    try:
        ct = (att.content_type or "").lower()
        if not (ct.startswith("image") or att.filename.lower().endswith((".png", ".jpg", ".jpeg"))):
            return None
        data = await att.read()
        try:
            from PIL import Image  # type: ignore
            import pytesseract     # type: ignore
        except Exception:
            return None
        img = Image.open(io.BytesIO(data)).convert("RGB")
        try:
            text = pytesseract.image_to_string(img, lang="eng+ukr")
        except Exception:
            text = pytesseract.image_to_string(img, lang="eng")
        return text
    except Exception as e:
        logger.error(f"[guildstatus] OCR error: {e}")
        return None

# ====== Сесія дозавантаження (додати ще) ======
@dataclass
class UploadSession:
    user_id: int
    channel_id: int
    week_key: str
    display_date: str
    expires_at: datetime
    added: int = 0

# ===================== VIEW =====================
class GuildStatusView(discord.ui.View):
    """Persistent View з постійними custom_id і модалками."""

    def __init__(
        self,
        data: List[List[str]],
        total_members: int,
        user: Optional[discord.Member] = None,
        custom_date: Optional[str] = None,
        col_idx: Optional[Dict[str, int]] = None,
        source: str = "google",
        week_key: Optional[str] = None,
    ):
        super().__init__(timeout=None)
        self.data = data
        self.total_members = total_members
        self.page = 0
        self.user = user
        self.highlight_name: Optional[str] = None
        self.filter_status = "all"  # "all" | "group"
        self.sort_activity = False
        self.created_date = custom_date or datetime.now().strftime("%d.%m.%Y")
        self.message_id: Optional[int] = None
        self.col_idx: Dict[str, int] = col_idx or {"name": 1, "activity": 2, "status": 7}
        self.source = source
        self.ocr_week = week_key
        logger.debug(
            f"[guildstatus] View створено: members={self.total_members}, date={self.created_date}, idx={self.col_idx}, src={self.source}, week={self.ocr_week}"
        )

    async def refresh_data(self):
        """Оновлюємо дані лише для Google-джерела; OCR не чіпаємо."""
        if self.source != "google":
            return
        logger.debug("[guildstatus] Оновлюю дані CSV (smart)...")
        rows, indices = await fetch_csv_smart()
        if not rows:
            rows = await fetch_csv_direct()
        else:
            self.col_idx = indices
        self.data = rows
        self.total_members = len(self.data)
        logger.debug(f"[guildstatus] Оновлено: {self.total_members} учасників, idx={self.col_idx}")

    def is_mod_or_admin(self, user: discord.Member) -> bool:
        return user.guild_permissions.manage_messages or user.guild_permissions.administrator

    def format_page(self):
        logger.debug(f"[guildstatus] Формую сторінку {self.page + 1}")
        if not self.data:
            table = (
                "```\nPos  | Name              | Activity       | Status   \n"
                "--------------------------------------------------------\n"
                "⚠️ Даних немає або не вдалося завантажити таблицю\n```"
            )
            footer = f"Сторінка 0/0 | Учасників: {self.total_members}"
            return table, footer

        filtered = list(self.data)  # копія
        i_name = self.col_idx.get("name", 1)
        i_act  = self.col_idx.get("activity", 2)
        i_stat = self.col_idx.get("status", 7)

        # Для OCR — мапа активностей попереднього тижня (для Δ)
        prev_map: Dict[str, int] = {}
        if self.source == "ocr" and self.ocr_week:
            prev_key = _prev_week_key(self.ocr_week)
            if prev_key and prev_key in OCR_DB.get("weeks", {}):
                bucket_prev = OCR_DB["weeks"][prev_key]
                agg_prev = bucket_prev.get("aggregate", bucket_prev)
                for nm, rec in agg_prev.items():
                    canon = get_canonical_name(clean_name(nm))
                    prev_map[canon] = parse_int(rec.get("activity", 0))

        # Якщо підсвічуємо — піднімаємо користувача угору та починаємо з 1-ї сторінки
        if self.highlight_name:
            def canon(row):
                try:
                    return get_canonical_name(clean_name(row[i_name]))
                except Exception:
                    return ""
            idx_match = next((k for k, r in enumerate(filtered)
                              if canon(r).lower() == self.highlight_name.lower()), None)
            if idx_match is not None:
                target = filtered.pop(idx_match)
                filtered.insert(0, target)
                self.page = 0

        # Групування за статусом
        if self.filter_status == "group":
            separator = "𓆟 ⊹ ࣪ ˖ ﹏﹏﹏𓊝﹏﹏﹏𓂁 ⊹ ࣪ ˖ 𓆝"
            groups = {"active": [], "vacation": [], "expired": [], "other": []}
            for row in filtered:
                status_r = clean_status(row[i_stat] if len(row) > i_stat else "")
                (groups[status_r] if status_r in groups else groups["other"]).append(row)
            filtered = []
            for key in ["active", "vacation", "expired", "other"]:
                if groups[key]:
                    filtered.append(["", separator, "", ""])  # розділювач
                    filtered.extend(groups[key])

        # Сортування за активністю
        if self.sort_activity:
            try:
                filtered = sorted(
                    filtered,
                    key=lambda x: parse_int(x[i_act] if len(x) > i_act else 0),
                    reverse=True,
                )
            except Exception as e:
                logger.warning(f"[guildstatus] Сортування за активністю не вдалося: {e}")

        start = self.page * ROWS_PER_PAGE
        end = start + ROWS_PER_PAGE
        page_data = filtered[start:end]

        headers = f"{'Pos':<4} | {'Name':<16} | {'Activity':<18} | {'Status':<20}"
        if self.source == 'ocr':
            headers = f"{'Pos':<4} | {'Name':<16} | {'Activity (Δ)':<18} | {'Status':<20}"
        lines = []

        for idx, row in enumerate(page_data, start=1 + start):
            pos = str(idx)
            raw_name  = row[i_name] if len(row) > i_name else "-"
            name      = get_canonical_name(clean_name(raw_name))
            activity  = row[i_act]  if len(row) > i_act  else "-"
            status_raw= row[i_stat] if len(row) > i_stat else ""
            status_r  = clean_status(status_raw)
            if not status_r:
                sraw = str(status_raw)
                if "🟡" in sraw:
                    status_r = "active"
                elif "🔵" in sraw:
                    status_r = "vacation"
                elif "⚪" in sraw:
                    status_r = "expired"

            if status_r == "active":
                status = "🟡 Active"
            elif status_r == "vacation":
                status = "🔵 Vacation"
            elif status_r == "expired":
                status = "⚪ Expired"
            else:
                status = str(status_raw) if status_raw else "-"

            if self.source == 'ocr':
                curr = parse_int(activity)
                delta = curr - prev_map.get(name, 0)
                act_text = f"{curr} ({delta:+})"
            else:
                act_text = str(activity)

            marker = ">>> " if (self.highlight_name and self.highlight_name.lower() == name.lower()) else ""
            line = f"{marker}{pos:<4} | {name:<16} | {act_text:<18} | {status:<20}"
            lines.append(line)

        if not lines:
            lines = ["Немає даних"]

        total_pages = (len(filtered) - 1) // ROWS_PER_PAGE + 1 if filtered else 1

        legend = "🟡 Active · 🔵 Vacation · ⚪ Expired"
        week_info = None
        if self.created_date:
            wn = iso_week_of(self.created_date)
            if wn:
                week_info = f"Тиждень року: {wn}"
        prefix = (week_info + "\n" if week_info else "") + legend + "\n"

        table = prefix + "```\n" + headers + "\n" + "-" * 70 + "\n" + "\n".join(lines) + "\n```"
        footer = f"Сторінка {self.page + 1}/{total_pages} | Учасників: {self.total_members}"
        logger.debug(f"[guildstatus] Згенеровано таблицю для сторінки {self.page + 1}")
        return table, footer

    async def _edit_host_message(self, interaction: discord.Interaction, embed: discord.Embed):
        try:
            if interaction.message:
                await interaction.message.edit(embed=embed, view=self)
            elif self.message_id:
                await interaction.followup.edit_message(message_id=self.message_id, embed=embed, view=self)
            else:
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"[guildstatus] Помилка редагування повідомлення: {e}")

    async def update_message(self, interaction: discord.Interaction):
        table, footer_text = self.format_page()
        embed = discord.Embed(
            title=f"📊 Активність учасників 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲 — {self.created_date}",
            description=table,
            color=discord.Color.green(),
        )
        bot_user = interaction.client.user if interaction.client else None
        if bot_user and bot_user.display_avatar:
            embed.set_footer(text=f"Silent Concierge by Myxa | {footer_text}", icon_url=bot_user.display_avatar.url)
        else:
            embed.set_footer(text=f"Silent Concierge by Myxa | {footer_text}")
        await self._edit_host_message(interaction, embed)

    # ----------------- BUTTONS -----------------
    @discord.ui.button(label="⮜ Попередня", style=discord.ButtonStyle.primary, row=0, custom_id="guildstatus:prev")
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.refresh_data()
        if self.page > 0:
            self.page -= 1
        await self.update_message(interaction)

    @discord.ui.button(label="Наступна ⮞", style=discord.ButtonStyle.primary, row=0, custom_id="guildstatus:next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.refresh_data()
        if (self.page + 1) * ROWS_PER_PAGE < len(self.data):
            self.page += 1
        await self.update_message(interaction)

    @discord.ui.button(label="Підсвітити мене", style=discord.ButtonStyle.primary, row=0, custom_id="guildstatus:me")
    async def highlight_me(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await self.refresh_data()
        cleaned_discord_name = get_canonical_name(clean_name(interaction.user.display_name.strip()))
        i_name = self.col_idx.get("name", 1)
        table_names = [get_canonical_name(clean_name(r[i_name])) for r in self.data if len(r) > i_name]
        normalized_table = [n.lower().replace(" ", "") for n in table_names]
        normalized_me = cleaned_discord_name.lower().replace(" ", "")
        if normalized_me in normalized_table:
            self.highlight_name = cleaned_discord_name
            self.page = 0
            await self.update_message(interaction)
        else:
            await interaction.followup.send(f"❌ Твій нік `{cleaned_discord_name}` не знайдено в таблиці.", ephemeral=True)

    @discord.ui.button(label="Підсвітити іншого", style=discord.ButtonStyle.success, row=1, custom_id="guildstatus:other")
    async def highlight_other(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = HighlightModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📊 Сортувати за активністю", style=discord.ButtonStyle.success, row=1, custom_id="guildstatus:sort")
    async def sort_by_activity(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.refresh_data()
        self.sort_activity = not self.sort_activity
        self.page = 0
        await self.update_message(interaction)

    @discord.ui.button(label="🔄 Групувати за статусом", style=discord.ButtonStyle.success, row=1, custom_id="guildstatus:group")
    async def filter_by_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.refresh_data()
        self.filter_status = "group" if self.filter_status != "group" else "all"
        self.page = 0
        await self.update_message(interaction)

    @discord.ui.button(label="Змінити дату", style=discord.ButtonStyle.secondary, row=2, custom_id="guildstatus:date")
    async def change_date(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = DateModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✏️ Перейменувати", style=discord.ButtonStyle.secondary, row=2, custom_id="guildstatus:rename")
    async def rename_member(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_mod_or_admin(interaction.user):
            return await interaction.response.send_message("⛔ Лише модераторам.", ephemeral=True)
        modal = RenameModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Скинути", style=discord.ButtonStyle.danger, row=2, custom_id="guildstatus:reset")
    async def reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.refresh_data()
        self.page = 0
        self.highlight_name = None  # виправлено відступ
        self.filter_status = "all"
        self.sort_activity = False
        await self.update_message(interaction)

# ===================== MODALS =====================
class HighlightModal(discord.ui.Modal, title="Підсвітити іншого користувача"):
    name = discord.ui.TextInput(label="Введіть нік", style=discord.TextStyle.short)

    def __init__(self, view: GuildStatusView):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.view_ref.refresh_data()
        cleaned_input = get_canonical_name(clean_name(self.name.value.strip()))
        i_name = self.view_ref.col_idx.get("name", 1)
        table_names = [get_canonical_name(clean_name(r[i_name])) for r in self.view_ref.data if len(r) > i_name]
        if cleaned_input in table_names:
            self.view_ref.highlight_name = cleaned_input
            self.view_ref.page = 0
            await self.view_ref.update_message(interaction)
        else:
            await interaction.followup.send(f"❌ Користувача `{cleaned_input}` не знайдено в таблиці.", ephemeral=True)

class DateModal(discord.ui.Modal, title="Змінити дату"):
    date_input = discord.ui.TextInput(
        label="Введіть дату (ДД.ММ.РРРР)",
        style=discord.TextStyle.short,
        placeholder=datetime.now().strftime("%d.%m.%Y"),
    )

    def __init__(self, view: GuildStatusView):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_date = datetime.strptime(self.date_input.value.strip(), "%d.%m.%Y")
            self.view_ref.created_date = new_date.strftime("%d.%m.%Y")
            await self.view_ref.update_message(interaction)
        except ValueError:
            await interaction.response.send_message("❌ Неправильний формат дати. Використовуйте ДД.ММ.РРРР", ephemeral=True)

class RenameModal(discord.ui.Modal, title="Перейменувати користувача"):
    old_name = discord.ui.TextInput(label="Поточне ім'я (як у таблиці)", style=discord.TextStyle.short)
    new_name = discord.ui.TextInput(label="Нове канонічне ім'я", style=discord.TextStyle.short)

    def __init__(self, view: GuildStatusView):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        i_name = self.view_ref.col_idx.get("name", 1)
        old_clean = get_canonical_name(clean_name(self.old_name.value.strip()))
        new_clean = clean_name(self.new_name.value.strip())
        if not new_clean:
            return await interaction.followup.send("⚠️ Невірне нове ім'я.", ephemeral=True)

        changed = 0
        for r in self.view_ref.data:
            if len(r) > i_name and get_canonical_name(clean_name(r[i_name])) == old_clean:
                r[i_name] = new_clean
                changed += 1

        ALIASES.setdefault("aliases", {})[old_clean.lower()] = new_clean
        save_json(ALIAS_FILE, ALIASES)

        if self.view_ref.source == "ocr" and self.view_ref.ocr_week and self.view_ref.ocr_week in OCR_DB.get("weeks", {}):
            bucket = OCR_DB["weeks"][self.view_ref.ocr_week]
            agg = bucket.get("aggregate", bucket)
            if old_clean in agg and new_clean not in agg:
                agg[new_clean] = agg.pop(old_clean)
            elif old_clean in agg and new_clean in agg:
                old_rec = agg.pop(old_clean)
                new_rec = agg[new_clean]
                new_rec["activity"] = max(parse_int(new_rec.get("activity", 0)), parse_int(old_rec.get("activity", 0)))
                if not new_rec.get("status") and old_rec.get("status"):
                    new_rec["status"] = old_rec["status"]
            save_json(OCR_FILE, OCR_DB)

        await self.view_ref.update_message(interaction)
        await interaction.followup.send(f"✅ Перейменовано **{old_clean} → {new_clean}** (змінено рядків: {changed}).", ephemeral=True)

# ===== Нові модалка/в’ю для завантажень =====
class WeekDateModal(discord.ui.Modal, title="Параметри OCR (тиждень і дата)"):
    week = discord.ui.TextInput(label="Тиждень (понеділок, ДД.ММ.РРРР)", required=True)
    display_date = discord.ui.TextInput(label="Дата відображення (ДД.ММ.РРРР)", required=True)

    def __init__(self, cog: "GuildStatusCog", image: discord.Attachment, suggest_date: date):
        super().__init__(timeout=180)
        self.cog = cog
        self.image = image
        self.week.default = _week_label_from_date(suggest_date)
        self.display_date  # страховка локалі

    async def on_submit(self, interaction: discord.Interaction):
        # валідація дат
        try:
            week_d = _parse_date_ddmmyyyy(self.week.value)
            disp_d = _parse_date_ddmmyyyy(self.display_date.value)
        except Exception:
            return await interaction.response.send_message("❌ Формат має бути ДД.ММ.РРРР.", ephemeral=True)

        week_key = _week_label_from_date(week_d)

        # OCR першого скріна
        txt = await _run_ocr_on_image(self.image)
        if not txt:
            return await interaction.response.send_message("⚠️ OCR недоступний або файл не є зображенням (потрібні pillow+pytesseract).", ephemeral=True)
        parsed = _parse_ocr_text_to_rows(txt)
        # антидублі в межах цього завантаження
        parsed = self.cog._dedupe_parsed_batch(parsed)

        added, total = self.cog._merge_parsed_into_week(parsed, week_key, interaction.user.id)
        # збережемо display_date
        OCR_DB["weeks"][week_key]["display_date"] = disp_d.strftime("%d.%m.%Y")
        save_json(OCR_FILE, OCR_DB)

        # Кнопки: додати ще / завершити
        sess = UploadSession(
            user_id=interaction.user.id,
            channel_id=interaction.channel_id,
            week_key=week_key,
            display_date=disp_d.strftime("%d.%m.%Y"),
            expires_at=datetime.utcnow() + timedelta(minutes=3),
        )
        self.cog.upload_sessions[interaction.user.id] = sess

        view = UploadMoreView(self.cog, sess)
        await interaction.response.send_message(
            f"✅ Додано {added} запис(ів) у тиждень **{week_key}** (усього в aggregate: {total}). "
            "Додати ще скрін?",
            view=view,
            ephemeral=True,
        )

class UploadMoreView(discord.ui.View):
    def __init__(self, cog: "GuildStatusCog", sess: UploadSession):
        super().__init__(timeout=180)
        self.cog = cog
        self.sess = sess

    @discord.ui.button(label="➕ Додати ще скрін", style=discord.ButtonStyle.primary)
    async def add_more(self, interaction: discord.Interaction, button: discord.ui.Button):
        # продовжуємо сесію на 3 хв
        self.sess.expires_at = datetime.utcnow() + timedelta(minutes=3)
        self.cog.upload_sessions[self.sess.user_id] = self.sess
        await interaction.response.send_message(
            "⬆️ Кинь **ще один скрін** як звичайне повідомлення у цьому каналі (PNG/JPG). Сесія активна 3 хвилини.",
            ephemeral=True,
        )

    @discord.ui.button(label="✅ Завершити", style=discord.ButtonStyle.success)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.upload_sessions.pop(self.sess.user_id, None)
        await interaction.response.send_message(
            f"🏁 Готово. Додатково додано: **{self.sess.added}** скрін(ів).",
            ephemeral=True,
        )

    @discord.ui.button(label="✖ Скасувати", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.upload_sessions.pop(self.sess.user_id, None)
        await interaction.response.send_message("❎ Сесію завантаження скасовано.", ephemeral=True)

# ===================== COG =====================
class GuildStatusCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._view_registered = False
        self.upload_sessions: Dict[int, UploadSession] = {}
        logger.debug("[guildstatus] Cog ініціалізовано")

    @commands.Cog.listener()
    async def on_ready(self):
        # Регіструємо persistent view тільки один раз
        if not self._view_registered:
            self.bot.add_view(GuildStatusView([], 0))
            self._view_registered = True
            logger.debug("[guildstatus] Persistent View зареєстровано")

    # ---- СЛУХАЧ ДЛЯ ДОДАТКОВИХ СКРІНІВ ----
    @commands.Cog.listener("on_message")
    async def _listen_more_uploads(self, message: discord.Message):
        if message.author.bot:
            return
        sess = self.upload_sessions.get(message.author.id)
        if not sess:
            return
        if datetime.utcnow() > sess.expires_at or message.channel.id != sess.channel_id:
            self.upload_sessions.pop(message.author.id, None)
            return
        if not message.attachments:
            return

        processed = False
        for att in message.attachments:
            ct = (att.content_type or "").lower()
            if not (ct.startswith("image") or att.filename.lower().endswith((".png", ".jpg", ".jpeg"))):
                continue
            txt = await _run_ocr_on_image(att)
            if not txt:
                continue
            parsed = _parse_ocr_text_to_rows(txt)
            # антидублі в межах цього завантаження
            parsed = self._dedupe_parsed_batch(parsed)
            if not parsed:
                continue
            self._merge_parsed_into_week(parsed, sess.week_key, message.author.id)
            sess.added += 1
            processed = True

        if processed:
            try:
                ack = await message.reply(f"✅ Додано до **{sess.week_key}**. (Разом у цій сесії: {sess.added})")
                await asyncio.sleep(5)
                await ack.delete()
            except Exception:
                pass

    # ---- Утиліта мерджу в базу ----
    def _merge_parsed_into_week(self, parsed: Dict[str, Dict[str, str]], week_key: str, uploader_id: int) -> Tuple[int, int]:
        OCR_DB.setdefault("weeks", {}).setdefault(week_key, {})
        bucket = OCR_DB["weeks"][week_key]
        agg = bucket.setdefault("aggregate", {})
        uploads = bucket.setdefault("uploads", [])

        upload_entry = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "uploader": str(uploader_id),
            "count": len(parsed),
            "data": parsed,
        }
        uploads.append(upload_entry)

        for name, rec in parsed.items():
            canon = get_canonical_name(clean_name(name))
            new_act  = parse_int(rec.get("activity", 0))
            new_stat = rec.get("status", "")
            if canon in agg:
                old = agg[canon]
                old_act = parse_int(old.get("activity", 0))
                agg[canon] = {
                    "activity": max(old_act, new_act),
                    "status": old.get("status") or new_stat,
                }
            else:
                agg[canon] = {"activity": new_act, "status": new_stat}

        save_json(OCR_FILE, OCR_DB)
        return len(parsed), len(agg)

    # ---- Дедуп у межах одного завантаження ----
    def _dedupe_parsed_batch(self, parsed: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        """
        Знімає дублікати в ОДНОМУ завантаженні:
        - clean_name + alias → канон
        - однакові _norm_key() зливаються: activity = max, статус = перший не-порожній
        """
        bucket: Dict[str, Dict[str, str]] = {}

        for raw_name, rec in parsed.items():
            canon = get_canonical_name(clean_name(raw_name))
            key = _norm_key(canon)

            act = parse_int(rec.get("activity", 0))
            status = rec.get("status", "")

            if key not in bucket:
                bucket[key] = {"name": canon, "activity": act, "status": status}
            else:
                if act > parse_int(bucket[key]["activity"]):
                    bucket[key]["activity"] = act
                if not bucket[key].get("status") and status:
                    bucket[key]["status"] = status

        return {v["name"]: {"activity": v["activity"], "status": v.get("status", "")} for v in bucket.values()}

    # ---- MOD: Завантажити скрін й записати OCR (з модалкою) ----
    @app_commands.command(name="guildstatus_upload", description="[MOD] Завантажити скрін і зчитати OCR")
    @app_commands.describe(image="Скрін таблиці активності (PNG/JPG)")
    async def guildstatus_upload(self, interaction: discord.Interaction, image: discord.Attachment):
        if interaction.channel_id != MOD_CHANNEL_ID:
            return await interaction.response.send_message("⛔ Ця команда доступна лише в каналі модераторів.", ephemeral=True)

        ct = (image.content_type or "").lower()
        if not (ct.startswith("image") or image.filename.lower().endswith((".png", ".jpg", ".jpeg"))):
            return await interaction.response.send_message("❌ Прикріпи PNG або JPG.", ephemeral=True)

        suggest = date.today()
        modal = WeekDateModal(self, image, suggest)
        await interaction.response.send_modal(modal)

    # ---- Показати статус ----
    @app_commands.command(name="guildstatus", description="Показати активність учасників гільдії")
    @app_commands.describe(
        date="Дата для заголовка (ДД.ММ.РРРР). Якщо порожньо — сьогодні або display_date з OCR.",
        source="Джерело даних: google або ocr",
        week="(для OCR) Мітка тижня. Якщо порожньо — останній доступний",
    )
    @app_commands.choices(source=[
        app_commands.Choice(name="google", value="google"),
        app_commands.Choice(name="ocr", value="ocr"),
    ])
    async def guildstatus(self, interaction: discord.Interaction, date: Optional[str] = None, source: Optional[app_commands.Choice[str]] = None, week: Optional[str] = None):
        logger.debug(f"[guildstatus] Викликана команда /guildstatus від {interaction.user}")
        start_time = datetime.now()

        custom_date = None
        if date:
            try:
                custom_date = datetime.strptime(date.strip(), "%d.%m.%Y").strftime("%d.%m.%Y")
            except ValueError:
                return await interaction.response.send_message("❌ Неправильний формат дати. Використовуйте ДД.ММ.РРРР", ephemeral=True)

        try:
            src = (source.value if source else "google")
            if src == "ocr":
                week_key = (week or _latest_week_key())
                if not week_key or week_key not in OCR_DB.get("weeks", {}):
                    return await interaction.response.send_message("📭 Немає OCR-даних. Завантаж скріни через /guildstatus_upload.", ephemeral=True)
                bucket = OCR_DB["weeks"][week_key]
                agg = bucket.get("aggregate", bucket)  # fallback для застарілого формату
                rows = [[name, str(rec.get("activity", 0)), rec.get("status", "")] for name, rec in agg.items()]
                indices = {"name": 0, "activity": 1, "status": 2}
                # якщо дату не задали — беремо з display_date, якщо є
                if not custom_date:
                    custom_date = bucket.get("display_date")
            else:
                rows, indices = await fetch_csv_smart()
                if not rows:
                    rows = await fetch_csv_direct()
                    indices = {"name": 1, "activity": 2, "status": 7}
                week_key = None

            view = GuildStatusView(
                rows,
                total_members=len(rows),
                user=interaction.user,
                custom_date=custom_date,
                col_idx=indices,
                source=src,
                week_key=week_key,
            )
            table, footer_text = view.format_page()

            embed = discord.Embed(
                title=f"📊 Активність учасників 𝗦𝗶𝗹𝗲𝗻𝘁 𝗖𝗼𝘃𝗲 — {view.created_date}",
                description=table,
                color=discord.Color.green(),
            )
            bot_user = interaction.client.user if interaction.client else None
            if bot_user and bot_user.display_avatar:
                embed.set_footer(text=f"Silent Concierge by Myxa | {footer_text}", icon_url=bot_user.display_avatar.url)
            else:
                embed.set_footer(text=f"Silent Concierge by Myxa | {footer_text}")

            await interaction.response.send_message(embed=embed, view=view)
            msg = await interaction.original_response()
            view.message_id = msg.id
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.debug(f"[guildstatus] Ембед відправлено і message_id збережено за {elapsed:.2f}с")
        except Exception as e:
            logger.error(f"[guildstatus] Помилка виконання /guildstatus: {e}")
            try:
                await interaction.response.send_message("⚠️ Сталася помилка при формуванні статусу.", ephemeral=True)
            except Exception:
                pass


def update_google_sheet(current_week: str, data: dict):
    spreadsheet = gs_client.open_by_key(GSHEET_ID)
    sheets = spreadsheet.worksheets()
    prev_sheet = sheets[-1] if sheets else None

    new_sheet = spreadsheet.add_worksheet(title=current_week, rows="200", cols="10")
    headers = [
        "Позиція",
        "Родина (Персонаж)",
        f"Очки активності ({current_week})",
        f"Очки активності ({prev_sheet.title if prev_sheet else '-'})",
        "Δ Різниця",
        "Статус",
    ]
    new_sheet.append_row(headers)

    prev_data = {}
    if prev_sheet:
        prev_rows = prev_sheet.get_all_records()
        for r in prev_rows:
            name = r.get("Родина (Персонаж)")
            if not name:
                continue
            prev_data[name] = int(
                r.get(f"Очки активності ({prev_sheet.title})") or r.get("Очки активності") or 0
            )

    for i, (name, rec) in enumerate(data.items(), start=1):
        curr = int(rec.get("activity", 0))
        prev = prev_data.get(name, 0)
        diff = curr - prev
        status = rec.get("status", "")
        new_sheet.append_row([i, name, curr, prev, diff, status])


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildStatusCog(bot))
    logger.debug("[guildstatus] Cog додано до бота")
