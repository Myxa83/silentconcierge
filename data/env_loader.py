# config/loader.py
from pathlib import Path
import os
from dotenv import load_dotenv

# Шляхи
ROOT = Path(__file__).resolve().parents[1]   # корінь проєкту (де лежить bot.py)
CFG  = Path(__file__).resolve().parent       # папка config/

# Порядок підхоплення .env (пізніший ПЕРЕЗАПИСУЄ ранній)
CANDIDATES = [
    ROOT / ".env",          # опціонально, якщо колись буде
    CFG  / ".env.main",     # твій існуючий файл (нижчий пріоритет)
    CFG  / ".env",          # основний
    CFG  / ".env.local",    # локальні оверрайди (найвищий)
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
    if not value or not str(value).strip():
        where = ", ".join([str(p) for p in CANDIDATES if p.exists()]) or "—"
        raise RuntimeError(f"❌ Missing env var {name}. Put it into one of: {where}")
    return str(value).strip()

_loaded = _load_all()

# Обов’язкові змінні
DISCORD_TOKEN = _require("DISCORD_TOKEN")
try:
    GUILD_ID = int(_require("GUILD_ID"))
except ValueError:
    raise RuntimeError("❌ GUILD_ID must be a numeric Discord Server ID.")

# Опційні
APPLICATION_ID = os.getenv("APPLICATION_ID")
CLIENT_ID      = os.getenv("CLIENT_ID")

def debug_print():
    print("[env] loaded:", _loaded)
    print("[env] GUILD_ID:", GUILD_ID)
    token = DISCORD_TOKEN
    print("[env] TOKEN:", f"{token[:6]}… ({len(token)} chars)")