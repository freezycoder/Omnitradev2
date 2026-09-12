#!/usr/bin/env bash
set -euo pipefail

if [[ -f "$HOME/.cargo/env" ]]; then
  # shellcheck source=/dev/null
  source "$HOME/.cargo/env"
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_DIR="$ROOT_DIR/desktop"
APP_PATH="$DESKTOP_DIR/src-tauri/target/release/bundle/macos/OmniTrade.app"

cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "OmniTrade.app can only be built on macOS."
  exit 1
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "Rust is required. Install it with:"
  echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js and npm are required."
  exit 1
fi

if [[ ! -x "$ROOT_DIR/.venv/bin/uvicorn" ]]; then
  echo "Creating Python environment..."
  python3 -m venv "$ROOT_DIR/.venv"
  "$ROOT_DIR/.venv/bin/pip" install -r "$ROOT_DIR/requirements.txt"
fi

if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  echo "Installing frontend dependencies..."
  (cd "$ROOT_DIR/frontend" && npm install)
fi

echo "Installing Tauri CLI..."
(cd "$DESKTOP_DIR" && npm install)

echo "Building OmniTrade.app (this can take several minutes)..."
(cd "$DESKTOP_DIR" && npx tauri build)

if [[ ! -d "$APP_PATH" ]]; then
  echo "Build finished but OmniTrade.app was not found at:"
  echo "  $APP_PATH"
  exit 1
fi

echo ""
echo "Built: $APP_PATH"
echo "Open it with:"
echo "  open \"$APP_PATH\""
echo "Replace Applications only after that window works:"
echo "  rm -rf /Applications/OmniTrade.app"
echo "  cp -R \"$APP_PATH\" /Applications/"
