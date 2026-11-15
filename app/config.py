import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", DATA_DIR / "desk.db"))
TZ = ZoneInfo(os.environ.get("TZ", "America/New_York"))

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()


def _parse_guild_ids(raw: str) -> list[int]:
    """Accept one id or a comma/space-separated list: `123,456` or `123 456`."""
    ids: list[int] = []
    seen: set[int] = set()
    for part in raw.replace(",", " ").split():
        part = part.strip()
        if not part:
            continue
        gid = int(part)
        if gid in seen:
            continue
        seen.add(gid)
        ids.append(gid)
    return ids


# Comma-separated Discord server ids for instant slash-command sync.
# Example: DISCORD_GUILD_ID=111,222,333
GUILD_IDS: list[int] = _parse_guild_ids(os.environ.get("DISCORD_GUILD_ID", "").strip())
GUILD_ID: int | None = GUILD_IDS[0] if GUILD_IDS else None  # first / legacy

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

# Live ticker pills — IB-style auto-refresh while the card is "hot".
LIVE_PILL_INTERVAL_SEC = int(os.environ.get("LIVE_PILL_INTERVAL_SEC", "20"))
LIVE_PILL_TTL_SEC = int(os.environ.get("LIVE_PILL_TTL_SEC", "720"))  # 12 minutes
LIVE_PILL_MAX = int(os.environ.get("LIVE_PILL_MAX", "40"))
