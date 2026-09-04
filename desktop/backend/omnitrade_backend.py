"""Standalone entrypoint for the OmniTrade FastAPI backend.

This module is the PyInstaller entry point for the desktop app. It is a thin
launcher around the *unchanged* ``api.main:app`` ASGI application. Its only
responsibilities are packaging concerns:

* choose a writable per-user data directory (``OMNITRADE_DATA_DIR``),
* seed the one bundled data file that is not part of the DB seed flow
  (``demo_data.json``),
* apply desktop-friendly defaults (local write mode, CORS for the Tauri webview),
* start uvicorn on the host/port chosen by the Tauri shell.

No research or business logic lives here.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def _bundle_root() -> Path:
    """Directory containing bundled read-only resources (seeds, demo data)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    # Running from source: repository root (three levels up from this file).
    return Path(__file__).resolve().parent.parent.parent


def _default_data_dir() -> Path:
    """Per-user writable directory used when the shell does not provide one."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OmniTrade"
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        return (Path(base) / "OmniTrade") if base else (Path.home() / "OmniTrade")
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "omnitrade"


def _prepare_data_dir() -> Path:
    data_dir = Path(os.environ.get("OMNITRADE_DATA_DIR") or _default_data_dir()).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["OMNITRADE_DATA_DIR"] = str(data_dir)

    # demo_data.json is read directly from DATA_DIR and is not copied by the
    # database seed flow, so ensure it exists on first launch.
    demo_target = data_dir / "demo_data.json"
    if not demo_target.exists():
        demo_source = _bundle_root() / "data_store" / "demo_data.json"
        if demo_source.exists():
            try:
                shutil.copyfile(demo_source, demo_target)
            except OSError as exc:  # pragma: no cover - non-fatal
                print(f"[omnitrade-backend] Could not seed demo data: {exc}", file=sys.stderr, flush=True)
    return data_dir


def _apply_desktop_defaults() -> None:
    # Enable local watchlist/performance-log writes for the desktop app.
    os.environ.setdefault("OMNITRADE_WRITE_MODE", "local")
    os.environ.setdefault("ENV", "production")
    # Allow the Tauri webview origins (macOS/Windows/Linux variants) to call the API.
    os.environ.setdefault(
        "OMNITRADE_CORS_ORIGINS",
        "tauri://localhost,http://tauri.localhost,https://tauri.localhost",
    )
    os.environ.setdefault(
        "OMNITRADE_CORS_ORIGIN_REGEX",
        r"(tauri://localhost|https?://tauri\.localhost|https?://(localhost|127\.0\.0\.1)(:\d+)?)",
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="omnitrade-backend")
    parser.add_argument("--host", default=os.environ.get("OMNITRADE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("OMNITRADE_PORT", "8788")))
    # Accepted for parity with run_api.sh; uvicorn reload is never used in the bundle.
    parser.add_argument("--no-reload", action="store_true")
    args, _unknown = parser.parse_known_args(argv)

    _apply_desktop_defaults()
    data_dir = _prepare_data_dir()

    # Import uvicorn/app only after the environment has been prepared so that
    # config.settings picks up OMNITRADE_DATA_DIR and CORS settings.
    import uvicorn

    print(
        f"[omnitrade-backend] starting on http://{args.host}:{args.port} "
        f"(data dir: {data_dir})",
        flush=True,
    )
    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
