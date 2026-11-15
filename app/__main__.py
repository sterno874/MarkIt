import logging
import os

from dotenv import load_dotenv

load_dotenv()

from app.bot import DeskBot, configure_logging  # noqa: E402


def main() -> None:
    configure_logging()
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "DISCORD_TOKEN is missing. Copy .env.example to .env and paste the bot token."
        )
    DeskBot().run(token, log_handler=None)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
