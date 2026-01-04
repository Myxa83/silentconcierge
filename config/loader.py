# config/loader.py
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]   # корінь проєкту
CFG = Path(__file__).resolve().parent        # папка config

CANDIDATES = [
    ROOT / ".env",
    CFG / ".env.main",
    CFG / ".env",
    CFG / ".env.local",
]

def _load_all():
    loaded = []
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
    out = []
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

def debug_print():
    print("[env] loaded:", _loaded)
    print("[env] GUILD_ID:", GUILD_ID)
    token = DISCORD_TOKEN
    print("[env] TOKEN:", f"{token[:6]}.. ({len(token)} chars)")
