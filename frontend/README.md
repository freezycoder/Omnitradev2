# OmniTrade Frontend

React/TypeScript terminal frontend for the existing OmniTrade FastAPI API.

## Run locally

Start the API from the repository root:

```bash
cd /path/to/omnitrade
./run_api.sh
```

Start the frontend in a second Terminal tab:

```bash
cd /path/to/omnitrade/frontend
npm install
npm run dev
```

The frontend defaults to `http://127.0.0.1:8788` for API calls. Override it with:

```bash
NEXT_PUBLIC_OMNITRADE_API_URL=http://127.0.0.1:8788 npm run dev
```

## Desktop launcher

Double-click `OmniTrade Web.app` on the Desktop to open a Terminal runner,
start the FastAPI API, start the Next frontend, and open `/overview`.
There is also a direct `Run OmniTrade Web.command` launcher on the Desktop.

Logs are written to:

- `/tmp/omnitrade-api.log`
- `/tmp/omnitrade-frontend.log`
- `/tmp/omnitrade-web-launcher.log`

## Pages

- `/overview`
- `/long-term`
- `/long-term-performance`
- `/short-term`
- `/international`
- `/ticker`
- `/performance`
- `/portfolio`
- `/calibration`
- `/watchlist`
