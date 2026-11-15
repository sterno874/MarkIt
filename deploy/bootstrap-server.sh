#!/usr/bin/env bash
# One-time setup on the Oracle VM (same host as Research Desk).
# Run as ubuntu with sudo:  bash bootstrap-server.sh
set -euo pipefail

APP_ROOT=/opt/markit
DATA_ROOT=/var/lib/markit
ENV_FILE=/etc/markit.env

sudo mkdir -p "$APP_ROOT" "$DATA_ROOT/data/tickets"
sudo chown -R ubuntu:ubuntu "$APP_ROOT" "$DATA_ROOT"

if [[ ! -f "$ENV_FILE" ]]; then
  sudo tee "$ENV_FILE" >/dev/null <<'EOF'
DISCORD_TOKEN=
DISCORD_GUILD_ID=
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.8-flash
SEC_USER_AGENT=markit/1.0 (you@example.com)
TZ=America/New_York
MORNING_HHMM=08:00
CLOSE_HHMM=16:15
EOF
  sudo chmod 600 "$ENV_FILE"
  sudo chown root:root "$ENV_FILE"
  echo "Created $ENV_FILE — edit it and paste DISCORD_TOKEN before starting the service."
else
  echo "$ENV_FILE already exists — left untouched."
fi

# uv installs a modern CPython under ~/.local — system python stays 3.8.
if [[ ! -x "$HOME/.local/bin/uv" ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

echo
echo "Next:"
echo "  1. sudo nano $ENV_FILE   # set DISCORD_TOKEN (+ optional GEMINI_API_KEY)"
echo "  2. Push to main on sterno874/MarkIt — CI publishes to $APP_ROOT/current"
echo "  3. Or manually: rsync the app tree, then: uv venv --python 3.13 .venv && uv pip install -r requirements.txt"
echo "  4. sudo cp deploy/markit.service /etc/systemd/system/ && sudo systemctl enable --now markit"
