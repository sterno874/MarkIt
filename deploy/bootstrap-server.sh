#!/usr/bin/env bash
# One-time setup on the Oracle VM (same host as Research Desk).
# Run as ubuntu with sudo:  bash bootstrap-server.sh
set -euo pipefail

APP_ROOT=/opt/markit
DATA_ROOT=/var/lib/markit
ENV_FILE=/etc/markit.env

sudo mkdir -p "$APP_ROOT" "$DATA_ROOT/data/tickets"
sudo chown -R ubuntu:ubuntu "$APP_ROOT" "$DATA_ROOT"

# Placeholder only — CI overwrites this from GitHub Secrets on every main deploy.
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
DATA_DIR=/var/lib/markit/data
DATABASE_PATH=/var/lib/markit/data/desk.db
EOF
  sudo chmod 600 "$ENV_FILE"
  sudo chown root:root "$ENV_FILE"
  echo "Created placeholder $ENV_FILE — CI will overwrite it from GitHub Secrets."
else
  echo "$ENV_FILE already exists — CI will overwrite it on the next main deploy."
fi

# uv installs a modern CPython under ~/.local — system python stays 3.8.
if [[ ! -x "$HOME/.local/bin/uv" ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

echo
echo "Next:"
echo "  1. Add GitHub Secrets on sterno874/MarkIt: DEPLOY_SSH_KEY, DISCORD_TOKEN,"
echo "     DISCORD_GUILD_ID (one or more ids, comma-separated), optional GEMINI_API_KEY"
echo "  2. Push to main — CI writes $ENV_FILE, publishes to $APP_ROOT/current, restarts markit"
echo "  3. Invite the bot to your Discord server (scopes: bot + applications.commands)"
