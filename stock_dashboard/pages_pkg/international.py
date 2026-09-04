from __future__ import annotations

import streamlit as st

from stock_dashboard.pages_pkg.formatters import (
    _render_long_term_pick,
    _render_short_term_pick,
    _scanner_header,
    render_rank_sheet_header,
    render_section_intro,
)


def render_international_page(scan_results: dict) -> None:
    _scanner_header(
        scan_results,
        "International markets",
        "Outside-US names scanned with the same long-term and short-term engines.",
    )
    long_rows = scan_results.get("long_term", [])
    short_rows = scan_results.get("short_term", [])

    discovery_cols = st.columns([1.1, 1.1], gap="large")
    with discovery_cols[0]:
        render_section_intro(
            "Highest-ranked international long ideas.",
            "International long-term recommendations",
            "",
        )
        render_rank_sheet_header("International Long-Term Conviction")
        if not long_rows:
            st.info("No international long-term candidates cleared the current scan thresholds.")
        for rank, row in enumerate(long_rows[:3], start=1):
            _render_long_term_pick(row, rank, "intl-home-long")

    with discovery_cols[1]:
        render_section_intro(
            "Highest-ranked international tactical setups.",
            "International short-term recommendations",
            "",
        )
        render_rank_sheet_header("International Short-Term Setup Quality")
        if not short_rows:
            st.info("No international short-term setups cleared the current scan thresholds.")
        for rank, row in enumerate(short_rows[:3], start=1):
            _render_short_term_pick(row, rank, "intl-home-short")

    intl_tabs = st.tabs(["Long-Term International", "Short-Term International"])
    with intl_tabs[0]:
        if not long_rows:
            st.info("No international long-term recommendations are available yet.")
        else:
            render_rank_sheet_header("International Investor Ranking Sheet")
            for rank, row in enumerate(long_rows, start=1):
                _render_long_term_pick(row, rank, "intl-long-page")

    with intl_tabs[1]:
        if not short_rows:
            st.info("No international short-term recommendations are available yet.")
        else:
            render_rank_sheet_header("International Trader Ranking Sheet")
            for rank, row in enumerate(short_rows, start=1):
                _render_short_term_pick(row, rank, "intl-short-page")
