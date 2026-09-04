from __future__ import annotations

import pandas as pd
import streamlit as st

from config.performance import STRATEGY_V1
from stock_dashboard.pages_pkg.formatters import (
    _format_pct_display,
    _format_price,
    _format_ratio_display,
    render_rank_sheet_header,
    render_section_intro,
    render_status_strip,
)
from stock_dashboard.ui import render_macro_strip


def render_portfolio_page(performance_results: dict) -> None:
    render_section_intro(
        "Portfolio",
        "Triggered allocation engine built from the deduplicated execution list.",
        "",
    )

    portfolio_payload = performance_results.get("strategy_v1_portfolio", {})
    portfolio_summary = portfolio_payload.get("summary", {})
    portfolio_holdings = portfolio_payload.get("holdings", [])
    benchmark_portfolio_payload = performance_results.get("strategy_v1_benchmark_portfolio", {})
    benchmark_portfolio_summary = benchmark_portfolio_payload.get("summary", {})
    portfolio_pnl = performance_results.get("strategy_v1_portfolio_pnl", {})
    portfolio_pnl_summary = portfolio_pnl.get("summary", {})
    portfolio_pnl_holdings = portfolio_pnl.get("holdings", [])
    benchmark_portfolio_pnl = performance_results.get("strategy_v1_benchmark_portfolio_pnl", {})
    benchmark_portfolio_pnl_summary = benchmark_portfolio_pnl.get("summary", {})
    baseline_rows = portfolio_pnl.get("baseline_comparison", [])
    capture_metrics = performance_results.get("strategy_v1_capture_metrics", {})
    trigger_sensitivity = performance_results.get("trigger_sensitivity", {})
    trigger_sensitivity_rows = trigger_sensitivity.get("methods", [])
    trigger_sensitivity_live = trigger_sensitivity.get("live_method")
    trigger_sensitivity_shadow = next(
        (
            row
            for row in trigger_sensitivity_rows
            if str(row.get("method_type")) == "pullback" and float(row.get("pullback_pct") or 0.0) == 1.0
        ),
        None,
    )
    trigger_sensitivity_best_expectancy = trigger_sensitivity.get("best_method_by_expectancy")
    trigger_sensitivity_best_deployment = trigger_sensitivity.get("best_method_by_deployment_adjusted_edge")
    trigger_sensitivity_best_risk = trigger_sensitivity.get("best_method_by_risk_adjusted_edge")
    trigger_sensitivity_risk_formula = trigger_sensitivity.get("risk_adjusted_edge_formula")
    strategy_history = performance_results.get("strategy_v1_strategy_history", {})
    strategy_history_summary = strategy_history.get("summary", {})
    trigger_series = strategy_history.get("trigger_series", [])
    quality_series = strategy_history.get("quality_series", [])
    portfolio_history = performance_results.get("strategy_v1_portfolio_history", {})
    portfolio_history_summary = portfolio_history.get("summary", {})
    portfolio_history_comparison_summary = portfolio_history.get("comparison_summary", {})
    equity_curve = portfolio_history.get("equity_curve", [])
    drawdown_curve = portfolio_history.get("drawdown_curve", [])
    capital_curve = portfolio_history.get("capital_curve", [])
    comparison_curve = portfolio_history.get("comparison_curve", [])

    render_rank_sheet_header("Active vs Benchmark Portfolio")
    st.caption("Compare the live Strategy_v1 portfolio against the conservative Pullback 1.00% shadow benchmark using the same allocation, sizing, and risk framework.")
    compare_cols = st.columns(2, gap="large")
    with compare_cols[0]:
        with st.container(border=True):
            st.markdown("**Active Strategy_v1 · Pullback 0.50%**")
            st.markdown(
                "\n".join(
                    [
                        f"- Holdings: {int(portfolio_summary.get('holdings_count') or 0)}",
                        f"- Deployed capital: {_format_pct_display((float(portfolio_pnl_summary.get('deployed_capital_weight') or 0.0) * 100.0), 1)}",
                        f"- Cash reserve: {_format_pct_display((float(portfolio_pnl_summary.get('cash_reserve_weight') or 0.0) * 100.0), 1)}",
                        f"- Weighted expectancy: {_format_pct_display(portfolio_summary.get('weighted_average_expectancy_pct'))}",
                        f"- Weighted risk penalty: {_format_ratio_display(portfolio_summary.get('weighted_average_risk_penalty'))}",
                        f"- Realized PnL: {_format_pct_display(portfolio_pnl_summary.get('realized_pnl_pct'))}",
                        f"- Unrealized PnL: {_format_pct_display(portfolio_pnl_summary.get('unrealized_pnl_pct'))}",
                        f"- Total PnL: {_format_pct_display(portfolio_pnl_summary.get('total_portfolio_pnl_pct'))}",
                    ]
                )
            )
    with compare_cols[1]:
        with st.container(border=True):
            st.markdown("**Conservative Benchmark · Pullback 1.00%**")
            st.markdown(
                "\n".join(
                    [
                        f"- Holdings: {int(benchmark_portfolio_summary.get('holdings_count') or 0)}",
                        f"- Deployed capital: {_format_pct_display((float(benchmark_portfolio_pnl_summary.get('deployed_capital_weight') or 0.0) * 100.0), 1)}",
                        f"- Cash reserve: {_format_pct_display((float(benchmark_portfolio_pnl_summary.get('cash_reserve_weight') or 0.0) * 100.0), 1)}",
                        f"- Weighted expectancy: {_format_pct_display(benchmark_portfolio_summary.get('weighted_average_expectancy_pct'))}",
                        f"- Weighted risk penalty: {_format_ratio_display(benchmark_portfolio_summary.get('weighted_average_risk_penalty'))}",
                        f"- Realized PnL: {_format_pct_display(benchmark_portfolio_pnl_summary.get('realized_pnl_pct'))}",
                        f"- Unrealized PnL: {_format_pct_display(benchmark_portfolio_pnl_summary.get('unrealized_pnl_pct'))}",
                        f"- Total PnL: {_format_pct_display(benchmark_portfolio_pnl_summary.get('total_portfolio_pnl_pct'))}",
                    ]
                )
            )

    render_macro_strip(
        [
            {
                "label": "Return Diff",
                "value": _format_pct_display(
                    (float(portfolio_pnl_summary.get("total_portfolio_pnl_pct") or 0.0))
                    - (float(benchmark_portfolio_pnl_summary.get("total_portfolio_pnl_pct") or 0.0))
                ),
                "meta": "Active minus benchmark total PnL",
            },
            {
                "label": "Deployment Diff",
                "value": _format_pct_display(
                    (
                        (float(portfolio_pnl_summary.get("deployed_capital_weight") or 0.0))
                        - (float(benchmark_portfolio_pnl_summary.get("deployed_capital_weight") or 0.0))
                    )
                    * 100.0,
                    1,
                ),
                "meta": "Active minus benchmark deployed capital",
            },
            {
                "label": "Holdings Diff",
                "value": str(
                    int(portfolio_summary.get("holdings_count") or 0)
                    - int(benchmark_portfolio_summary.get("holdings_count") or 0)
                ),
                "meta": "Active minus benchmark holdings",
            },
        ]
    )

    render_rank_sheet_header("Portfolio Engine")
    st.caption(
        f"Normalized portfolio weights built only from deduplicated triggered signals with positive expectancy and positive size. "
        f"Active Rule: Pullback {float(STRATEGY_V1.pullback_pct or 0.0):.2f}% · Conservative Benchmark: Pullback 1.00%."
    )
    render_macro_strip(
        [
            {
                "label": "Holdings",
                "value": str(int(portfolio_summary.get("holdings_count") or 0)),
                "meta": "Allocated names",
            },
            {
                "label": "Eligible",
                "value": str(int(portfolio_summary.get("eligible_signals_count") or 0)),
                "meta": "Triggered names passing filters",
            },
            {
                "label": "Weighted Exp.",
                "value": _format_pct_display(portfolio_summary.get("weighted_average_expectancy_pct")),
                "meta": "Portfolio-weighted expectancy",
            },
            {
                "label": "Weighted Risk",
                "value": _format_ratio_display(portfolio_summary.get("weighted_average_risk_penalty")),
                "meta": "Portfolio-weighted risk penalty",
            },
            {
                "label": "Top 3 Conc.",
                "value": _format_pct_display(portfolio_summary.get("concentration_top_3_pct"), 1),
                "meta": "Top 3 weight share",
            },
            {
                "label": "Cash Reserve",
                "value": _format_pct_display((float(portfolio_summary.get("cash_reserve_weight") or 0.0) * 100.0), 1),
                "meta": "Unallocated due to caps",
            },
            {
                "label": "Weight Check",
                "value": f"{float(portfolio_summary.get('total_weight_check') or 0.0):.4f}",
                "meta": "Should equal 1.0000",
            },
        ]
    )
    if portfolio_summary.get("cash_reserve_reason"):
        st.caption(str(portfolio_summary.get("cash_reserve_reason")))

    render_rank_sheet_header("Eligibility Breakdown")
    breakdown_rows = [
        {
            "Stage": "Triggered signals",
            "Count": int(portfolio_summary.get("total_triggered_signals") or 0),
            "Meaning": "Triggered names from the strict one-per-ticker execution list",
        },
        {
            "Stage": "Positive expectancy signals",
            "Count": int(portfolio_summary.get("positive_expectancy_signals_count") or 0),
            "Meaning": "Triggered names with historical expectancy above zero",
        },
        {
            "Stage": "Eligible after risk filter",
            "Count": int(portfolio_summary.get("eligible_after_risk_filter_count") or 0),
            "Meaning": "Names still carrying positive raw weight after risk adjustment",
        },
        {
            "Stage": "Included holdings",
            "Count": int(portfolio_summary.get("holdings_count") or 0),
            "Meaning": "Final capped portfolio names",
        },
    ]
    st.dataframe(breakdown_rows, use_container_width=True, hide_index=True)

    render_rank_sheet_header("Execution Capture")
    st.caption("How much of the currently eligible strategy edge is actually reaching triggered and deployed portfolio exposure.")
    render_macro_strip(
        [
            {
                "label": "Trigger Rate",
                "value": _format_pct_display((float(capture_metrics.get("trigger_rate") or 0.0) * 100.0), 1),
                "meta": "Triggered / eligible",
            },
            {
                "label": "Wait Ratio",
                "value": _format_pct_display((float(capture_metrics.get("wait_ratio") or 0.0) * 100.0), 1),
                "meta": "Waiting / eligible",
            },
            {
                "label": "Deployed Capital",
                "value": _format_pct_display((float(capture_metrics.get("deployed_capital_weight") or 0.0) * 100.0), 1),
                "meta": "Current portfolio deployment",
            },
            {
                "label": "Edge Capture Ratio",
                "value": _format_pct_display((float(capture_metrics.get("edge_capture_ratio") or 0.0) * 100.0), 1),
                "meta": "Holdings / eligible",
            },
            {
                "label": "Capital Capture Ratio",
                "value": _format_pct_display((float(capture_metrics.get("capital_capture_ratio") or 0.0) * 100.0), 1),
                "meta": "Deployed / triggered capacity",
            },
        ]
    )

    render_rank_sheet_header("Trigger Sensitivity")
    st.caption("Compare trigger strictness against edge quality without changing the live rule. This section balances raw edge, capture, and downside fragility across the current entry ladder.")
    if trigger_sensitivity_live:
        render_status_strip(
            [
                (
                    f"Live rule {trigger_sensitivity_live.get('method_label')} · trigger rate {_format_pct_display((float(trigger_sensitivity_live.get('trigger_rate') or 0.0) * 100.0), 1)}",
                    "watch",
                ),
                (
                    f"Expectancy {_format_pct_display(trigger_sensitivity_live.get('expectancy_pct'))}",
                    "positive" if float(trigger_sensitivity_live.get("expectancy_pct") or 0.0) > 0 else "watch",
                ),
                (
                    f"Capital capture {_format_pct_display((float(trigger_sensitivity_live.get('capital_capture_ratio') or 0.0) * 100.0), 1)}",
                    "neutral",
                ),
            ]
        )
    active_vs_benchmark_status = []
    if trigger_sensitivity_live:
        active_vs_benchmark_status.append(
            (
                f"Active Rule {trigger_sensitivity_live.get('method_label')} · {_format_pct_display(trigger_sensitivity_live.get('expectancy_pct'))}",
                "positive" if float(trigger_sensitivity_live.get("expectancy_pct") or 0.0) > 0 else "watch",
            )
        )
    if trigger_sensitivity_shadow:
        active_vs_benchmark_status.append(
            (
                f"Conservative Benchmark {trigger_sensitivity_shadow.get('method_label')} · {_format_pct_display(trigger_sensitivity_shadow.get('expectancy_pct'))}",
                "neutral",
            )
        )
    if active_vs_benchmark_status:
        render_status_strip(active_vs_benchmark_status)
    best_method_status = []
    if trigger_sensitivity_best_expectancy:
        best_method_status.append(
            (
                f"Best expectancy {trigger_sensitivity_best_expectancy.get('method_label')} · {_format_pct_display(trigger_sensitivity_best_expectancy.get('expectancy_pct'))}",
                "positive",
            )
        )
    if trigger_sensitivity_best_deployment:
        best_method_status.append(
            (
                f"Best deployment-adjusted edge {trigger_sensitivity_best_deployment.get('method_label')} · {_format_pct_display(trigger_sensitivity_best_deployment.get('deployment_adjusted_edge'))}",
                "watch",
            )
        )
    if trigger_sensitivity_best_risk:
        best_method_status.append(
            (
                f"Best risk-adjusted edge {trigger_sensitivity_best_risk.get('method_label')} · {_format_pct_display(trigger_sensitivity_best_risk.get('risk_adjusted_edge'))}",
                "neutral",
            )
        )
    if best_method_status:
        render_status_strip(best_method_status)
    if trigger_sensitivity_risk_formula:
        st.caption(f"Risk-adjusted edge uses {trigger_sensitivity_risk_formula}.")
    sensitivity_table_rows = [
        {
            "Method": row.get("method_label"),
            "Eligible": row.get("eligible_signals"),
            "Triggered": row.get("triggered_signals"),
            "Trigger Rate": _format_pct_display((float(row.get("trigger_rate") or 0.0) * 100.0), 1),
            "Expectancy": _format_pct_display(row.get("expectancy_pct")),
            "Edge Capture Score": _format_pct_display(row.get("edge_capture_score")),
            "Deploy.-Adjusted Edge": _format_pct_display(row.get("deployment_adjusted_edge")),
            "Risk-Adjusted Edge": _format_pct_display(row.get("risk_adjusted_edge")),
            "Avg Edge Score": (
                f"{float(row.get('average_edge_score') or 0.0):.1f}"
                if row.get("average_edge_score") is not None
                else "N/A"
            ),
            "Potential Deployed Capital": _format_pct_display((float(row.get("potential_deployed_capital") or 0.0) * 100.0), 1),
            "Capital Capture Ratio": _format_pct_display((float(row.get("capital_capture_ratio") or 0.0) * 100.0), 1),
            "Std Return": _format_pct_display(row.get("std_return_pct")),
            "Max Loss": _format_pct_display(row.get("max_loss_pct")),
            "Max Drawdown": _format_pct_display(row.get("max_drawdown_pct")),
            "Max Cons. Losses": row.get("max_consecutive_losses"),
            "Risk Flag": row.get("risk_flag"),
        }
        for row in trigger_sensitivity_rows
    ]
    if sensitivity_table_rows:
        st.dataframe(sensitivity_table_rows, use_container_width=True, hide_index=True)
    else:
        st.info("Trigger sensitivity analysis is not available yet.")

    portfolio_rows = [
        {
            "Ticker": row.get("ticker"),
            "Company": row.get("company"),
            "Strategy": row.get("strategy"),
            "Score": row.get("score"),
            "Edge Score": row.get("edge_score"),
            "Position Size": row.get("position_size"),
            "Risk Penalty": _format_ratio_display(row.get("risk_penalty")),
            "Raw Weight": row.get("raw_weight"),
            "Final Weight": row.get("final_weight"),
            "Hist. Expectancy": _format_pct_display(row.get("historical_expectancy_pct")),
            "Hist. Win Rate": _format_pct_display(row.get("historical_win_rate"), 1),
            "Risk Flag": row.get("risk_flag"),
            "Allocation Reason": row.get("allocation_reason"),
        }
        for row in portfolio_holdings
    ]
    if portfolio_rows:
        st.dataframe(portfolio_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No triggered signals currently qualify for portfolio allocation.")

    render_rank_sheet_header("Portfolio PnL")
    st.caption("Live portfolio performance using current Portfolio Engine v1 weights, with open holdings marked to current price and resolved holdings marked to exit price when available.")
    render_macro_strip(
        [
            {
                "label": "Deployed",
                "value": _format_pct_display((float(portfolio_pnl_summary.get("deployed_capital_weight") or 0.0) * 100.0), 1),
                "meta": "Capital assigned to holdings",
            },
            {
                "label": "Cash Reserve",
                "value": _format_pct_display((float(portfolio_pnl_summary.get("cash_reserve_weight") or 0.0) * 100.0), 1),
                "meta": "Unallocated capital",
            },
            {
                "label": "Realized PnL",
                "value": _format_pct_display(portfolio_pnl_summary.get("realized_pnl_pct")),
                "meta": "Resolved holdings only",
            },
            {
                "label": "Unrealized PnL",
                "value": _format_pct_display(portfolio_pnl_summary.get("unrealized_pnl_pct")),
                "meta": "Open holdings only",
            },
            {
                "label": "Total PnL",
                "value": _format_pct_display(portfolio_pnl_summary.get("total_portfolio_pnl_pct")),
                "meta": "Realized + unrealized",
            },
            {
                "label": "Weighted Hit Rate",
                "value": _format_pct_display(portfolio_pnl_summary.get("weighted_hit_rate"), 1),
                "meta": "Resolved holdings only",
            },
            {
                "label": "Open Holdings",
                "value": str(int(portfolio_pnl_summary.get("open_holdings") or 0)),
                "meta": "Still active",
            },
            {
                "label": "Resolved Holdings",
                "value": str(int(portfolio_pnl_summary.get("resolved_holdings") or 0)),
                "meta": "Closed positions",
            },
        ]
    )

    render_rank_sheet_header("Baseline Comparison")
    if baseline_rows:
        baseline_table = [
            {
                "Baseline": row.get("Baseline"),
                "Deployed": _format_pct_display((float(row.get("Deployed") or 0.0) * 100.0), 1),
                "Realized PnL": _format_pct_display(row.get("Realized PnL")),
                "Unrealized PnL": _format_pct_display(row.get("Unrealized PnL")),
                "Total PnL": _format_pct_display(row.get("Total PnL")),
                "Weighted Hit Rate": _format_pct_display(row.get("Weighted Hit Rate"), 1),
                "Open Holdings": row.get("Open Holdings"),
                "Resolved Holdings": row.get("Resolved Holdings"),
                "Vs Strategy_v1": _format_pct_display(row.get("Vs Strategy_v1")),
            }
            for row in baseline_rows
        ]
        st.dataframe(baseline_table, use_container_width=True, hide_index=True)
    else:
        st.info("Baseline comparison is not available yet.")

    render_rank_sheet_header("Holdings Performance")
    holdings_performance_rows = [
        {
            "Ticker": row.get("ticker"),
            "Company": row.get("company"),
            "Strategy": row.get("strategy"),
            "Status": row.get("status"),
            "Entry Price": _format_price(row.get("entry_price")),
            "Current Price": _format_price(row.get("current_price")),
            "Exit Price": _format_price(row.get("exit_price")),
            "Final Weight": row.get("final_weight"),
            "Holding Return": _format_pct_display(row.get("holding_return_pct")),
            "Weighted Contribution": _format_pct_display(row.get("weighted_return_contribution_pct")),
            "Immediate Baseline": _format_pct_display(row.get("immediate_entry_return_pct")),
        }
        for row in portfolio_pnl_holdings
    ]
    if holdings_performance_rows:
        st.dataframe(holdings_performance_rows, use_container_width=True, hide_index=True)
    else:
        st.info("No active portfolio holdings are available for PnL tracking.")

    render_rank_sheet_header("Strategy History")
    st.caption(
        f"This tracks the Strategy_v1 signal state over time even when the live portfolio is fully in cash, so the strategy doesn't look dormant between triggered allocations. "
        f"It reflects the active Pullback {float(STRATEGY_V1.pullback_pct or 0.0):.2f}% rule; Pullback 1.00% remains the conservative benchmark in Trigger Sensitivity."
    )
    render_macro_strip(
        [
            {
                "label": "Triggered",
                "value": str(int(strategy_history_summary.get("latest_triggered_count") or 0)),
                "meta": "Latest triggered names",
            },
            {
                "label": "Waiting",
                "value": str(int(strategy_history_summary.get("latest_waiting_count") or 0)),
                "meta": "Latest waiting names",
            },
            {
                "label": "Cohort Expectancy",
                "value": _format_pct_display(strategy_history_summary.get("latest_cohort_expectancy_pct")),
                "meta": "Latest strategy cohort expectancy",
            },
            {
                "label": "Avg Edge Score",
                "value": (
                    f"{float(strategy_history_summary.get('latest_average_edge_score') or 0.0):.1f}"
                    if strategy_history_summary.get("latest_average_edge_score") is not None
                    else "N/A"
                ),
                "meta": "Latest average edge score",
            },
            {
                "label": "Snapshots",
                "value": str(int(strategy_history_summary.get("snapshots_count") or 0)),
                "meta": "Stored strategy history points",
            },
        ]
    )

    strategy_cols = st.columns(2, gap="large")
    with strategy_cols[0]:
        with st.container(border=True):
            st.markdown("**Triggered vs Waiting**")
            if trigger_series:
                trigger_df = pd.DataFrame(trigger_series)
                trigger_df["timestamp"] = pd.to_datetime(trigger_df["timestamp"])
                st.line_chart(
                    trigger_df,
                    x="timestamp",
                    y=["triggered_signals_count", "waiting_signals_count"],
                    use_container_width=True,
                )
            else:
                st.info("Strategy history will appear once snapshots are recorded.")

    with strategy_cols[1]:
        with st.container(border=True):
            st.markdown("**Cohort Expectancy**")
            if quality_series:
                expectancy_df = pd.DataFrame(quality_series)
                expectancy_df["timestamp"] = pd.to_datetime(expectancy_df["timestamp"])
                st.line_chart(
                    expectancy_df,
                    x="timestamp",
                    y="cohort_expectancy_pct",
                    use_container_width=True,
                )
            else:
                st.info("Cohort expectancy history will appear after snapshots are recorded.")

    with st.container(border=True):
        st.markdown("**Average Edge Score & Risk**")
        if quality_series:
            quality_df = pd.DataFrame(quality_series)
            quality_df["timestamp"] = pd.to_datetime(quality_df["timestamp"])
            st.line_chart(
                quality_df,
                x="timestamp",
                y=["average_edge_score", "average_risk_penalty"],
                use_container_width=True,
            )
        else:
            st.info("Average edge and risk history will appear after snapshots are recorded.")

    render_rank_sheet_header("Portfolio History")
    st.caption("Append-only snapshots of the current portfolio state, built from the live Portfolio PnL payload to create a real track record over time.")
    render_macro_strip(
        [
            {
                "label": "Cumulative Return",
                "value": _format_pct_display(portfolio_history_summary.get("cumulative_return_pct")),
                "meta": "Latest Strategy_v1 portfolio PnL",
            },
            {
                "label": "Max Drawdown",
                "value": _format_pct_display(portfolio_history_summary.get("max_drawdown_pct")),
                "meta": "Peak-to-trough decline",
            },
            {
                "label": "Avg Deployed",
                "value": _format_pct_display((float(portfolio_history_summary.get("average_deployed_capital_weight") or 0.0) * 100.0), 1),
                "meta": "Average deployed capital",
            },
            {
                "label": "Latest Cash",
                "value": _format_pct_display((float(portfolio_history_summary.get("latest_cash_reserve_weight") or 0.0) * 100.0), 1),
                "meta": "Latest cash reserve",
            },
            {
                "label": "Snapshots",
                "value": str(int(portfolio_history_summary.get("snapshots_count") or 0)),
                "meta": "Stored history points",
            },
        ]
    )

    render_rank_sheet_header("Rolling Active vs Benchmark")
    st.caption("Track whether the live Pullback 0.50% rule is outperforming or underperforming the Pullback 1.00% benchmark over time, using paired portfolio history snapshots.")
    render_macro_strip(
        [
            {
                "label": "Latest Diff",
                "value": _format_pct_display(portfolio_history_comparison_summary.get("latest_active_minus_benchmark_total_pnl_pct")),
                "meta": "Active minus benchmark total PnL",
            },
            {
                "label": "Rolling 5",
                "value": _format_pct_display(portfolio_history_comparison_summary.get("rolling_5_snapshot_avg_diff_pct")),
                "meta": "5-snapshot avg PnL difference",
            },
            {
                "label": "Rolling 10",
                "value": _format_pct_display(portfolio_history_comparison_summary.get("rolling_10_snapshot_avg_diff_pct")),
                "meta": "10-snapshot avg PnL difference",
            },
            {
                "label": "Active PnL / Deploy",
                "value": _format_pct_display(portfolio_history_comparison_summary.get("active_pnl_per_deployed_capital")),
                "meta": "Total PnL per deployed capital",
            },
            {
                "label": "Benchmark PnL / Deploy",
                "value": _format_pct_display(portfolio_history_comparison_summary.get("benchmark_pnl_per_deployed_capital")),
                "meta": "Benchmark PnL per deployed capital",
            },
        ]
    )
    with st.container(border=True):
        st.markdown("**Active vs Benchmark Over Time**")
        if comparison_curve:
            comparison_df = pd.DataFrame(comparison_curve)
            comparison_df["timestamp"] = pd.to_datetime(comparison_df["timestamp"])
            st.line_chart(
                comparison_df,
                x="timestamp",
                y=[
                    "active_minus_benchmark_total_pnl_pct",
                    "rolling_5_snapshot_avg_diff_pct",
                    "rolling_10_snapshot_avg_diff_pct",
                ],
                use_container_width=True,
            )
            st.line_chart(
                comparison_df,
                x="timestamp",
                y=[
                    "active_deployed_capital_weight",
                    "benchmark_deployed_capital_weight",
                ],
                use_container_width=True,
            )
        else:
            st.info("Rolling active-vs-benchmark history will appear once paired snapshots are recorded.")

    history_cols = st.columns(2, gap="large")
    with history_cols[0]:
        with st.container(border=True):
            st.markdown("**Equity Curve**")
            if equity_curve:
                equity_df = pd.DataFrame(equity_curve)
                equity_df["timestamp"] = pd.to_datetime(equity_df["timestamp"])
                st.line_chart(
                    equity_df,
                    x="timestamp",
                    y=[
                        "strategy_weighted_pnl_pct",
                        "equal_weight_baseline_pnl_pct",
                        "immediate_entry_baseline_pnl_pct",
                    ],
                    use_container_width=True,
                )
            else:
                st.info("Portfolio history has not accumulated enough snapshots yet.")

    with history_cols[1]:
        with st.container(border=True):
            st.markdown("**Drawdown Curve**")
            if drawdown_curve:
                drawdown_df = pd.DataFrame(drawdown_curve)
                drawdown_df["timestamp"] = pd.to_datetime(drawdown_df["timestamp"])
                st.area_chart(drawdown_df, x="timestamp", y="drawdown_pct", use_container_width=True)
            else:
                st.info("Drawdown history will appear after snapshots are recorded.")

    with st.container(border=True):
        st.markdown("**Capital Deployment History**")
        if capital_curve:
            capital_df = pd.DataFrame(capital_curve)
            capital_df["timestamp"] = pd.to_datetime(capital_df["timestamp"])
            st.line_chart(
                capital_df,
                x="timestamp",
                y=["deployed_capital_weight", "cash_reserve_weight"],
                use_container_width=True,
            )
        else:
            st.info("Deployment history will appear after snapshots are recorded.")
