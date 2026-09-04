#!/usr/bin/env bash
# End-to-end desktop build:
#   1. bundle the FastAPI backend with PyInstaller,
#   2. build the Next.js frontend as a static export,
#   3. build the Tauri desktop app (installers/bundles for the current OS).
#
# Requirements: Python venv with deps + pyinstaller, Node/npm, Rust, and the
# Tauri CLI (`cargo install tauri-cli --version "^2"`).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "==> [1/3] Building backend bundle (PyInstaller)"
bash "$SCRIPT_DIR/backend/build_backend.sh"

echo "==> [2/3] Building frontend static export"
export OMNITRADE_DESKTOP=1
export NEXT_PUBLIC_OMNITRADE_API_URL="http://127.0.0.1:8788"
npm --prefix frontend install
npm --prefix frontend run build

echo "==> [3/3] Building Tauri desktop app"
if command -v cargo-tauri >/dev/null 2>&1; then
  ( cd "$SCRIPT_DIR/src-tauri" && cargo tauri build "$@" )
else
  ( cd "$SCRIPT_DIR/src-tauri" && cargo build --release )
  echo "NOTE: cargo-tauri not found; built the app binary only (no installers)."
  echo "      Install it with: cargo install tauri-cli --version \"^2\""
fi

echo "==> Desktop build complete."
