from __future__ import annotations

from html import escape

import streamlit as st

from storage.repositories.watchlist_repository import load_watchlist, remove_from_watchlist
from stock_dashboard.pages_pkg.formatters import (
    _open_ticker,
    _source_badge,
    _source_meta,
    recommendation_pill,
    render_rank_sheet_header,
    render_section_intro,
)
from stock_dashboard.ui import format_timestamp


def render_watchlist_page(scan_results: dict) -> None:
    render_section_intro(
        "Watchlist",
        "Saved names from the scanner and ticker page.",
        "",
    )
    watchlist = load_watchlist()
    if not watchlist:
        st.info("No names have been saved yet.")
        return

    long_lookup = {row["ticker"]: row for row in scan_results.get("long_term", [])}
    short_lookup = {row["ticker"]: row for row in scan_results.get("short_term", [])}
    render_rank_sheet_header("Status / Source / Monitoring")

    for rank, item in enumerate(watchlist, start=1):
        ticker = item["ticker"]
        long_row = long_lookup.get(ticker)
        short_row = short_lookup.get(ticker)
        row_source = (long_row or short_row or {}).get("data_source", scan_results.get("source", "demo"))
        row_updated_at = (long_row or short_row or {}).get("updated_at", scan_results.get("updated_at"))
        st.markdown(
            f"""
            <div class="rank-sheet-row">
                <div class="rank-grid">
                    <div class="rank-cell">
                        <div class="rank-number">{rank:02d}</div>
                    </div>
                    <div class="rank-cell">
                        <div class="rank-heading">
                            <div>
                                <h3 class="rank-ticker">{escape(ticker)}</h3>
                                <div class="rank-subtitle">Saved from {escape(item.get('source', 'manual'))}</div>
                            </div>
                        </div>
                        <div class="rank-meta-strip">
                            {_source_badge(row_source, row_updated_at)}
                            {recommendation_pill("Watchlist Name", "neutral")}
                        </div>
                        <div class="rank-details">
                            <div class="detail-box">
                                <div class="detail-box-title">Long-Term Status</div>
                                <div class="detail-box-body">
                                    {escape(f"{long_row['recommendation_label']} • {long_row['long_term_score']}/100" if long_row else "Not in the latest long-term recommendation list.")}
                                </div>
                            </div>
                            <div class="detail-box">
                                <div class="detail-box-title">Short-Term Status</div>
                                <div class="detail-box-body">
                                    {escape(f"{short_row['recommendation_label']} • {short_row['short_term_score']}/100" if short_row else "Not in the latest short-term recommendation list.")}
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="rank-cell">
                        <div class="detail-box">
                            <div class="detail-box-title">Monitoring</div>
                            <div class="detail-box-body">
                                Latest source: {escape(_source_meta(row_source).label)}<br/>
                                Last updated: {escape(format_timestamp(row_updated_at))}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        action_cols = st.columns([0.28, 0.20, 0.52], gap="small")
        if action_cols[0].button("Open Analysis", key=f"watch-open-{ticker}", use_container_width=True):
            _open_ticker(ticker)
        if action_cols[1].button("Remove", key=f"watch-remove-{ticker}", use_container_width=True):
            remove_from_watchlist(ticker)
            st.rerun()
