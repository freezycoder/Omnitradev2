# OmniTrade API

FastAPI adapter over the existing OmniTrade application services.

Run locally:

```bash
cd /path/to/omnitrade
./run_api.sh
```

If using the project virtualenv:

```bash
cd /path/to/omnitrade
OMNITRADE_WRITE_MODE=local .venv/bin/uvicorn api.main:app --reload
```

The `api` package is imported from the project root, so run the command from
the cloned repository directory.

Endpoints:

- `GET /`
- `GET /api/health`
- `GET /api/capabilities`
- `GET /api/overview`
- `GET /api/ticker/{ticker}?data_mode=auto|live|demo`
- `GET /api/performance-lab?price_mode=cached|live`
- `POST /api/performance-log`
- `GET /api/long-term-performance`
- `GET /api/calibration`
- `GET /api/portfolio?price_mode=cached|live`
- `GET /api/watchlist`
- `POST /api/watchlist`
- `DELETE /api/watchlist/{ticker}`

`price_mode=cached` is the default for frontend responsiveness. Use `price_mode=live` when you explicitly want the same live price refresh behavior as the Streamlit portfolio/performance views.

User mutations fail closed unless `OMNITRADE_WRITE_MODE=local` is explicitly
set. The bundled Render deployment remains read-only; `./run_api.sh` opts into
local writes for personal use.
