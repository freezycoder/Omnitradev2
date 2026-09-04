from __future__ import annotations

import streamlit as st

from stock_dashboard.pages_pkg.formatters import (
    _render_long_term_pick,
    _scanner_header,
    _tone_for_score,
    render_rank_sheet_header,
    render_status_strip,
)


def render_long_term_page(scan_results: dict) -> None:
    _scanner_header(
        scan_results,
        "Long-term recommendations",
        "Ranked by the current long-term model.",
    )
    rows = scan_results.get("long_term", [])
    if not rows:
        st.info("No long-term recommendations are available yet.")
        return

    with st.container(border=True):
        filter_cols = st.columns(3)
        labels = sorted({row["recommendation_label"] for row in rows})
        min_score = filter_cols[0].slider("Minimum score", 0, 100, 0)
        selected_labels = filter_cols[1].multiselect("Recommendation labels", options=labels, default=labels)
        sort_by = filter_cols[2].selectbox("Sort by", ["Score", "Ticker", "Market Cap"])

    filtered = [
        row for row in rows if row["long_term_score"] >= min_score and row["recommendation_label"] in selected_labels
    ]
    if sort_by == "Ticker":
        filtered.sort(key=lambda row: row["ticker"])
    elif sort_by == "Market Cap":
        filtered.sort(key=lambda row: row.get("market_cap") or 0, reverse=True)
    else:
        filtered.sort(key=lambda row: row["long_term_score"], reverse=True)

    render_status_strip(
        [
            (f"Matched {len(filtered)} names", "neutral"),
            (f"Filter floor {min_score}", _tone_for_score(min_score)),
            ("Long-term scoring active", "positive"),
        ]
    )
    render_rank_sheet_header("Score / Conviction / Valuation")
    for rank, row in enumerate(filtered, start=1):
        _render_long_term_pick(row, rank, "long-page")
