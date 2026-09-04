#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
API_URL="http://127.0.0.1:8788"
FRONTEND_URL="http://127.0.0.1:3000"
APP_URL="$FRONTEND_URL/overview"
API_LOG="/tmp/omnitrade-api.log"
FRONTEND_LOG="/tmp/omnitrade-frontend.log"
LAUNCHER_LOG="/tmp/omnitrade-web-launcher.log"
API_PID=""
FRONTEND_PID=""

alert() {
  /usr/bin/osascript -e "display alert \"OmniTrade\" message \"$1\" as critical" >/dev/null 2>&1 || true
}

wait_for_url() {
  local url="$1"
  local attempts="$2"
  local delay_seconds="$3"

  for _ in $(seq 1 "$attempts"); do
    if /usr/bin/curl -s --max-time 5 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay_seconds"
  done

  return 1
}

{
  echo "[$(date)] Launching OmniTrade web app"

  if [[ ! -x "$ROOT_DIR/.venv/bin/uvicorn" ]]; then
    alert "Python environment is missing. Open Terminal and run: cd $ROOT_DIR && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
  fi

  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    alert "Frontend dependencies are missing. Open Terminal and run: cd $FRONTEND_DIR && npm install"
    exit 1
  fi

  if ! /usr/bin/curl -s --max-time 5 "$API_URL/api/health" >/dev/null 2>&1; then
    echo "Starting API..."
    "$ROOT_DIR/run_api.sh" --no-reload >"$API_LOG" 2>&1 &
    API_PID="$!"
  fi

  if ! wait_for_url "$API_URL/api/health" 24 2; then
    alert "The API did not start. Log: $API_LOG"
    exit 1
  fi

  if ! /usr/bin/curl -s --max-time 5 "$FRONTEND_URL/overview" >/dev/null 2>&1; then
    echo "Starting frontend..."
    (
      cd "$FRONTEND_DIR"
      NEXT_PUBLIC_OMNITRADE_API_URL="$API_URL" npm run dev >"$FRONTEND_LOG" 2>&1
    ) &
    FRONTEND_PID="$!"
  fi

  if ! wait_for_url "$FRONTEND_URL/overview" 30 2; then
    alert "The frontend did not start. Log: $FRONTEND_LOG"
    exit 1
  fi

  /usr/bin/open "$APP_URL"

  if [[ "${OMNITRADE_KEEPALIVE:-0}" == "1" ]]; then
    if [[ -n "$FRONTEND_PID" ]]; then
      wait "$FRONTEND_PID"
    else
      while /usr/bin/curl -s --max-time 5 "$FRONTEND_URL/overview" >/dev/null 2>&1; do
        sleep 30
      done
    fi
  fi
} >>"$LAUNCHER_LOG" 2>&1
