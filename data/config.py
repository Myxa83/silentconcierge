import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")  # токен бота
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0"))
MODER_CHANNEL_ID = int(os.getenv("MODER_CHANNEL_ID", "0"))

ALLOWED_ROLE_IDS = [int(rid) for rid in os.getenv("ALLOWED_ROLE_IDS", "").split(",") if rid]
ALLOWED_CHANNEL_IDS = [int(cid) for cid in os.getenv("ALLOWED_CHANNEL_IDS", "").split(",") if cid]

BAN_CHANNEL_ID = int(os.getenv("BAN_CHANNEL_ID", "0"))
TAPOCHOK_ROLE_ID = int(os.getenv("TAPOCHOK_ROLE_ID", "0"))

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
MODERATOR_ROLE_ID = int(os.getenv("MODERATOR_ROLE_ID", "0"))
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", "0"))

# дефолтні параметри для ембеду велла
DEFAULT_WHISPER = "Myxa"
DEFAULT_SERVER = "Kamasylvia 5"
DEFAULT_CTG = "Так"
DEFAULT_PLACE = "Око Окілу"

SIEGE_CHANNEL_ID = int(os.getenv("SIEGE_CHANNEL_ID", "0"))
BOSS_CHANNEL_ID = int(os.getenv("BOSS_CHANNEL_ID", "0"))
GUILD_BOSS_CHANNEL_ID = int(os.getenv("GUILD_BOSS_CHANNEL_ID", "0"))