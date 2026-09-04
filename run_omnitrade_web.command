#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
API_URL="http://127.0.0.1:8788"
FRONTEND_URL="http://127.0.0.1:3000"
APP_URL="$FRONTEND_URL/overview"
API_LOG="/tmp/omnitrade-api.log"

cd "$ROOT_DIR"

echo "OmniTrade Web"
echo "============="
echo ""

if [[ ! -x "$ROOT_DIR/.venv/bin/uvicorn" ]]; then
  echo "Python environment is missing."
  echo "Run:"
  echo "  cd \"$ROOT_DIR\""
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/pip install -r requirements.txt"
  read -r -p "Press Return to close..."
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Frontend dependencies are missing."
  echo "Run:"
  echo "  cd \"$FRONTEND_DIR\""
  echo "  npm install"
  read -r -p "Press Return to close..."
  exit 1
fi

if ! /usr/bin/curl -s --max-time 5 "$API_URL/api/health" >/dev/null 2>&1; then
  echo "Starting FastAPI on $API_URL ..."
  "$ROOT_DIR/run_api.sh" --no-reload >"$API_LOG" 2>&1 &

  for _ in $(seq 1 30); do
    if /usr/bin/curl -s --max-time 5 "$API_URL/api/health" >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done
else
  echo "FastAPI is already running on $API_URL"
fi

if ! /usr/bin/curl -s --max-time 5 "$API_URL/api/health" >/dev/null 2>&1; then
  echo "FastAPI did not start. Check $API_LOG"
  read -r -p "Press Return to close..."
  exit 1
fi

if /usr/bin/curl -s --max-time 5 "$FRONTEND_URL/overview" >/dev/null 2>&1; then
  echo "Frontend is already running on $FRONTEND_URL"
  /usr/bin/open "$APP_URL"
  echo "Opened $APP_URL"
  read -r -p "Press Return to close..."
  exit 0
fi

echo "Starting Next frontend on $FRONTEND_URL ..."
echo "Using API backend $API_URL"
(
  for _ in $(seq 1 60); do
    if /usr/bin/curl -s --max-time 5 "$FRONTEND_URL/overview" >/dev/null 2>&1; then
      /usr/bin/open "$APP_URL"
      exit 0
    fi
    sleep 1
  done
) &

cd "$FRONTEND_DIR"
NEXT_PUBLIC_OMNITRADE_API_URL="$API_URL" npm run dev
