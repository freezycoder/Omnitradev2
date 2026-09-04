from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from config.performance import STRATEGY_V1
from stock_dashboard.pages_pkg.formatters import (
    _edge_discovery_table,
    _edge_metric_lines,
    _entry_trigger_metric_lines,
    _format_pct_display,
    _format_price,
    _format_ratio_display,
    _sample_tone,
    render_rank_sheet_header,
    render_section_intro,
    render_status_strip,
)
from stock_dashboard.ui import render_macro_strip


POSITIVE_COLOR = "#66d99a"
NEGATIVE_COLOR = "#e26d5c"
NEUTRAL_COLOR = "#7f8da3"
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


def _signed_bar_chart(
    rows: list[dict],
    *,
    x_field: str,
    y_field: str,
    title: str,
    y_title: str,
    tooltip_fields: list[str] | None = None,
) -> None:
    df = pd.DataFrame(rows)
    if df.empty or x_field not in df.columns or y_field not in df.columns:
        st.info("Not enough data to draw this chart yet.")
        return

    df[y_field] = pd.to_numeric(df[y_field], errors="coerce")
    df = df.dropna(subset=[x_field, y_field])
    if df.empty:
        st.info("Not enough resolved data to draw this chart yet.")
        return

    df["Tone"] = df[y_field].map(_tone)
    tooltip = tooltip_fields or [x_field, y_field]
    chart = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(f"{x_field}:N", title=None, sort=None, axis=alt.Axis(labelAngle=0)),
            y=alt.Y(f"{y_field}:Q", title=y_title),
            color=alt.Color(
                "Tone:N",
                scale=alt.Scale(
                    domain=["Positive", "Negative", "Neutral"],
                    range=[POSITIVE_COLOR, NEGATIVE_COLOR, NEUTRAL_COLOR],
                ),
                legend=None,
            ),
            tooltip=tooltip,
        )
        .properties(height=230, title=title)
    )
    st.altair_chart(chart, width="stretch")


def _strategy_expectancy_chart(strategy_map: dict) -> None:
    labels = {
        "short_term_day": "1-2 Day",
        "short_term_swing": "5-15 Day",
    }
    rows = []
    for key, label in labels.items():
        summary = strategy_map.get(key)
        if not summary:
            continue
        rows.append(
            {
                "Strategy": label,
                "Expectancy %": _to_float(getattr(summary, "expectancy_pct", None)),
                "Win Rate %": _to_float(getattr(summary, "win_rate", None)),
                "Resolved": int(getattr(summary, "resolved_signals", 0) or 0),
            }
        )
    _signed_bar_chart(
        rows,
        x_field="Strategy",
        y_field="Expectancy %",
        title="Expectancy by Strategy",
        y_title="Expectancy %",
        tooltip_fields=["Strategy", "Expectancy %", "Win Rate %", "Resolved"],
    )


def _score_bucket_expectancy_chart(bucket_rows: list[dict]) -> None:
    rows = [
        {
            "Bucket": row.get("score_bucket"),
            "Expectancy %": _to_float(row.get("expectancy_pct")),
            "Win Rate %": _to_float(row.get("win_rate")),
            "Resolved": int(row.get("total_resolved") or 0),
        }
        for row in bucket_rows
    ]
    _signed_bar_chart(
        rows,
        x_field="Bucket",
        y_field="Expectancy %",
        title="Expectancy by Score Bucket",
        y_title="Expectancy %",
        tooltip_fields=["Bucket", "Expectancy %", "Win Rate %", "Resolved"],
    )


