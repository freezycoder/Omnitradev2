from __future__ import annotations

from stock_dashboard.pages_pkg.calibration import render_calibration_page
from stock_dashboard.pages_pkg.home import render_home_page
from stock_dashboard.pages_pkg.international import render_international_page
from stock_dashboard.pages_pkg.long_term import render_long_term_page
from stock_dashboard.pages_pkg.long_term_performance import render_long_term_performance_page
from stock_dashboard.pages_pkg.no_data import render_no_data_home
from stock_dashboard.pages_pkg.performance_lab import render_performance_lab_page
from stock_dashboard.pages_pkg.portfolio import render_portfolio_page
from stock_dashboard.pages_pkg.short_term import render_short_term_page
from stock_dashboard.pages_pkg.ticker import render_ticker_page
from stock_dashboard.pages_pkg.watchlist import render_watchlist_page

__all__ = [
    "render_calibration_page",
    "render_home_page",
    "render_international_page",
    "render_long_term_page",
    "render_long_term_performance_page",
    "render_no_data_home",
    "render_performance_lab_page",
    "render_portfolio_page",
    "render_short_term_page",
    "render_ticker_page",
    "render_watchlist_page",
]
