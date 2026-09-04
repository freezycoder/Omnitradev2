# OmniTrade

OmniTrade is a local stock-screening dashboard with a Streamlit app, a FastAPI API, and a Next.js frontend.

## What is included

- Streamlit dashboard: `app.py`
- FastAPI backend: `api/main.py`
- Next.js frontend: `frontend/`
- Local demo data: `data_store/demo_data.json`
- Clickable launchers for local desktop and same-Wi-Fi phone access

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cd frontend
npm install
```

For live Finnhub news and FRED macro context, create `~/.config/omnitrade/secrets.env`:

```bash
FINNHUB_API_KEY=your_key_here
FRED_API_KEY=your_key_here
```

SEC EDGAR events use the SEC's free public API and do not require a key. Set
`SEC_EDGAR_USER_AGENT` to a declared application name and reachable contact,
as shown in `.env.example`, before running automated live scans.

The SEC, classified-news, and FRED signals are recorded in **shadow mode**.
They expose a capped modeled impact for calibration, but their applied impact
is zero and they do not change live recommendations.

Relative strength is also shadow-only. It compares each stock with SPY and its
sector ETF over 1, 3, 6, and 12 months, then records universe and sector
percentile ranks during full scans. The benchmark histories are fetched once
and cached across the scan.

Earnings intelligence is shadow-only as well. It combines the last four
Finnhub EPS surprises with Yahoo Finance consensus estimates and revision
counts, the next earnings date, recent guidance headlines, and the observed
three-session move after the latest SEC earnings filing. Imminent earnings are
flagged as event risk, never interpreted as bullish or bearish by themselves.

This product uses the FRED® API but is not endorsed or certified by the
Federal Reserve Bank of St. Louis.

Do not commit `.env` or local data files.

OmniTrade is research and decision-support software, not financial advice.
Market data can be delayed, incomplete, or inaccurate. Do not use displayed
signals as the sole basis for a trade.

## Run on this Mac

Double-click `run_omnitrade_web.command`, or run:

```bash
./run_api.sh --no-reload
cd frontend
npm run dev
```

Then open `http://127.0.0.1:3000/overview`.

The local API launcher explicitly enables watchlist and performance-log writes.
API processes started without `OMNITRADE_WRITE_MODE=local` fail closed in
read-only mode.

## Run from your phone on the same Wi-Fi

Double-click `run_omnitrade_lan.command`.

It starts the API and frontend on your Mac's local network address, copies the phone URL to your clipboard, and prints it in Terminal. Open that URL on your phone while both devices are on the same Wi-Fi network.

If macOS asks whether Python, Node, or Terminal can accept incoming connections, allow it. The Terminal window must stay open while you use the app from your phone.

## Public repository safety

Before making a fork or mirror public, run:

```bash
python3 scripts/check_public_repo.py
```

The check rejects tracked secret files, high-confidence credential patterns,
personal absolute paths, and unexpected tables in the compressed deployment
seed. Also inspect the complete Git history with a dedicated secret scanner,
review commit author emails, and confirm that you have redistribution rights
for any refreshed market-data snapshots. If a real credential was ever
committed, revoke it before rewriting or deleting Git history.

After publishing, enable GitHub secret scanning, push protection, private
vulnerability reporting, Dependabot alerts, and branch protection for `main`.

See `SECURITY.md` for vulnerability reporting and safe deployment defaults.

## Deployment note

GitHub stores the source code; it does not run this full-stack app by itself. For always-on phone access away from your Mac, deploy the frontend and backend separately, then set `NEXT_PUBLIC_OMNITRADE_API_URL` in the frontend host to the backend URL.

For the recommended Vercel + Render setup, see `DEPLOYMENT.md`.
