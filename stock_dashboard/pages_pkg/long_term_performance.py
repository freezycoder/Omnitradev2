from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from stock_dashboard.pages_pkg.formatters import _format_pct_display, render_section_intro, render_status_strip
from stock_dashboard.ui import render_macro_strip


POSITIVE_COLOR = "#66d99a"
NEGATIVE_COLOR = "#e26d5c"
NEUTRAL_COLOR = "#7f8da3"
OPEN_COLOR = "#4f8cff"
RESOLVED_COLOR = "#66d99a"
AMBER_COLOR = "#d8b45d"


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tone(value: float | None) -> str:
    if value is None:
        return "Neutral"
    if value > 0:
        return "Positive"
    if value < 0:
        return "Negative"
    return "Neutral"


def _metric_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "Segment": row.get("segment"),
            "Signals": int(row.get("total_signals") or 0),
            "Resolved": int(row.get("resolved_signals") or 0),
            "Open": int(row.get("open_signals") or 0),
            "Wins": int(row.get("wins") or 0),
            "Losses": int(row.get("losses") or 0),
            "Win Rate": _format_pct_display(row.get("win_rate"), 1) if row.get("win_rate") is not None else "N/A",
            "Avg Return": _format_pct_display(row.get("avg_return_pct")),
            "Avg Win": _format_pct_display(row.get("avg_win_pct")),
            "Avg Loss": _format_pct_display(row.get("avg_loss_pct")),
            "Expectancy": _format_pct_display(row.get("expectancy_pct")),
            "Max Loss": _format_pct_display(row.get("max_loss_pct")),
            "Risk": row.get("risk_flag", "No data"),
            "Sample": row.get("sample_quality", "Weak"),
        }
        for row in rows
    ]


def _cohort_stack_chart(rows: list[dict], title: str) -> None:
    chart_rows = []
    for row in rows:
        segment = row.get("segment")
        if not segment:
            continue
        chart_rows.append({"Segment": segment, "State": "Open", "Signals": int(row.get("open_signals") or 0)})
        chart_rows.append({"Segment": segment, "State": "Resolved", "Signals": int(row.get("resolved_signals") or 0)})

    df = pd.DataFrame(chart_rows)
    if df.empty or int(df["Signals"].sum()) == 0:
        st.info("No cohort distribution is available yet.")
        return

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("Segment:N", title=None, sort=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Signals:Q", title="Signals"),
            color=alt.Color(
                "State:N",
                scale=alt.Scale(domain=["Open", "Resolved"], range=[OPEN_COLOR, RESOLVED_COLOR]),
                legend=alt.Legend(title=None, orient="bottom"),
            ),
            tooltip=["Segment", "State", "Signals"],
        )
        .properties(height=230, title=title)
    )
    st.altair_chart(chart, width="stretch")


def _cohort_count_chart(rows: list[dict], title: str) -> None:
    chart_rows = [
        {
            "Segment": row.get("segment"),
            "Signals": int(row.get("total_signals") or 0),
            "Resolved": int(row.get("resolved_signals") or 0),
        }
        for row in rows
        if row.get("segment")
    ]
    df = pd.DataFrame(chart_rows)
    if df.empty or int(df["Signals"].sum()) == 0:
        st.info("No logged signals are available for this chart yet.")
        return

    chart = (
        alt.Chart(df)
        .mark_bar(color=NEUTRAL_COLOR)
        .encode(
            x=alt.X("Segment:N", title=None, sort=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Signals:Q", title="Logged signals"),
            tooltip=["Segment", "Signals", "Resolved"],
        )
        .properties(height=230, title=title)
    )
    st.altair_chart(chart, width="stretch")


def _long_term_expectancy_chart(rows: list[dict], title: str) -> None:
    chart_rows = []
    for row in rows:
        expectancy = _to_float(row.get("expectancy_pct"))
        resolved = int(row.get("resolved_signals") or 0)
        if expectancy is None or resolved == 0:
            continue
        chart_rows.append(
            {
                "Segment": row.get("segment"),
                "Expectancy %": expectancy,
                "Win Rate %": _to_float(row.get("win_rate")),
                "Resolved": resolved,
                "Tone": _tone(expectancy),
            }
        )

    df = pd.DataFrame(chart_rows)
    if df.empty:
        st.info("Outcome charts will activate once long-term horizons mature.")
        return

    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("Segment:N", title=None, sort=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y("Expectancy %:Q", title="Expectancy %"),
            color=alt.Color(
                "Tone:N",
                scale=alt.Scale(
                    domain=["Positive", "Negative", "Neutral"],
                    range=[POSITIVE_COLOR, NEGATIVE_COLOR, NEUTRAL_COLOR],
                ),
                legend=None,
            ),
            tooltip=["Segment", "Expectancy %", "Win Rate %", "Resolved"],
        )
        .properties(height=230, title=title)
    )
    st.altair_chart(chart, width="stretch")


