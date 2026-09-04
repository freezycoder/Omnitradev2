#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
API_LOG="/tmp/omnitrade-api-lan.log"

detect_lan_ip() {
  if [[ -n "${OMNITRADE_LAN_IP:-}" ]]; then
    echo "$OMNITRADE_LAN_IP"
    return 0
  fi

  for interface in en0 en1; do
    local ip
    ip="$(/usr/sbin/ipconfig getifaddr "$interface" 2>/dev/null || true)"
    if [[ -n "$ip" ]]; then
      echo "$ip"
      return 0
    fi
  done

  /sbin/ifconfig | /usr/bin/awk '/inet / && $2 !~ /^127\./ { print $2; exit }'
}

port_is_listening() {
  /usr/sbin/lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

pick_port() {
  local port="$1"
  while port_is_listening "$port"; do
    port=$((port + 1))
  done
  echo "$port"
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

cd "$ROOT_DIR"

echo "OmniTrade Phone/LAN"
echo "==================="
echo ""

LAN_IP="$(detect_lan_ip)"
if [[ -z "$LAN_IP" ]]; then
  echo "Could not find this Mac's Wi-Fi IP address."
  echo "Connect the Mac and phone to the same Wi-Fi network, then try again."
  read -r -p "Press Return to close..."
  exit 1
fi

API_PORT="${OMNITRADE_API_PORT:-8788}"
FRONTEND_PORT="${OMNITRADE_FRONTEND_PORT:-3000}"

if ! /usr/bin/curl -s --max-time 5 "http://$LAN_IP:$API_PORT/api/health" >/dev/null 2>&1; then
  if port_is_listening "$API_PORT"; then
    API_PORT="$(pick_port $((API_PORT + 1)))"
  fi
fi

if ! /usr/bin/curl -s --max-time 5 "http://$LAN_IP:$FRONTEND_PORT/overview" >/dev/null 2>&1; then
  if port_is_listening "$FRONTEND_PORT"; then
    FRONTEND_PORT="$(pick_port $((FRONTEND_PORT + 1)))"
  fi
fi

API_URL="http://$LAN_IP:$API_PORT"
FRONTEND_URL="http://$LAN_IP:$FRONTEND_PORT"
APP_URL="$FRONTEND_URL/overview"

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
  "$ROOT_DIR/run_api.sh" --host 0.0.0.0 --port "$API_PORT" --no-reload >"$API_LOG" 2>&1 &
else
  echo "FastAPI is already available on $API_URL"
fi

if ! wait_for_url "$API_URL/api/health" 30 2; then
  echo "FastAPI did not start. Check $API_LOG"
  read -r -p "Press Return to close..."
  exit 1
fi

echo ""
echo "Phone URL:"
echo "  $APP_URL"
echo ""
echo "The URL was copied to your clipboard. Keep this Terminal window open."
printf "%s" "$APP_URL" | /usr/bin/pbcopy || true
/usr/bin/open "$APP_URL" || true

cd "$FRONTEND_DIR"
NEXT_PUBLIC_OMNITRADE_API_URL="$API_URL" npm run dev:lan -- --port "$FRONTEND_PORT"
