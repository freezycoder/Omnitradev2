#!/usr/bin/env bash
# Build the self-contained OmniTrade FastAPI backend bundle with PyInstaller.
#
# Output: desktop/src-tauri/resources/backend/omnitrade-backend/
# (a one-directory bundle containing the executable + Python runtime + deps).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
  elif [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/Scripts/python.exe"
  else
    PYTHON_BIN="python3"
  fi
fi

DIST_DIR="$ROOT_DIR/desktop/src-tauri/resources/backend"
WORK_DIR="$ROOT_DIR/desktop/backend/.build"

echo "Building OmniTrade backend bundle"
echo "  Python:   $PYTHON_BIN"
echo "  Dist dir: $DIST_DIR"

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --distpath "$DIST_DIR" \
  --workpath "$WORK_DIR" \
  "$ROOT_DIR/desktop/backend/omnitrade-backend.spec"

echo "Backend bundle written to: $DIST_DIR/omnitrade-backend"
