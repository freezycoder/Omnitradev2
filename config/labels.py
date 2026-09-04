from __future__ import annotations

from config.settings import DATA_MODE_AUTO, DATA_MODE_DEMO

NAV_PAGES = [
    "Overview",
    "Long-Term Recommendations",
    "Long-Term Performance",
    "Short-Term Recommendations",
    "International Markets",
    "Ticker Analysis",
    "Performance Lab",
    "Portfolio",
    "Calibration",
    "Watchlist",
]

DATA_MODE_LABELS = {
    "Auto": DATA_MODE_AUTO,
    "Demo Only": DATA_MODE_DEMO,
}

__all__ = ["DATA_MODE_LABELS", "NAV_PAGES"]
