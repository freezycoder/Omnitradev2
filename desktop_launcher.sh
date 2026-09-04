#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
STREAMLIT_BIN="$ROOT_DIR/.venv/bin/streamlit"
APP_FILE="$ROOT_DIR/app.py"
HOST="127.0.0.1"
PORT="8501"
URL="http://$HOST:$PORT"
LOG_FILE="/tmp/omnitrade-desktop.log"

if [[ ! -x "$STREAMLIT_BIN" ]]; then
  osascript -e 'display alert "OmniTrade setup incomplete" message "The project virtual environment is missing. Open Terminal in the OmniTrade repository and install dependencies first." as critical'
  exit 1
fi

if ! curl -s "$URL" >/dev/null 2>&1; then
  nohup "$STREAMLIT_BIN" run "$APP_FILE" --server.address "$HOST" --server.port "$PORT" --server.headless true >"$LOG_FILE" 2>&1 &

  for _ in $(seq 1 20); do
    sleep 1
    if curl -s "$URL" >/dev/null 2>&1; then
      break
    fi
  done
fi

open "$URL"
