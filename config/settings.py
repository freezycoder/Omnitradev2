from __future__ import annotations

import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path


def _resolve_base_dir() -> Path:
    """Resolve the directory that holds bundled, read-only resources.

    In a normal source checkout this is the repository root. When the backend is
    packaged with PyInstaller (desktop app), the bundled resources such as
    ``seed_data/`` live next to the frozen modules under ``sys._MEIPASS``. This
    only affects where read-only bundled assets are located; the writable data
    directory (``DATA_DIR``) is still controlled by ``OMNITRADE_DATA_DIR``.
    """

    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


BASE_DIR = _resolve_base_dir()
DATA_DIR = Path(os.environ.get("OMNITRADE_DATA_DIR", BASE_DIR / "data_store")).expanduser()
ENV_FILE = BASE_DIR / ".env"
SECRETS_FILE = Path.home() / ".config" / "omnitrade" / "secrets.env"
SCAN_CACHE_DIR = DATA_DIR / "scan_cache"
REAL_SCAN_CACHE_FILE = DATA_DIR / "latest_real_scan.json"
LATEST_VIEW_SCAN_FILE = DATA_DIR / "latest_scan_results.json"
WATCHLIST_FILE = DATA_DIR / "watchlist.json"
TICKER_CACHE_DIR = DATA_DIR / "ticker_cache"
DEMO_DATA_FILE = DATA_DIR / "demo_data.json"

CACHE_FRESHNESS_HOURS = 24
ALLOW_DEMO_FALLBACK = True

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FINNHUB_TIMEOUT_SECONDS = 8
FINNHUB_NEWS_LOOKBACK_DAYS = 21
FINNHUB_MAX_HEADLINES = 6
LONG_TERM_NEWS_MAX_IMPACT = 6
SHORT_TERM_NEWS_MAX_IMPACT = 8

SEC_EDGAR_BASE_URL = "https://data.sec.gov"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_EDGAR_TIMEOUT_SECONDS = 10
SEC_EVENT_LOOKBACK_DAYS = 120
SEC_MAX_EVENTS = 12
SEC_MAX_FORM4_DOCUMENTS = 3
SEC_CACHE_TTL_SECONDS = 60 * 60

FRED_BASE_URL = "https://api.stlouisfed.org/fred"
FRED_TIMEOUT_SECONDS = 10
FRED_CACHE_TTL_SECONDS = 6 * 60 * 60

ALTERNATIVE_SIGNALS_MODE = "shadow"
ALTERNATIVE_SIGNALS_MAX_IMPACT = 10

DATA_MODE_AUTO = "auto"
DATA_MODE_LIVE = "live"
DATA_MODE_DEMO = "demo"


@dataclass(frozen=True)
class SourceMeta:
    key: str
    label: str
    banner: str | None
    recommendation_note: str | None
    allow_actionable_recommendations: bool


SOURCE_CONFIG = {
    "live": SourceMeta(
        key="live",
        label="Live data",
        banner=None,
        recommendation_note=None,
        allow_actionable_recommendations=True,
    ),
    "cached_real": SourceMeta(
        key="cached_real",
        label="Cached real data",
        banner="Using cached real data because live data is unavailable. Signals become read-only after 24 hours.",
        recommendation_note="Cached signals are actionable only inside the configured 24-hour freshness window.",
        allow_actionable_recommendations=True,
    ),
    "demo": SourceMeta(
        key="demo",
        label="Demo data",
        banner="Using demo data because live and cached real data are unavailable.",
        recommendation_note="Demo mode is for testing only and should not be treated as live market intelligence.",
        allow_actionable_recommendations=False,
    ),
}


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv-style file into a dict. Does NOT touch os.environ."""
    if not path.exists():
        return {}
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            parsed[key] = value
    return parsed


@dataclass(frozen=True)
class Settings:
    """Typed configuration object loaded from secrets file and project .env.

    Secrets are NOT injected into os.environ — all consumers must import
    `settings` from this module and read attributes directly. This prevents
    secrets from leaking to subprocesses spawned by yfinance, Finnhub HTTP
    clients, or any other library that inspects the parent environment.
    """

    finnhub_api_key: str
    fred_api_key: str
    sec_edgar_user_agent: str
    env: str
    default_page: str
    default_ticker: str
    default_data_mode_label: str
    secrets_source: str = field(default="")


def _load_settings() -> Settings:
    env_name = os.environ.get("ENV", "production").strip().lower() or "production"

    secrets = _read_env_file(SECRETS_FILE)
    project_env = _read_env_file(ENV_FILE)

    project_key = project_env.get("FINNHUB_API_KEY", "").strip()
    if project_key and env_name != "development":
        warnings.warn(
            "FINNHUB_API_KEY found in project .env; ignoring it. "
            "Move the key to ~/.config/omnitrade/secrets.env or set ENV=development.",
            stacklevel=2,
        )
        # Also print to stderr so the message is visible in non-warning-aware tools.
        print(
            "[omnitrade] WARNING: FINNHUB_API_KEY in project .env is ignored in non-dev mode.",
            file=sys.stderr,
            flush=True,
        )

    secrets_key = secrets.get("FINNHUB_API_KEY", "").strip()
    environment_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if secrets_key:
        finnhub_api_key = secrets_key
        secrets_source = str(SECRETS_FILE)
    elif environment_key:
        finnhub_api_key = environment_key
        secrets_source = "FINNHUB_API_KEY environment variable"
    elif env_name == "development" and project_key:
        finnhub_api_key = project_key
        secrets_source = str(ENV_FILE)
    else:
        finnhub_api_key = ""
        secrets_source = ""

    project_fred_key = project_env.get("FRED_API_KEY", "").strip()
    secrets_fred_key = secrets.get("FRED_API_KEY", "").strip()
    environment_fred_key = os.environ.get("FRED_API_KEY", "").strip()
    if secrets_fred_key:
        fred_api_key = secrets_fred_key
    elif environment_fred_key:
        fred_api_key = environment_fred_key
    elif env_name == "development" and project_fred_key:
        fred_api_key = project_fred_key
    else:
        fred_api_key = ""

    sec_edgar_user_agent = (
        os.environ.get("SEC_EDGAR_USER_AGENT")
        or project_env.get("SEC_EDGAR_USER_AGENT")
        or ""
    ).strip()

    # Non-secret runtime preferences may still come from os.environ; these
    # are not sensitive and Streamlit launchers commonly set them.
    return Settings(
        finnhub_api_key=finnhub_api_key,
        fred_api_key=fred_api_key,
        sec_edgar_user_agent=sec_edgar_user_agent,
        env=env_name,
        default_page=os.environ.get("OMNITRADE_DEFAULT_PAGE", "Overview"),
        default_ticker=(os.environ.get("OMNITRADE_DEFAULT_TICKER", "AAPL") or "AAPL").upper().strip() or "AAPL",
        default_data_mode_label=os.environ.get("OMNITRADE_DEFAULT_DATA_MODE_LABEL", "Auto"),
        secrets_source=secrets_source,
    )


settings = _load_settings()

# Backwards-compatible module-level constant. Modules that already imported
# FINNHUB_API_KEY continue to work; new code should prefer `settings.finnhub_api_key`.
FINNHUB_API_KEY = settings.finnhub_api_key
