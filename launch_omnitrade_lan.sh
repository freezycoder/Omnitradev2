#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
API_HOST="0.0.0.0"
API_LOG="/tmp/omnitrade-api-lan.log"
FRONTEND_LOG="/tmp/omnitrade-frontend-lan.log"
LAUNCHER_LOG="/tmp/omnitrade-lan-launcher.log"

alert() {
  /usr/bin/osascript -e "display alert \"OmniTrade\" message \"$1\" as critical" >/dev/null 2>&1 || true
}

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

{
  echo "[$(date)] Launching OmniTrade on the local network"

  LAN_IP="$(detect_lan_ip)"
  if [[ -z "$LAN_IP" ]]; then
    alert "I could not find this Mac's Wi-Fi IP address. Connect to Wi-Fi and try again."
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
    alert "Python environment is missing. Run: cd $ROOT_DIR && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
  fi

  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    alert "Frontend dependencies are missing. Run: cd $FRONTEND_DIR && npm install"
    exit 1
  fi

  if ! /usr/bin/curl -s --max-time 5 "$API_URL/api/health" >/dev/null 2>&1; then
    echo "Starting API on $API_URL ..."
    "$ROOT_DIR/run_api.sh" --host "$API_HOST" --port "$API_PORT" --no-reload >"$API_LOG" 2>&1 &
  fi

  if ! wait_for_url "$API_URL/api/health" 24 2; then
    alert "The LAN API did not start. Log: $API_LOG"
    exit 1
  fi

  if ! /usr/bin/curl -s --max-time 5 "$FRONTEND_URL/overview" >/dev/null 2>&1; then
    echo "Starting frontend on $FRONTEND_URL ..."
    (
      cd "$FRONTEND_DIR"
      NEXT_PUBLIC_OMNITRADE_API_URL="$API_URL" npm run dev:lan -- --port "$FRONTEND_PORT" >"$FRONTEND_LOG" 2>&1
    ) &
  fi

  if ! wait_for_url "$FRONTEND_URL/overview" 30 2; then
    alert "The LAN frontend did not start. Log: $FRONTEND_LOG"
    exit 1
  fi

  printf "%s" "$APP_URL" | /usr/bin/pbcopy || true
  /usr/bin/open "$APP_URL"
  /usr/bin/osascript -e "display notification \"Phone URL copied: $APP_URL\" with title \"OmniTrade\"" >/dev/null 2>&1 || true

  if [[ "${OMNITRADE_KEEPALIVE:-0}" == "1" ]]; then
    while /usr/bin/curl -s --max-time 5 "$FRONTEND_URL/overview" >/dev/null 2>&1; do
      sleep 30
    done
  fi
} >>"$LAUNCHER_LOG" 2>&1