def _open_maturity_chart(open_rows: list[dict]) -> None:
    chart_rows = []
    for row in open_rows:
        days_to_maturity = _to_float(row.get("days_to_maturity"))
        if days_to_maturity is None:
            continue
        chart_rows.append(
            {
                "Ticker": row.get("ticker"),
                "Horizon": row.get("horizon") or row.get("horizon_label") or row.get("holding_period_label") or "Open",
                "Days to Maturity": days_to_maturity,
                "Score": _to_float(row.get("score")),
            }
        )

    df = pd.DataFrame(chart_rows)
    if df.empty:
        st.info("No maturity runway data is available yet.")
        return

    chart = (
        alt.Chart(df)
        .mark_circle(size=85, opacity=0.8)
        .encode(
            x=alt.X("Days to Maturity:Q", title="Days until horizon closes"),
            y=alt.Y("Horizon:N", title=None, sort=None),
            color=alt.Color("Horizon:N", scale=alt.Scale(range=[OPEN_COLOR, AMBER_COLOR, NEUTRAL_COLOR]), legend=None),
            tooltip=["Ticker", "Horizon", "Days to Maturity", "Score"],
        )
        .properties(height=220, title="Open Signal Maturity Runway")
    )
    st.altair_chart(chart, width="stretch")


def render_long_term_performance_page(payload: dict) -> None:
    render_section_intro(
        "Long-term performance",
        "Long-term recommendation measurement loop.",
        "Tracks scan-generated Strong Buy / Buy decisions over 3M, 6M, and 12M horizons separately from short-term trading performance.",
    )

    overall = payload.get("overall", {})
    if not overall or int(overall.get("total_signals") or 0) == 0:
        st.info("No long-term signals have been logged yet. Run a live scan to start building the long-term track record.")
        return

    win_rate = _format_pct_display(overall.get("win_rate"), 1) if overall.get("win_rate") is not None else "N/A"
    render_macro_strip(
        [
            {"label": "Logged", "value": str(int(overall.get("total_signals") or 0)), "meta": "3M / 6M / 12M signals"},
            {"label": "Resolved", "value": str(int(overall.get("resolved_signals") or 0)), "meta": "Matured horizons"},
            {"label": "Open", "value": str(int(overall.get("open_signals") or 0)), "meta": "Still measuring"},
            {"label": "Win Rate", "value": win_rate, "meta": "Resolved horizons only"},
            {"label": "Expectancy", "value": _format_pct_display(overall.get("expectancy_pct")), "meta": "Per matured signal"},
            {"label": "Risk", "value": str(overall.get("risk_flag") or "No data"), "meta": f"Sample {overall.get('sample_quality', 'Weak')}"},
        ]
    )

    if int(overall.get("resolved_signals") or 0) == 0:
        render_status_strip(
            [
                ("Tracking active", "positive"),
                ("No matured 3M/6M/12M outcomes yet", "watch"),
                ("This page will become useful as horizons close", "neutral"),
            ]
        )
        st.caption(
            "Long-term signals are intentionally slow to validate. The current database started recently, so logged names will remain open until their 3M, 6M, or 12M horizon has elapsed."
        )
    elif overall.get("low_sample"):
        render_status_strip(
            [
                ("Early sample", "watch"),
                (f"Resolved {int(overall.get('resolved_signals') or 0)}", "neutral"),
                ("Do not overfit yet", "neutral"),
            ]
        )

    horizon_rows = _metric_rows(payload.get("by_horizon", []))
    score_rows = _metric_rows(payload.get("by_score_bucket", []))
    recommendation_rows = _metric_rows(payload.get("by_recommendation", []))
    accounting_rows = _metric_rows(payload.get("by_accounting_risk", []))
    trend_rows = _metric_rows(payload.get("by_trend", []))
    open_rows = payload.get("open_signals", [])

    st.markdown("**Long-Term Visuals**")
    visual_cols = st.columns(2, gap="large")
    with visual_cols[0]:
        _cohort_stack_chart(payload.get("by_horizon", []), "Horizon Coverage")
    with visual_cols[1]:
        _cohort_count_chart(payload.get("by_score_bucket", []), "Logged Signals by Score")

    mix_cols = st.columns(2, gap="large")
    with mix_cols[0]:
        _cohort_count_chart(payload.get("by_recommendation", []), "Recommendation Mix")
    with mix_cols[1]:
        _cohort_count_chart(payload.get("by_accounting_risk", []), "Accounting Risk Mix")

    outcome_cols = st.columns(2, gap="large")
    with outcome_cols[0]:
        _long_term_expectancy_chart(payload.get("by_horizon", []), "Expectancy by Horizon")
    with outcome_cols[1]:
        _open_maturity_chart(open_rows)

    st.markdown("**Horizon Breakdown**")
    if horizon_rows:
        st.dataframe(horizon_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No horizon data is available yet.")

    col_left, col_right = st.columns(2, gap="large")
    with col_left:
        st.markdown("**Score Buckets**")
        if score_rows:
            st.dataframe(score_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No score-bucket data is available yet.")

        st.markdown("**Recommendation Labels**")
        if recommendation_rows:
            st.dataframe(recommendation_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No recommendation-label data is available yet.")

    with col_right:
        st.markdown("**Accounting Risk**")
        if accounting_rows:
            st.dataframe(accounting_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No accounting-risk data is available yet.")

        st.markdown("**Long-Term Trend**")
        if trend_rows:
            st.dataframe(trend_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No trend data is available yet.")

    st.markdown("**Open Long-Term Signals**")
    if open_rows:
        st.dataframe(open_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No open long-term signals are currently being tracked.")

    st.markdown("**Recent Matured Outcomes**")
    recent_rows = payload.get("recent_resolved", [])
    if recent_rows:
        st.dataframe(recent_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No long-term horizons have matured yet.")


__all__ = ["render_long_term_performance_page"]