def _recent_return_curve(recent_rows: list[dict]) -> None:
    rows = []
    for row in recent_rows:
        realized = _to_float(row.get("realized_return_pct"))
        if realized is None:
            continue
        rows.append(
            {
                "Evaluated At": str(row.get("evaluated_at") or row.get("created_at") or ""),
                "Ticker": row.get("ticker"),
                "Return %": realized,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("No resolved return history is available for a curve yet.")
        return

    df = df.sort_values("Evaluated At").reset_index(drop=True)
    df["Trade #"] = df.index + 1
    df["Cumulative Return %"] = df["Return %"].cumsum()
    chart = (
        alt.Chart(df)
        .mark_line(point=True, color=POSITIVE_COLOR)
        .encode(
            x=alt.X("Trade #:Q", title="Resolved trade sequence"),
            y=alt.Y("Cumulative Return %:Q", title="Cumulative return %"),
            tooltip=["Trade #", "Ticker", "Return %", "Cumulative Return %", "Evaluated At"],
        )
        .properties(height=220, title="Recent Resolved Return Curve")
    )
    st.altair_chart(chart, width="stretch")


def _trigger_method_expectancy_chart(trigger_methods: list[dict]) -> None:
    rows = [
        {
            "Method": row.get("method_label"),
            "Expectancy %": _to_float(row.get("expectancy_pct")),
            "Win Rate %": _to_float(row.get("win_rate")),
            "Resolved": int(row.get("resolved_signals") or 0),
            "Risk Penalty": _to_float(row.get("risk_penalty")),
        }
        for row in trigger_methods
    ]
    _signed_bar_chart(
        rows,
        x_field="Method",
        y_field="Expectancy %",
        title="Entry Method Expectancy",
        y_title="Expectancy %",
        tooltip_fields=["Method", "Expectancy %", "Win Rate %", "Resolved", "Risk Penalty"],
    )


def _trigger_sensitivity_chart(trigger_sensitivity: dict) -> None:
    rows = []
    for row in trigger_sensitivity.get("methods", []):
        expectancy = _to_float(row.get("expectancy_pct"))
        trigger_rate = _to_float(row.get("trigger_rate"))
        capital_capture = _to_float(row.get("capital_capture_ratio"))
        if expectancy is None or trigger_rate is None:
            continue
        rows.append(
            {
                "Method": row.get("method_label"),
                "Expectancy %": expectancy,
                "Trigger Rate %": trigger_rate * 100,
                "Capital Capture %": (capital_capture or 0.0) * 100,
                "Deployment Adjusted Edge": _to_float(row.get("deployment_adjusted_edge")),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        st.info("Trigger sensitivity needs more data before it can be charted.")
        return

    df["Tone"] = df["Expectancy %"].map(_tone)
    chart = (
        alt.Chart(df)
        .mark_circle(size=130)
        .encode(
            x=alt.X("Trigger Rate %:Q", title="Trigger rate %"),
            y=alt.Y("Expectancy %:Q", title="Expectancy %"),
            color=alt.Color(
                "Tone:N",
                scale=alt.Scale(
                    domain=["Positive", "Negative", "Neutral"],
                    range=[POSITIVE_COLOR, NEGATIVE_COLOR, NEUTRAL_COLOR],
                ),
                legend=None,
            ),
            tooltip=["Method", "Expectancy %", "Trigger Rate %", "Capital Capture %", "Deployment Adjusted Edge"],
        )
        .properties(height=230, title="Capture vs Quality Tradeoff")
    )
    st.altair_chart(chart, width="stretch")


def render_performance_lab_page(performance_results: dict) -> None:
    render_section_intro(
        "Performance lab",
        "Measured short-term signal outcomes from the SQLite signal log.",
        "",
    )

    overall = performance_results.get("overall")
    if overall is None:
        st.info("Performance data is not available yet.")
        return

    overall_win_rate = f"{overall.win_rate:.1f}%" if overall.win_rate is not None else "N/A"
    overall_avg_return = f"{overall.avg_return_pct:+.2f}%" if overall.avg_return_pct is not None else "N/A"
    overall_expectancy = f"{overall.expectancy_pct:+.2f}%" if overall.expectancy_pct is not None else "N/A"
    render_macro_strip(
        [
            {"label": "Logged", "value": str(overall.total_signals), "meta": "Short-term signals"},
            {"label": "Resolved", "value": str(overall.resolved_signals), "meta": "Closed outcomes"},
            {"label": "Open", "value": str(overall.open_signals), "meta": "Awaiting resolution"},
            {"label": "Win Rate", "value": overall_win_rate, "meta": "Resolved signals only"},
            {"label": "Avg Return", "value": overall_avg_return, "meta": "Realized return"},
            {"label": "Expectancy", "value": overall_expectancy, "meta": "Edge per resolved trade"},
        ]
    )

    strategy_map = performance_results.get("by_strategy", {})
    bucket_rows = performance_results.get("score_buckets", [])
    recent_rows = performance_results.get("recent_outcomes", [])
    render_rank_sheet_header("Performance Visuals")
    visual_cols = st.columns(2, gap="large")
    with visual_cols[0]:
        _strategy_expectancy_chart(strategy_map)
    with visual_cols[1]:
        _score_bucket_expectancy_chart(bucket_rows)
    _recent_return_curve(recent_rows)

    edge_filter = performance_results.get("edge_filter", {})
    edge_by_strategy = edge_filter.get("by_strategy", {})
    threshold_options = edge_filter.get("threshold_options", ["All", "70+", "75+", "80+", "85+"])
    strategy_options = {
        "All strategies": "all_short_term",
        "1-2 Day Trades": "short_term_day",
        "5-15 Day Swings": "short_term_swing",
    }
    render_rank_sheet_header("Edge Filter")
    control_cols = st.columns([1.2, 1, 2.2], gap="small")
    with control_cols[0]:
        selected_strategy_label = st.selectbox(
            "Strategy Scope",
            list(strategy_options.keys()),
            key="performance-edge-strategy",
        )
    with control_cols[1]:
        selected_threshold = st.selectbox(
            "Score Threshold",
            threshold_options,
            index=threshold_options.index("80+") if "80+" in threshold_options else 0,
            key="performance-edge-threshold",
        )

    strategy_key = strategy_options[selected_strategy_label]
    threshold_rows = edge_by_strategy.get(strategy_key, [])
    all_row = next((row for row in threshold_rows if row.get("threshold_label") == "All"), None)
    filtered_row = next((row for row in threshold_rows if row.get("threshold_label") == selected_threshold), None)
    best_row = edge_filter.get("best_by_strategy", {}).get(strategy_key)

    status_items = []
    if filtered_row:
        expectancy = filtered_row.get("expectancy_pct")
        status_items.append(
            (
                f"{selected_threshold} expectancy {_format_pct_display(expectancy)}",
                "positive" if (expectancy or 0) > 0 else "watch" if expectancy is not None else "neutral",
            )
        )
        status_items.append(
            (
                f"{filtered_row.get('sample_quality', 'Weak')} sample • {filtered_row.get('sample_note', 'Established')}",
                _sample_tone(bool(filtered_row.get("low_sample")), int(filtered_row.get("resolved_signals") or 0)),
            )
        )
    if best_row:
        best_expectancy = best_row.get("expectancy_pct")
        status_items.append(
            (
                f"Best {best_row.get('threshold_label')} {_format_pct_display(best_expectancy)}",
                "positive" if (best_expectancy or 0) > 0 else "watch",
            )
        )
    if status_items:
        render_status_strip(status_items)

    compare_cols = st.columns(2, gap="large")
    with compare_cols[0]:
        with st.container(border=True):
            st.markdown("**All Signals**")
            if all_row:
                if all_row.get("low_sample"):
                    st.caption(all_row.get("sample_note", "Early sample"))
                st.markdown(_edge_metric_lines(all_row))
            else:
                st.info("No resolved signals are available for the full cohort yet.")

    with compare_cols[1]:
        with st.container(border=True):
            st.markdown(f"**Filtered Signals · {selected_threshold}**")
            if filtered_row:
                if filtered_row.get("low_sample"):
                    st.caption(filtered_row.get("sample_note", "Early sample"))
                st.markdown(_edge_metric_lines(filtered_row))
            else:
                st.info("No signals are available for this threshold yet.")

    ladder_rows = [
        {
            "Threshold": row.get("threshold_label"),
            "Signals": int(row.get("total_signals") or 0),
            "Resolved": int(row.get("resolved_signals") or 0),
            "Wins": int(row.get("wins") or 0),
            "Losses": int(row.get("losses") or 0),
            "Flats": int(row.get("flats") or 0),
            "Win Rate": f"{row.get('win_rate'):.1f}%" if row.get("win_rate") is not None else "N/A",
            "Avg Return": _format_pct_display(row.get("avg_return_pct")),
            "Avg Win": _format_pct_display(row.get("avg_win_pct")),
            "Avg Loss": _format_pct_display(row.get("avg_loss_pct")),
            "Expectancy": _format_pct_display(row.get("expectancy_pct")),
            "Risk-Adjusted": _format_ratio_display(row.get("risk_adjusted_view")),
            "Std Return": _format_pct_display(row.get("std_return_pct")),
            "Max Loss": _format_pct_display(row.get("max_loss_pct")),
            "Max DD": _format_pct_display(row.get("max_drawdown_pct")),
            "Loss Streak": int(row.get("max_consecutive_losses") or 0),
            "Risk Penalty": _format_ratio_display(row.get("risk_penalty")),
            "Risk Flag": row.get("risk_flag", "No data"),
            "Sample Quality": row.get("sample_quality", "Weak"),
            "Sample": row.get("sample_note", "Established"),
        }
        for row in threshold_rows
    ]
    st.caption("Compare the full cohort against high-score filters to see where expectancy actually improves.")
    if ladder_rows:
        st.dataframe(ladder_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No edge-filter data is available yet.")

    strategy_v1_execution = performance_results.get("strategy_v1_execution", {})
    execution_preset = strategy_v1_execution.get("preset", {})
    execution_counts = strategy_v1_execution.get("counts", {})
    execution_history = strategy_v1_execution.get("historical_expectancy") or {}
    top_pretrigger_rows = strategy_v1_execution.get("top_pretrigger_signals", [])
    top_triggered_rows = strategy_v1_execution.get("top_triggered_signals", [])
    ranked_triggered_rows = strategy_v1_execution.get("ranked_triggered_signals", [])
    execution_rows = strategy_v1_execution.get("deduplicated_signals", [])

    render_rank_sheet_header("Top Signals (Pre-Trigger Ranking)")
    st.caption("Highest-edge ticker-deduplicated setups before trigger, combining both waiting and triggered names from the same execution base.")
    pretrigger_table_rows = [
        {
            "Rank": row.get("pretrigger_rank"),
            "Ticker": row.get("ticker"),
            "Strategy": row.get("strategy_family"),
            "Edge Score": row.get("edge_quality_score"),
            "Position Size": row.get("position_size"),
            "Hist. Expectancy": _format_pct_display(row.get("historical_cohort_expectancy_pct")),
            "Trigger Status": str(row.get("trigger_status", "waiting")).title(),
        }
        for row in top_pretrigger_rows
    ]
    if pretrigger_table_rows:
        st.dataframe(pretrigger_table_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No pre-trigger signals are available yet.")

    render_rank_sheet_header("Strategy_v1 Execution")
    st.caption(
        f"ENTER NOW signals become executable only after an active Pullback {float(STRATEGY_V1.pullback_pct or 0.0):.2f}% below the original signal entry. "
        f"Pullback 1.00% remains the conservative benchmark in Trigger Sensitivity."
    )
    execution_filter_items = [
        (f"STATE: {execution_preset.get('trade_state', 'ENTER NOW')}", "neutral"),
        (f"SCORE: >= {execution_preset.get('min_score', '70')}", "neutral"),
        (f"TREND: {str(execution_preset.get('trend_direction', 'all')).upper()}", "neutral"),
        ("STRATEGY: All short-term", "neutral"),
        (f"ACTIVE RULE: Pullback {float(STRATEGY_V1.pullback_pct or 0.0):.2f}%", "watch"),
        ("CONSERVATIVE BENCHMARK: Pullback 1.00%", "neutral"),
    ]
    if top_triggered_rows:
        top_row = top_triggered_rows[0]
        execution_filter_items.append(
            (
                f"TOP: {top_row.get('ticker', 'N/A')} edge {top_row.get('edge_quality_score', 'N/A')} • size {top_row.get('position_size', 'N/A')}",
                "positive",
            )
        )
    render_status_strip(execution_filter_items)

    execution_macro = [
        {
            "label": "Waiting",
            "value": str(int(execution_counts.get("waiting_signals") or 0)),
            "meta": "Below trigger not reached",
        },
        {
            "label": "Triggered",
            "value": str(int(execution_counts.get("triggered_signals") or 0)),
            "meta": "Ready by trigger rule",
        },
        {
            "label": "Open Signals",
            "value": str(int(execution_counts.get("total_signals") or 0)),
            "meta": "Active cohort size",
        },
        {
            "label": "Per-Ticker",
            "value": str(int(execution_counts.get("execution_deduplicated_signals") or 0)),
            "meta": "Highest edge per ticker",
        },
        {
            "label": "Cohort Expectancy",
            "value": _format_pct_display(execution_history.get("expectancy_pct")),
            "meta": execution_history.get("sample_note", "No historical cohort yet"),
        },
        {
            "label": "Strategy PnL",
            "value": _format_pct_display(execution_history.get("realized_pnl_pct")),
            "meta": f"Vs baseline {_format_pct_display(execution_history.get('pnl_vs_baseline_pct'))}",
        },
    ]
    if int(execution_counts.get("unavailable_signals") or 0):
        execution_macro.append(
            {
                "label": "Price Unavailable",
                "value": str(int(execution_counts.get("unavailable_signals") or 0)),
                "meta": "Live/cached price missing",
            }
        )
    render_macro_strip(execution_macro)

    execution_compare_cols = st.columns(2, gap="large")
    with execution_compare_cols[0]:
        with st.container(border=True):
            st.markdown("**Execution State**")
            st.markdown(
                "\n".join(
                    [
                        f"- Waiting: {int(execution_counts.get('waiting_signals') or 0)}",
                        f"- Triggered: {int(execution_counts.get('triggered_signals') or 0)}",
                        f"- Open cohort: {int(execution_counts.get('total_signals') or 0)}",
                        f"- Analysis dedupe (ticker / strategy / day): {int(execution_counts.get('analysis_deduplicated_signals') or 0)}",
                        f"- Execution dedupe (ticker only): {int(execution_counts.get('execution_deduplicated_signals') or 0)}",
                        f"- Execution triggered (ticker only): {int(execution_counts.get('execution_deduplicated_triggered_signals') or 0)}",
                    ]
                )
            )
    with execution_compare_cols[1]:
        with st.container(border=True):
            st.markdown("**Historical Cohort**")
            if execution_history:
                if execution_history.get("sample_note"):
                    st.caption(execution_history.get("sample_quality", "Weak") + " sample • " + execution_history.get("sample_note", ""))
                st.markdown(_entry_trigger_metric_lines(execution_history))
            else:
                st.info("No resolved cohort is available yet for this execution rule.")

    top_trigger_table_rows = [
        {
            "Rank": row.get("rank"),
            "Ticker": row.get("ticker"),
            "Strategy": row.get("strategy_family"),
            "Score": row.get("score"),
            "Edge Score": row.get("edge_quality_score"),
            "Position Size": row.get("position_size"),
            "Raw Weight": row.get("raw_weight"),
            "Sizing Reason": row.get("sizing_reason"),
            "Current Price": _format_price(row.get("current_price")),
            "Trigger Price": _format_price(row.get("trigger_price")),
            "Distance to Trigger": _format_pct_display(row.get("distance_to_trigger_pct")),
            "Hist. Expectancy": _format_pct_display(row.get("historical_cohort_expectancy_pct")),
            "Hist. Win Rate": _format_pct_display(row.get("historical_cohort_win_rate"), 1),
            "Sample": row.get("historical_cohort_resolved_signals"),
            "Risk Flag": row.get("historical_cohort_risk_flag"),
            "Risk Penalty": _format_ratio_display(row.get("historical_cohort_risk_penalty")),
            "Max DD": _format_pct_display(row.get("historical_cohort_max_drawdown_pct")),
            "Realized PnL": _format_pct_display(execution_history.get("realized_pnl_pct")),
            "Vs Baseline": _format_pct_display(execution_history.get("pnl_vs_baseline_pct")),
            "Recency (hrs)": row.get("signal_age_hours"),
            "Vol Proxy": _format_pct_display(row.get("volatility_proxy_pct")),
        }
        for row in top_triggered_rows
    ]
    render_rank_sheet_header("Top Triggered Signals (One Per Ticker)")
    if top_trigger_table_rows:
        st.dataframe(top_trigger_table_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No signals are currently below their pullback trigger.")

    ranked_trigger_table_rows = [
        {
            "Rank": row.get("rank"),
            "Ticker": row.get("ticker"),
            "Company": row.get("company_name"),
            "Strategy": row.get("strategy_family"),
            "Score": row.get("score"),
            "Edge Score": row.get("edge_quality_score"),
            "Position Size": row.get("position_size"),
            "Raw Weight": row.get("raw_weight"),
            "Sizing Reason": row.get("sizing_reason"),
            "Current Price": _format_price(row.get("current_price")),
            "Trigger Price": _format_price(row.get("trigger_price")),
            "Distance to Trigger": _format_pct_display(row.get("distance_to_trigger_pct")),
            "Hist. Expectancy": _format_pct_display(row.get("historical_cohort_expectancy_pct")),
            "Hist. Win Rate": _format_pct_display(row.get("historical_cohort_win_rate"), 1),
            "Sample": row.get("historical_cohort_resolved_signals"),
            "Risk Flag": row.get("historical_cohort_risk_flag"),
            "Risk Penalty": _format_ratio_display(row.get("historical_cohort_risk_penalty")),
            "Max DD": _format_pct_display(row.get("historical_cohort_max_drawdown_pct")),
            "Realized PnL": _format_pct_display(execution_history.get("realized_pnl_pct")),
            "Vs Baseline": _format_pct_display(execution_history.get("pnl_vs_baseline_pct")),
            "Recency (hrs)": row.get("signal_age_hours"),
            "Vol Proxy": _format_pct_display(row.get("volatility_proxy_pct")),
            "Signal Source": row.get("source_quality"),
            "Price Source": row.get("price_source"),
        }
        for row in ranked_triggered_rows
    ]
    if ranked_trigger_table_rows:
        st.dataframe(ranked_trigger_table_rows, use_container_width=True, hide_index=True)

    execution_table_rows = [
        {
            "Ticker": row.get("ticker"),
            "Company": row.get("company_name"),
            "Strategy": row.get("strategy_family"),
            "Score": row.get("score"),
            "Recommendation": row.get("recommendation_label"),
            "Edge Score": row.get("edge_quality_score"),
            "Position Size": row.get("position_size"),
            "Raw Weight": row.get("raw_weight"),
            "Sizing Reason": row.get("sizing_reason"),
            "Current Price": _format_price(row.get("current_price")),
            "Trigger Price": _format_price(row.get("trigger_price")),
            "Trigger Status": str(row.get("trigger_status", "waiting")).title(),
            "Distance to Trigger": _format_pct_display(row.get("distance_to_trigger_pct")),
            "Hist. Expectancy": _format_pct_display(row.get("historical_cohort_expectancy_pct")),
            "Hist. Win Rate": _format_pct_display(row.get("historical_cohort_win_rate"), 1),
            "Sample": row.get("historical_cohort_resolved_signals"),
            "Risk Flag": row.get("historical_cohort_risk_flag"),
            "Risk Penalty": _format_ratio_display(row.get("historical_cohort_risk_penalty")),
            "Max DD": _format_pct_display(row.get("historical_cohort_max_drawdown_pct")),
            "Realized PnL": _format_pct_display(execution_history.get("realized_pnl_pct")),
            "Vs Baseline": _format_pct_display(execution_history.get("pnl_vs_baseline_pct")),
            "Recency (hrs)": row.get("signal_age_hours"),
            "Vol Proxy": _format_pct_display(row.get("volatility_proxy_pct")),
            "Signal Entry": _format_price(row.get("signal_entry_price")),
            "Signal Source": row.get("source_quality"),
            "Price Source": row.get("price_source"),
        }
        for row in execution_rows
    ]
    render_rank_sheet_header("Execution Signals (One Per Ticker)")
    if execution_table_rows:
        st.dataframe(execution_table_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No active ENTER NOW signals currently match Strategy_v1.")

    entry_trigger_lab = performance_results.get("entry_trigger_lab", {})
    trigger_strategy_options = {
        "1-2 Day Trades": "short_term_day",
        "5-15 Day Swings": "short_term_swing",
    }
    default_trigger_strategy = "1-2 Day Trades" if strategy_key == "all_short_term" else next(
        (label for label, key in trigger_strategy_options.items() if key == strategy_key),
        "1-2 Day Trades",
    )
    trigger_strategy_label = st.selectbox(
        "Entry Trigger Strategy",
        list(trigger_strategy_options.keys()),
        index=list(trigger_strategy_options.keys()).index(default_trigger_strategy),
        key="performance-entry-trigger-strategy",
    )
    trigger_strategy_key = trigger_strategy_options[trigger_strategy_label]
    trigger_scope = entry_trigger_lab.get(trigger_strategy_key, {})
    trigger_methods = trigger_scope.get("methods", [])
    trigger_min_resolved = int(trigger_scope.get("min_resolved") or 15)
    trigger_best = trigger_scope.get("best_method")
    trigger_filters = trigger_scope.get("cohort_filters", {})
    baseline_method = next((row for row in trigger_methods if row.get("method_type") == "immediate"), None)
    alternative_methods = [row for row in trigger_methods if row.get("method_type") != "immediate"]
    best_alternative = max(
        alternative_methods,
        key=lambda row: (
            float(row.get("expectancy_pct") or -9999.0),
            float(row.get("avg_return_pct") or -9999.0),
            int(row.get("resolved_signals") or 0),
        ),
    ) if alternative_methods else None

    render_rank_sheet_header("Entry Trigger Lab")
    st.caption(
        f"Compare delayed entries against the original ENTER NOW baseline using the same logged signals and realized outcome windows. "
        f"Methods need at least {trigger_min_resolved} resolved triggered trades to count as established."
    )
    filter_items = []
    if trigger_filters:
        filter_items = [
            (f"STATE: {trigger_filters.get('trade_state', 'N/A')}", "neutral"),
            (f"SCORE: >= {trigger_filters.get('min_score', 'N/A')}", "neutral"),
            (f"TREND: {str(trigger_filters.get('trend_direction', 'N/A')).upper()}", "neutral"),
            (f"STRATEGY: {trigger_strategy_label}", "neutral"),
        ]
    if filter_items:
        render_status_strip(filter_items)
    trigger_status = []
    if trigger_best:
        best_expectancy = trigger_best.get("expectancy_pct")
        trigger_status.append(
            (
                f"Best {trigger_best.get('method_label')} {_format_pct_display(best_expectancy)}",
                "positive" if (best_expectancy or 0) > 0 else "watch",
            )
        )
        trigger_status.append(
            (
                f"{trigger_best.get('sample_quality', 'Weak')} sample • {trigger_best.get('sample_note', 'Established')}",
                _sample_tone(bool(trigger_best.get("low_sample")), int(trigger_best.get("resolved_signals") or 0)),
            )
        )
    if trigger_status:
        render_status_strip(trigger_status)

    trigger_compare_cols = st.columns(2, gap="large")
    with trigger_compare_cols[0]:
        with st.container(border=True):
            st.markdown("**Immediate Entry Baseline**")
            if baseline_method:
                if baseline_method.get("low_sample"):
                    st.caption(baseline_method.get("sample_note", "Early sample"))
                st.markdown(_entry_trigger_metric_lines(baseline_method))
            else:
                st.info("No resolved ENTER NOW baseline sample is available yet.")

    with trigger_compare_cols[1]:
        with st.container(border=True):
            st.markdown("**Best Alternative Trigger**")
            if best_alternative:
                if best_alternative.get("low_sample"):
                    st.caption(best_alternative.get("sample_note", "Early sample"))
                st.markdown(f"**Method:** {best_alternative.get('method_label')}")
                st.markdown(_entry_trigger_metric_lines(best_alternative))
            else:
                st.info("No alternative trigger has enough resolved data yet.")

    trigger_visual_cols = st.columns(2, gap="large")
    with trigger_visual_cols[0]:
        _trigger_method_expectancy_chart(trigger_methods)
    with trigger_visual_cols[1]:
        _trigger_sensitivity_chart(performance_results.get("trigger_sensitivity", {}))

    trigger_rows = [
        {
            "Method": row.get("method_label"),
            "Resolved": int(row.get("resolved_signals") or 0),
            "Wins": int(row.get("wins") or 0),
            "Losses": int(row.get("losses") or 0),
            "Flats": int(row.get("flats") or 0),
            "Win Rate": f"{row.get('win_rate'):.1f}%" if row.get("win_rate") is not None else "N/A",
            "Avg Return": _format_pct_display(row.get("avg_return_pct")),
            "Avg Win": _format_pct_display(row.get("avg_win_pct")),
            "Avg Loss": _format_pct_display(row.get("avg_loss_pct")),
            "Expectancy": _format_pct_display(row.get("expectancy_pct")),
            "Realized PnL": _format_pct_display(row.get("realized_pnl_pct")),
            "PnL vs Baseline": _format_pct_display(row.get("pnl_vs_baseline_pct")),
            "Risk-Adjusted": _format_ratio_display(row.get("risk_adjusted_view")),
            "Std Return": _format_pct_display(row.get("std_return_pct")),
            "Max Loss": _format_pct_display(row.get("max_loss_pct")),
            "Max DD": _format_pct_display(row.get("max_drawdown_pct")),
            "Loss Streak": int(row.get("max_consecutive_losses") or 0),
            "Risk Penalty": _format_ratio_display(row.get("risk_penalty")),
            "Risk Flag": row.get("risk_flag", "No data"),
            "Vs Baseline": _format_pct_display(row.get("improvement_vs_baseline_pct")),
            "Sample Quality": row.get("sample_quality", "Weak"),
            "Sample": row.get("sample_note", "Established"),
        }
        for row in trigger_methods
    ]
    if trigger_rows:
        st.dataframe(trigger_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No entry-trigger lab data is available yet.")

    edge_discovery = performance_results.get("edge_discovery", {})
    discovery_by_strategy = edge_discovery.get("by_strategy", {})
    discovery_scope = discovery_by_strategy.get(strategy_key, {})
    top_segments = discovery_scope.get("top_segments", [])
    worst_segments = discovery_scope.get("worst_segments", [])
    min_resolved = int(edge_discovery.get("min_resolved") or 15)

    render_rank_sheet_header("Edge Discovery")
    st.caption(
        f"Top and worst segment combinations with at least {min_resolved} resolved outcomes. "
        "This helps show where real expectancy exists across score, state, trend, recommendation, and source."
    )
    discovery_status = []
    if top_segments:
        best_segment = top_segments[0]
        best_expectancy = best_segment.get("expectancy_pct")
        best_meta = best_segment.get("segment", {})
        discovery_status.append(
            (
                f"Best {best_meta.get('score_bucket', 'N/A')} · {best_meta.get('trade_state', 'N/A')} {_format_pct_display(best_expectancy)}",
                "positive" if (best_expectancy or 0) > 0 else "watch",
            )
        )
    if worst_segments:
        worst_segment = worst_segments[0]
        worst_expectancy = worst_segment.get("expectancy_pct")
        worst_meta = worst_segment.get("segment", {})
        discovery_status.append(
            (
                f"Worst {worst_meta.get('score_bucket', 'N/A')} · {worst_meta.get('trade_state', 'N/A')} {_format_pct_display(worst_expectancy)}",
                "negative" if (worst_expectancy or 0) < 0 else "watch",
            )
        )
    if discovery_status:
        render_status_strip(discovery_status)

    discovery_cols = st.columns(2, gap="large")
    with discovery_cols[0]:
        render_status_strip([("Top Performing Segments", "positive")])
        if top_segments:
            st.dataframe(_edge_discovery_table(top_segments), use_container_width=True, hide_index=True)
        else:
            st.info("No segment combinations meet the minimum resolved-sample threshold yet.")
    with discovery_cols[1]:
        render_status_strip([("Worst Performing Segments", "negative")])
        if worst_segments:
            st.dataframe(_edge_discovery_table(worst_segments), use_container_width=True, hide_index=True)
        else:
            st.info("No low-performing segment combinations meet the minimum resolved-sample threshold yet.")

    strategy_labels = {
        "short_term_day": "1-2 Day Trades",
        "short_term_swing": "5-15 Day Swings",
    }
    render_rank_sheet_header("Strategy Breakdown")
    strategy_rows = []
    for strategy_key in ("short_term_day", "short_term_swing"):
        summary = strategy_map.get(strategy_key)
        strategy_rows.append(
            {
                "Strategy": strategy_labels[strategy_key],
                "Signals": summary.total_signals if summary else 0,
                "Resolved": summary.resolved_signals if summary else 0,
                "Win Rate": f"{summary.win_rate:.1f}%" if summary and summary.win_rate is not None else "N/A",
                "Avg Return": f"{summary.avg_return_pct:+.2f}%" if summary and summary.avg_return_pct is not None else "N/A",
                "Expectancy": f"{summary.expectancy_pct:+.2f}%" if summary and summary.expectancy_pct is not None else "N/A",
                "Risk-Adjusted": _format_ratio_display(getattr(summary, "risk_adjusted_view", None)),
                "Std Return": _format_pct_display(getattr(summary, "std_return_pct", None)),
                "Max Loss": _format_pct_display(getattr(summary, "max_loss_pct", None)),
                "Max DD": _format_pct_display(getattr(summary, "max_drawdown_pct", None)),
                "Loss Streak": getattr(summary, "max_consecutive_losses", 0) if summary else 0,
                "Risk Penalty": _format_ratio_display(getattr(summary, "risk_penalty", None)),
                "Risk Flag": getattr(summary, "risk_flag", "No data") if summary else "No data",
                "Wins / Losses / Flats": (
                    f"{summary.wins} / {summary.losses} / {summary.flats}" if summary else "0 / 0 / 0"
                ),
                "Target / Stop / Expired": (
                    f"{summary.target_hits} / {summary.stop_hits} / {summary.expired_signals}" if summary else "0 / 0 / 0"
                ),
            }
        )
    st.dataframe(strategy_rows, use_container_width=True, hide_index=True)

    render_rank_sheet_header("Score Buckets")
    if bucket_rows:
        st.dataframe(bucket_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No resolved score-bucket data is available yet.")

    render_rank_sheet_header("Recent Resolved Signals")
    if recent_rows:
        st.dataframe(recent_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No resolved signals have been recorded yet.")
