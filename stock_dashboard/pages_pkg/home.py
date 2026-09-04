from __future__ import annotations

import streamlit as st

from stock_dashboard.pages_pkg.formatters import (
    _render_long_term_pick,
    _render_short_term_pick,
    _scanner_header,
    render_rank_sheet_header,
    render_section_intro,
)


def render_home_page(scan_results: dict) -> None:
    _scanner_header(
        scan_results,
        "Current scan summary.",
        "Top-ranked long and short ideas.",
    )
    st.markdown("<div class='overview-stack-gap'></div>", unsafe_allow_html=True)
    long_rows = scan_results.get("long_term", [])[:2]
    short_rows = scan_results.get("short_term", [])[:2]

    header_cols = st.columns([1.1, 1.1], gap="large")
    with header_cols[0]:
        render_section_intro(
            "",
            "Long-term recommendations",
            "",
        )
        render_rank_sheet_header("Long-Term Conviction")
        if not long_rows:
            st.info("No long-term candidates cleared the current scan thresholds.")
    with header_cols[1]:
        render_section_intro(
            "",
            "Short-term recommendations",
            "",
        )
        render_rank_sheet_header("Short-Term Setup Quality")
        if not short_rows:
            st.info("No short-term setups cleared the current scan thresholds.")

    row_count = max(len(long_rows), len(short_rows))
    for index in range(row_count):
        row_cols = st.columns([1.1, 1.1], gap="large")
        with row_cols[0]:
            if index < len(long_rows):
                _render_long_term_pick(long_rows[index], index + 1, "home-long")
        with row_cols[1]:
            if index < len(short_rows):
                _render_short_term_pick(short_rows[index], index + 1, "home-short")
