# config/loader.py
from __future__ import annotations

from pathlib import Path
import os
import json
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]   # корінь проєкту
CFG = Path(__file__).resolve().parent        # папка config

CANDIDATES = [
    ROOT / ".env",
    CFG / ".env.main",
    CFG / ".env",
    CFG / ".env.local",
]

def _load_all() -> list[str]:
    loaded: list[str] = []
    for p in CANDIDATES:
        if p.exists():
            load_dotenv(p, override=True)
            loaded.append(str(p))
    return loaded

def _require(name: str) -> str:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        where = ", ".join([str(p) for p in CANDIDATES if p.exists()]) or "no .env found"
        raise RuntimeError(f"Missing env var {name}. Put it into one of: {where}")
    return str(value).strip()

_loaded = _load_all()

DISCORD_TOKEN = _require("DISCORD_TOKEN")

def _get_int(name: str, default: int = 0) -> int:
    v = os.getenv(name)
    if v is None or not str(v).strip():
        return default
    try:
        return int(str(v).strip())
    except ValueError:
        raise RuntimeError(f"{name} must be an integer")

def _get_int_list(name: str) -> list[int]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return []
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            raise RuntimeError(f"{name} must be a comma-separated list of integers")
    return out

GUILD_ID = _get_int("GUILD_ID", 0)
APPLICATION_ID = os.getenv("APPLICATION_ID")
CLIENT_ID = os.getenv("CLIENT_ID")

# ================= JSON CONFIG LOADER =================

def load_json(filename: str) -> dict:
    """
    Завжди читає JSON з папки config незалежно від того,
    звідки запустили бота (Render або локально).
    """
    path = CFG / filename
    if not path.exists():
        raise FileNotFoundError(f"[config] Missing file: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_json_optional(filename: str, default):
    """
    Не валить старт, якщо файла нема. Повертає default.
    """
    path = CFG / filename
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

# Обовязкові (якщо хочеш, щоб падало коли нема файла):
STATUSES = load_json("statuses.json")
STATUS_PHRASES = load_json("status_phrases.json")

# Опціонально (можеш зробити обовязковим, якщо хочеш):
TIMEZONES = load_json_optional("timezones.json", {})

def debug_print():
    print("[env] loaded:", _loaded)
    print("[env] GUILD_ID:", GUILD_ID)
    token = DISCORD_TOKEN
    print("[env] TOKEN:", f"{token[:6]}.. ({len(token)} chars)")

    # Діагностика JSON
    try:
        print("[json] statuses keys:", list(STATUSES.keys()))
    except Exception as e:
        print("[json][FAIL] STATUSES:", type(e).__name__, str(e))

    try:
        print("[json] status_phrases keys:", list(STATUS_PHRASES.keys()))
    except Exception as e:
        print("[json][FAIL] STATUS_PHRASES:", type(e).__name__, str(e))

    try:
        if isinstance(TIMEZONES, dict):
            print("[json] timezones entries:", len(TIMEZONES))
        else:
            print("[json] timezones type:", type(TIMEZONES).__name__)
    except Exception as e:
        print("[json][FAIL] TIMEZONES:", type(e).__name__, str(e))
