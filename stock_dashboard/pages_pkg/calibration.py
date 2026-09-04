from __future__ import annotations

import streamlit as st

from stock_dashboard.pages_pkg.formatters import (
    _format_pct_display,
    render_rank_sheet_header,
    render_section_intro,
    render_status_strip,
)


def render_calibration_page(calibration_results: dict) -> None:
    render_section_intro(
        "Calibration",
        "Diagnostics for whether the short-term model ranks signals in the right order.",
        "",
    )

    diagnostics = calibration_results.get("diagnostics", {})
    score_diag = diagnostics.get("score_calibration", {})
    regime_diag = diagnostics.get("regime_alignment", {})
    confidence_diag = diagnostics.get("confidence_alignment", {})
    accounting_diag = diagnostics.get("accounting_risk_alignment", {})

    def _diag_tone(status: str) -> str:
        if status == "Aligned":
            return "positive"
        if status == "Mixed":
            return "watch"
        if status == "Not aligned":
            return "negative"
        return "neutral"

    render_status_strip(
        [
            (f"Score {score_diag.get('status', 'Insufficient data')}", _diag_tone(score_diag.get("status", ""))),
            (f"Regime {regime_diag.get('status', 'Insufficient data')}", _diag_tone(regime_diag.get("status", ""))),
            (f"Confidence {confidence_diag.get('status', 'Insufficient data')}", _diag_tone(confidence_diag.get("status", ""))),
            (f"Accounting {accounting_diag.get('status', 'Insufficient data')}", _diag_tone(accounting_diag.get("status", ""))),
        ]
    )

    active_thresholds = calibration_results.get("active_thresholds", {})
    cost_model = calibration_results.get("cost_model", {})
    config_cols = st.columns(4, gap="small")
    config_cols[0].metric("Short Scan Floor", active_thresholds.get("min_short_term_scan_score", "N/A"))
    config_cols[1].metric("Execution Score", active_thresholds.get("min_execution_score", "N/A"))
    config_cols[2].metric("Pullback", _format_pct_display(active_thresholds.get("strategy_v1_pullback_pct")))
    config_cols[3].metric("Cost Drag", _format_pct_display(cost_model.get("estimated_transaction_cost_pct")))

    diagnostic_cols = st.columns(4, gap="small")
    for column, diagnostic in zip(
        diagnostic_cols,
        (score_diag, regime_diag, confidence_diag, accounting_diag),
    ):
        with column:
            with st.container(border=True):
                st.markdown(f"**{diagnostic.get('title', 'Diagnostic')}**")
                st.caption(diagnostic.get("expectation", ""))
                st.write(diagnostic.get("summary", "No diagnostic summary is available."))

    render_rank_sheet_header("Score Bucket Analysis")
    st.caption("Objective: higher score buckets should produce better expectancy, win rates, and realized returns.")
    score_rows = calibration_results.get("score_buckets", [])
    if score_rows:
        st.dataframe(score_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No resolved score-bucket data is available yet.")

    render_rank_sheet_header("Strategy Comparison")
    st.caption("Compare 1-2 day trades against 5-15 day swings on realized outcomes.")
    strategy_rows = calibration_results.get("strategy_comparison", [])
    if strategy_rows:
        st.dataframe(strategy_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No strategy comparison data is available yet.")

    render_rank_sheet_header("Regime Calibration")
    st.caption("Compare momentum and mean-reversion cohorts after modeled transaction costs.")
    regime_rows = calibration_results.get("regime_comparison", [])
    if regime_rows:
        st.dataframe(regime_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No regime calibration data is available yet.")

    secondary_cols = st.columns(2, gap="large")
    with secondary_cols[0]:
        render_rank_sheet_header("Recommendation Confidence vs Outcomes")
        st.caption("Checks whether higher stated confidence is earning better expectancy and realized outcomes.")
        confidence_rows = calibration_results.get("confidence_analysis", [])
        if confidence_rows:
            st.dataframe(confidence_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No resolved confidence-band data is available yet.")

    with secondary_cols[1]:
        render_rank_sheet_header("Accounting Risk vs Outcomes")
        st.caption("Checks whether higher shenanigan risk is associated with weaker expectancy and realized outcomes.")
        accounting_rows = calibration_results.get("accounting_risk_analysis", [])
        if accounting_rows:
            st.dataframe(accounting_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No resolved accounting-risk data is available yet.")

    render_rank_sheet_header("Edge Filter Thresholds")
    st.caption("Use this ladder to see whether higher minimum scores improve expectancy before lower buckets dilute edge.")
    calibration_edge = calibration_results.get("edge_filter", {}).get("by_strategy", {}).get("all_short_term", [])
    if calibration_edge:
        st.dataframe(
            [
                {
                    "Threshold": row.get("threshold_label"),
                    "Signals": int(row.get("total_signals") or 0),
                    "Resolved": int(row.get("resolved_signals") or 0),
                    "Win Rate": f"{row.get('win_rate'):.1f}%" if row.get("win_rate") is not None else "N/A",
                    "Avg Return": _format_pct_display(row.get("avg_return_pct")),
                    "Expectancy": _format_pct_display(row.get("expectancy_pct")),
                    "Sample": row.get("sample_note", "Established"),
                }
                for row in calibration_edge
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No threshold-filter comparison is available yet.")
