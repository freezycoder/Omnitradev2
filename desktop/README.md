# OmniTrade Desktop

Native desktop packaging for OmniTrade (macOS and Windows) built with
[Tauri](https://tauri.app). The desktop app wraps the **existing** Next.js
frontend and FastAPI/Python backend — no research or business logic is changed.

The folder `desktop/` lives **inside this git repo**. It is not `~/Desktop`.
Run every command below from the repository root (the folder that contains
`README.md` and `desktop/build_desktop.sh`).

```bash
cd ~/Omnitradev2
ls desktop/build_desktop.sh
```

## How to run (from source)

1. Install tools once: Python 3.12, Node 22, Rust, Tauri CLI (`cargo install tauri-cli --version "^2" --locked`). On macOS also run `xcode-select --install` if needed.
2. Create a project venv and install backend deps **plus PyInstaller** (the build script uses `.venv` when it exists):

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install --upgrade pip
   .venv/bin/pip install -r requirements.txt pyinstaller
   npm --prefix frontend install
   ```

   Prefer Python 3.12. Homebrew `python3.14` often fails (`No module named PyInstaller` or package build errors).

3. Put Cargo on your `PATH` and build. The first build can take 10–30 minutes. Leave the terminal open.

   ```bash
   export PATH="$HOME/.cargo/bin:$PATH"
   bash desktop/build_desktop.sh
   ```

   `~/.cargo/bin/cargo-tauri` is the compiler CLI, not the OmniTrade app.

4. Only after the script finishes with no error, open the app:

   ```bash
   # macOS
   open desktop/src-tauri/target/release/bundle/macos/OmniTrade.app
   ```

   Windows installers land under `desktop/src-tauri/target/release/bundle/nsis/` or `bundle/msi/`.

The window starts the bundled FastAPI backend by itself. Do not also run
`./run_api.sh` or `npm run dev`.

If `OmniTrade.app does not exist`, the build has not completed. Scroll up in
Terminal for the first error (missing PyInstaller, wrong directory, or Rust
tools not on `PATH`).

## After you have an installer

1. Download `OmniTrade.dmg` (macOS) / `OmniTrade-setup.exe` (Windows).
2. Drag `OmniTrade.app` to Applications (macOS) / run the installer (Windows).
3. Double-click to launch. The app starts all required local services automatically.

No Python, Node, npm, Terminal, or virtual environment is required for that
installed-app path.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│ OmniTrade.app (Tauri shell, Rust)                           │
│                                                            │
│  • picks a free localhost port                             │
│  • launches the bundled backend on that port              │
│  • injects window.__OMNITRADE_API_BASE__ into the webview  │
│  • health-checks the backend, logs output                 │
│  • gracefully stops the backend on quit                   │
│  • reads/writes API keys and restarts the backend         │
│                                                            │
│  ┌──────────────────────────┐   ┌───────────────────────┐ │
│  │ WebView                   │   │ Backend child process  │ │
│  │ static Next.js export     │──▶│ PyInstaller bundle of  │ │
│  │ (frontend/out)            │   │ api.main:app (uvicorn) │ │
│  └──────────────────────────┘   └───────────┬───────────┘ │
└──────────────────────────────────────────────┼────────────┘
                                                │ writes
                                    per-user writable data dir
                                    (OMNITRADE_DATA_DIR)
```

- **Frontend** — built with `output: "export"` (static HTML/JS/CSS) so no Node
  runtime ships. The one server route handler (`/api/saved-scan`) was replaced by
  a client-side load of the same bundled JSON, keeping behavior identical.
- **Backend** — packaged with PyInstaller into a self-contained one-directory
  bundle (Python runtime + all deps). It is the unchanged `api.main:app` started
  by a thin launcher (`desktop/backend/omnitrade_backend.py`).
- **Dynamic port** — the shell binds `127.0.0.1:0` to get a free port, starts the
  backend there, and injects the resolved base URL into the webview before any app
  code runs (`frontend/lib/api.ts` prefers `window.__OMNITRADE_API_BASE__`).
- **Data directory** — the shell sets `OMNITRADE_DATA_DIR` to a per-user writable
  path so the read-only app bundle is never written to:
  - macOS: `~/Library/Application Support/com.omnitrade.desktop`
  - Windows: `%APPDATA%\com.omnitrade.desktop`
- **Secrets / API keys** — stored in `~/.config/omnitrade/secrets.env` (the exact
  path the backend already reads). Managed from the in-app **Settings** panel.
- **Logging** — backend stdout/stderr is written to the app log directory
  (`backend.log`), openable from Settings.

The optional Kronos (PyTorch) forecast service is intentionally **not** bundled —
it is multi-GB and disabled by default. It can still be pointed at an external
service via `KRONOS_SERVICE_URL`.

## Building

Prerequisites: Python 3.12, Node 22, Rust (stable), and the Tauri CLI
(`cargo install tauri-cli --version "^2" --locked`). Platform bundlers require
building on the target OS (macOS bundles on macOS, Windows on Windows).

One command builds everything for the current OS:

```bash
bash desktop/build_desktop.sh
```

This runs the three stages individually:

```bash
# 1. Bundle the backend (output: desktop/src-tauri/resources/backend/)
bash desktop/backend/build_backend.sh

# 2. Build the static frontend export (output: frontend/out/)
OMNITRADE_DESKTOP=1 NEXT_PUBLIC_OMNITRADE_API_URL=http://127.0.0.1:8788 \
  npm --prefix frontend run build

# 3. Build the desktop app + installers
cd desktop/src-tauri && cargo tauri build
```

Outputs land under `desktop/src-tauri/target/**/release/bundle/` (`.dmg`/`.app`
on macOS, `.exe`/`.msi` on Windows).

## CI

`.github/workflows/desktop-build.yml` builds signed-ready installers for macOS
(arm64 + x64) and Windows (x64) on tag pushes or manual dispatch, uploading each
platform's installer as a build artifact.

## Code signing / notarization

The pipeline produces unsigned bundles by default. For distribution, add the
platform signing secrets and enable them in `tauri.conf.json`:

- macOS: Developer ID certificate + notarization (`APPLE_CERTIFICATE`,
  `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`).
- Windows: Authenticode certificate for the NSIS/MSI bundle.
