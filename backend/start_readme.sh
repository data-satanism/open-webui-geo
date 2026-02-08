#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8503}"

if [ ! -d "venv" ]; then
  python3.10 -m venv venv
fi

./venv/bin/python3.10 -m pip install -r requirements.txt

if [ ! -f ".webui_secret_key" ]; then
  echo "$(head -c 12 /dev/random | base64)" > .webui_secret_key
fi

PYTHONPATH=. WEBUI_SECRET_KEY="$(cat .webui_secret_key)" \
  exec ./venv/bin/python3.10 -m uvicorn open_webui.main:app \
  --host="${HOST}" \
  --port="${PORT}" \
  --reload
