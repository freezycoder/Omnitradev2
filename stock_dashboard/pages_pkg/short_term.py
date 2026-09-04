from __future__ import annotations

import streamlit as st

from stock_dashboard.pages_pkg.formatters import (
    _render_short_term_pick,
    _scanner_header,
    _tone_for_score,
    render_rank_sheet_header,
    render_status_strip,
)


def render_short_term_page(scan_results: dict) -> None:
    _scanner_header(
        scan_results,
        "Short-term recommendations",
        "Ranked by the current short-term model.",
    )
    rows = scan_results.get("short_term", [])
    if not rows:
        st.info("No short-term recommendations are available yet.")
        return

    with st.container(border=True):
        filter_cols = st.columns(3)
        labels = sorted({row["recommendation_label"] for row in rows})
        min_score = filter_cols[0].slider("Minimum score", 0, 100, 0)
        selected_labels = filter_cols[1].multiselect("Recommendation labels", options=labels, default=labels)
        sort_by = filter_cols[2].selectbox("Sort by", ["Score", "Ticker", "Holding Period"])

    filtered = [
        row for row in rows if row["short_term_score"] >= min_score and row["recommendation_label"] in selected_labels
    ]
    if sort_by == "Ticker":
        filtered.sort(key=lambda row: row["ticker"])
    elif sort_by == "Holding Period":
        filtered.sort(key=lambda row: row["expected_holding_period"])
    else:
        filtered.sort(key=lambda row: row["short_term_score"], reverse=True)

    render_status_strip(
        [
            (f"Matched {len(filtered)} setups", "neutral"),
            (f"Filter floor {min_score}", _tone_for_score(min_score)),
            ("Short-term scoring active", "watch"),
        ]
    )
    render_rank_sheet_header("Score / Setup / Execution")
    for rank, row in enumerate(filtered, start=1):
        _render_short_term_pick(row, rank, "short-page")
