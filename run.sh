#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
VENV_STREAMLIT="$ROOT_DIR/.venv/bin/streamlit"

HOST="127.0.0.1"
PORT="8501"
HEADLESS="false"
DEFAULT_MODE_LABEL="Auto"
DEFAULT_PAGE="Overview"
DEFAULT_TICKER="AAPL"
DEFAULT_TICKER_UPPER="AAPL"

print_help() {
  cat <<'EOF'
OmniTrade launcher

Usage:
  ./run.sh [options]

Options:
  --demo               Start the app with Demo Only selected by default
  --auto               Start the app with Auto selected by default
  --page PAGE          Default page on first load
  --ticker SYMBOL      Default ticker on first load
  --port PORT          Streamlit port (default: 8501)
  --host HOST          Streamlit host (default: 127.0.0.1)
  --headless           Run without auto-opening a browser
  --help               Show this help

Examples:
  ./run.sh
  ./run.sh --demo --ticker NVDA --page "Ticker Analysis"
  ./run.sh --port 8510 --host 0.0.0.0
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --demo)
      DEFAULT_MODE_LABEL="Demo Only"
      shift
      ;;
    --auto)
      DEFAULT_MODE_LABEL="Auto"
      shift
      ;;
    --page)
      [[ $# -ge 2 ]] || { echo "Missing value for --page" >&2; exit 1; }
      DEFAULT_PAGE="$2"
      shift 2
      ;;
    --ticker)
      [[ $# -ge 2 ]] || { echo "Missing value for --ticker" >&2; exit 1; }
      DEFAULT_TICKER="$2"
      shift 2
      ;;
    --port)
      [[ $# -ge 2 ]] || { echo "Missing value for --port" >&2; exit 1; }
      PORT="$2"
      shift 2
      ;;
    --host)
      [[ $# -ge 2 ]] || { echo "Missing value for --host" >&2; exit 1; }
      HOST="$2"
      shift 2
      ;;
    --headless)
      HEADLESS="true"
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

if [[ ! -x "$VENV_PYTHON" || ! -x "$VENV_STREAMLIT" ]]; then
  echo "Virtual environment not found in $ROOT_DIR/.venv" >&2
  echo "Create it and install dependencies first:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

cd "$ROOT_DIR"

DEFAULT_TICKER_UPPER="$(printf '%s' "$DEFAULT_TICKER" | tr '[:lower:]' '[:upper:]')"

export OMNITRADE_DEFAULT_DATA_MODE_LABEL="$DEFAULT_MODE_LABEL"
export OMNITRADE_DEFAULT_PAGE="$DEFAULT_PAGE"
export OMNITRADE_DEFAULT_TICKER="$DEFAULT_TICKER_UPPER"

echo "Launching OmniTrade"
echo "  Mode:   $DEFAULT_MODE_LABEL"
echo "  Page:   $DEFAULT_PAGE"
echo "  Ticker: $DEFAULT_TICKER_UPPER"
echo "  URL:    http://$HOST:$PORT"

exec "$VENV_STREAMLIT" run app.py --server.address "$HOST" --server.port "$PORT" --server.headless "$HEADLESS"
