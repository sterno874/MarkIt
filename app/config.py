import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "desk.db"))
TZ = ZoneInfo(os.environ.get("TZ", "America/New_York"))

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
_guild = os.environ.get("DISCORD_GUILD_ID", "").strip()
GUILD_ID = int(_guild) if _guild else None

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"

SEC_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT",
    "market-desk/1.0 (set SEC_USER_AGENT to your email)",
).strip()

_port = os.environ.get("WEBHOOK_PORT", "").strip()
WEBHOOK_PORT = int(_port) if _port else 0
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()

MORNING_HHMM = os.environ.get("MORNING_HHMM", "08:00").strip()
CLOSE_HHMM = os.environ.get("CLOSE_HHMM", "16:15").strip()
