# Deployment

This repo is best deployed as two services:

- FastAPI backend on Render's free web service tier
- Next.js frontend on Vercel

Render's free backend is enough to test the app from your phone without paying. Fresh instances start from the bundled AI signal-history and scan-cache snapshot. The tradeoff is that new filesystem changes can be lost on restart/redeploy, so newly generated picks and outcomes are not durable until the app is moved to Postgres or paid persistent storage.

## 1. Deploy the backend to Render

Use the GitHub repo and create a Render Blueprint from `render.yaml`, or create a Web Service manually.

Manual settings:

```text
Service type: Web Service
Runtime: Python
Branch: main
Build Command: pip install -r requirements.txt
Start Command: uvicorn api.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /api/health
Instance Type: Free
```

Add variables:

```bash
ENV=production
FINNHUB_API_KEY=your_finnhub_key_here
FRED_API_KEY=your_fred_key_here
SEC_EDGAR_USER_AGENT=OmniTrade/1.0 your-reachable-contact@example.com
OMNITRADE_CORS_ORIGINS=https://your-vercel-app.vercel.app
OMNITRADE_DATA_DIR=data_store
OMNITRADE_WRITE_MODE=read_only
```

`FINNHUB_API_KEY` is optional for demo/cached mode, but live Finnhub headlines need it.
`FRED_API_KEY` is optional; without it the macro component is marked unavailable
instead of being treated as neutral. SEC EDGAR needs no key, but its fair-access
policy requires a declared `SEC_EDGAR_USER_AGENT`.
Hosted deployments should keep `OMNITRADE_WRITE_MODE=read_only`. This blocks
performance-log and watchlist mutations at the API boundary while leaving all
research views available.

Alternative signals remain shadow-only in hosted and local deployments. Their
modeled impact is capped at ±10, their applied impact remains zero, and the
Calibration page must meet every evidence gate before activation is even
eligible for manual review.

After deploy, open:

```text
https://your-render-backend.onrender.com/api/health
```

It should return `{"status":"ok","service":"omnitrade-api"}`.

## 2. Deploy the frontend to Vercel

1. Import the same GitHub repo in Vercel.
2. Leave Root Directory blank. The root `package.json` and `vercel.json` forward the build to `frontend`.
3. Keep Framework Preset as Next.js.
4. Add this environment variable before deploying:

```bash
NEXT_PUBLIC_OMNITRADE_API_URL=https://your-render-backend.onrender.com
```

Deploy, then open:

```text
https://your-vercel-app.vercel.app/overview
```

## 3. Deployment safety

Set `OMNITRADE_CORS_ORIGINS` to the exact Vercel production origin. For
multiple trusted frontends, use a comma-separated list. Do not use a wildcard
regular expression in a public deployment.

CORS controls which browser origins may read responses; it is not
authentication. Keep `OMNITRADE_WRITE_MODE=read_only`, protect provider quotas
with the hosting platform's rate limiting, and never place provider keys in
`NEXT_PUBLIC_*` variables or commit them to Git.

## Data persistence

The repository includes a compressed seed containing the existing AI-picked
signal history and real scan caches. Render loads that seed only when its
runtime database is empty, so the hosted dashboards begin with the same
historical dataset as the local app.

Free Render web services are good for testing and casual personal use, but not
durable local storage. For durable SQLite storage:

1. Upgrade the Render service to a plan that supports persistent disks.
2. Attach a disk, for example at `/var/data`.
3. Set `OMNITRADE_DATA_DIR=/var/data`.
4. Redeploy.

The first start hydrates the disk from the bundled seed. Future AI picks,
outcomes, watchlist changes, and scan caches then survive deploys and restarts.
