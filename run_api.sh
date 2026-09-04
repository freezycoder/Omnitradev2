#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_UVICORN="$ROOT_DIR/.venv/bin/uvicorn"

HOST="127.0.0.1"
PORT="8788"
RELOAD="true"

print_help() {
  cat <<'EOF'
OmniTrade API launcher

Usage:
  ./run_api.sh [options]

Options:
  --host HOST      FastAPI host (default: 127.0.0.1)
  --port PORT      FastAPI port (default: 8788)
  --no-reload      Disable Uvicorn reload
  --help           Show this help

Examples:
  ./run_api.sh
  ./run_api.sh --port 8790
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      [[ $# -ge 2 ]] || { echo "Missing value for --host" >&2; exit 1; }
      HOST="$2"
      shift 2
      ;;
    --port)
      [[ $# -ge 2 ]] || { echo "Missing value for --port" >&2; exit 1; }
      PORT="$2"
      shift 2
      ;;
    --no-reload)
      RELOAD="false"
      shift
      ;;
    --help|-h)
      print_help
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "" >&2
      print_help >&2
      exit 1
      ;;
  esac
done

if [[ ! -x "$VENV_UVICORN" ]]; then
  echo "Virtual environment not found in $ROOT_DIR/.venv" >&2
  echo "Create it and install dependencies first:" >&2
  echo "  cd \"$ROOT_DIR\"" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

cd "$ROOT_DIR"

export ENV="${ENV:-development}"
export OMNITRADE_WRITE_MODE="${OMNITRADE_WRITE_MODE:-local}"

echo "Launching OmniTrade API"
echo "  URL: http://$HOST:$PORT"
echo "  Environment: $ENV"
echo "  Write mode: $OMNITRADE_WRITE_MODE"

if [[ "$RELOAD" == "true" ]]; then
  exec "$VENV_UVICORN" api.main:app --host "$HOST" --port "$PORT" --reload
fi

exec "$VENV_UVICORN" api.main:app --host "$HOST" --port "$PORT"
