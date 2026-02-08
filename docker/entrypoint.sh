#!/usr/bin/env bash
set -euo pipefail

cd /app/backend

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8503}"

# Install Python requirements on startup (useful when the repo is bind-mounted).
# Can be disabled by setting INSTALL_REQUIREMENTS=0.
INSTALL_REQUIREMENTS="${INSTALL_REQUIREMENTS:-1}"
if [[ "${INSTALL_REQUIREMENTS}" != "0" ]]; then
  python -m pip install --no-cache-dir -r requirements.txt
fi

# Create secret key file on the mounted volume if missing
if [[ ! -f .webui_secret_key ]]; then
  head -c 12 /dev/random | base64 > .webui_secret_key
fi

export PYTHONPATH=.
export WEBUI_SECRET_KEY="$(cat .webui_secret_key)"

exec python -m uvicorn open_webui.main:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --reload
