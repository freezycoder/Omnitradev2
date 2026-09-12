# OmniTrade Mac app (Tauri)

This folder rebuilds `OmniTrade.app`. The clickable app starts the local FastAPI API and the Next.js UI from **this git checkout**, then opens them in a desktop window.

It is a launcher around the repo, not a bundled copy of Python or Next.js. Keep the clone at `~/Omnitradev2` (or set `OMNITRADE_ROOT`) so the app can find `run_api.sh`, `.venv`, and `frontend/`.

Copying an older `.app` into `/Applications` does not pick up new features such as ETF research.

## Rebuild on your Mac

From the repo root:

```bash
cd ~/Omnitradev2
git checkout main
git pull origin main
chmod +x desktop/build-mac.sh desktop/build-frontend.sh
./desktop/build-mac.sh
```

When it finishes, open the **new** build first:

```bash
open ~/Omnitradev2/desktop/src-tauri/target/release/bundle/macos/OmniTrade.app
```

Only replace Applications after that window loads the research UI:

```bash
rm -rf /Applications/OmniTrade.app
cp -R ~/Omnitradev2/desktop/src-tauri/target/release/bundle/macos/OmniTrade.app /Applications/
```

## Requirements

- macOS 12+
- Xcode Command Line Tools: `xcode-select --install`
- Node.js + npm
- Rust: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
- Python 3; the build script creates `.venv` if it is missing

Linux CI can compile and test the Rust launcher, but it cannot produce `OmniTrade.app`.

## Dev window

Start the API and Next.js UI first, then:

```bash
cd desktop
npm install
npx tauri dev
```

`tauri dev` expects the API on `http://127.0.0.1:8788` and the Next app on `http://127.0.0.1:3000`.
