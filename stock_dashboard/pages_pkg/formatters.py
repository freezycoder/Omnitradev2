"""Shared formatters, tone helpers, and scanner-header renderers used by every page.

Mechanical extraction from the original `stock_dashboard/pages.py` — content is
identical to the original lines 38-528. Imports cover every name referenced by
the helpers below.
"""
from __future__ import annotations

from html import escape
from textwrap import dedent

import streamlit as st

from config.settings import SOURCE_CONFIG
from storage.repositories.watchlist_repository import add_to_watchlist
from stock_dashboard.ui import (
    age_badge_tone,
    format_age_badge,
    format_large_number,
    format_timestamp,
    recommendation_pill,
    render_macro_strip,
    render_rank_sheet_header,
    render_section_intro,
    render_status_strip,
)


def _source_meta(source: str):
    return SOURCE_CONFIG.get(source, SOURCE_CONFIG["demo"])


def _display_recommendation_label(label: str, source: str) -> str:
    if source == "demo":
        return f"Demo: {label}"
    return label


def _display_confidence(confidence: str, source: str) -> str:
    if source == "cached_real":
        return f"{confidence} conviction • stale risk"
    if source == "demo":
        return "Testing only"
    return f"{confidence} conviction"


def _source_badge(source: str, updated_at: str | None) -> str:
    tone = "negative" if source == "demo" else age_badge_tone(updated_at)
    meta = _source_meta(source)
    return recommendation_pill(f"{meta.label} • {format_age_badge(updated_at)}", tone)


def _tone_for_score(score: int) -> str:
    if score >= 75:
        return "positive"
    if score >= 55:
        return "watch"
    if score >= 40:
        return "neutral"
    return "negative"


def _trend_tone(direction: str) -> str:
    if direction == "Bullish":
        return "positive"
    if direction == "Bearish":
        return "negative"
    return "neutral"


def _risk_flag_for_long(tone: str) -> str:
    if tone == "positive":
        return "Controlled"
    if tone == "watch":
        return "Balanced"
    if tone == "neutral":
        return "Mixed"
    return "Elevated"


def _risk_flag_for_short(tone: str) -> str:
    if tone == "positive":
        return "Defined"
    if tone == "watch":
        return "Watch"
    if tone == "neutral":
        return "Mixed"
    return "Fragile"


def _news_tone(impact: int) -> str:
    if impact >= 2:
        return "positive"
    if impact <= -2:
        return "negative"
    return "neutral"


def _accounting_tone(label: str, risk_score: int | None = None) -> str:
    if label == "Clean Reporting":
        return "positive"
    if label == "Generally Acceptable":
        return "neutral"
    if label == "Limited Visibility":
        return "watch"
    if label == "Inconclusive":
        return "watch"
    if label == "Elevated Shenanigan Risk":
        return "negative" if (risk_score or 0) >= 60 else "watch"
    return "negative"


def _html_list(items: list[str]) -> str:
    safe_items = [escape(str(item)) for item in (items or []) if item]
    if not safe_items:
        safe_items = ["No items available."]
    return "<ul>" + "".join(f"<li>{item}</li>" for item in safe_items) + "</ul>"


def _inline_list(items: list[str], limit: int = 2) -> str:
    visible = [escape(str(item)) for item in (items or [])[:limit] if item]
    return " • ".join(visible) if visible else "None noted"


def _truncate_copy(text: str | None, limit: int = 180) -> str:
    if not text:
        return "Not available."
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _compress_thesis(text: str | None) -> str:
    if not text:
        return "No thesis available."
    cleaned = " ".join(str(text).split())
    cleaned = cleaned.replace("Long-term recommendation engine", "").replace("Recommendation engine", "").strip(" .")
    primary = cleaned.split(". ")[0].strip()
    if primary:
        cleaned = primary
    return _truncate_copy(cleaned, 118)


def _prioritized_risk_lines(items: list[str] | None, limit: int = 3) -> str:
    visible = [str(item).strip() for item in (items or []) if item][:limit]
    if not visible:
        return "**Top risk:** No major risks listed."
    first = f"**Top risk:** {visible[0]}"
    remaining = [f"- {item}" for item in visible[1:]]
    return "\n".join([first, *remaining]) if remaining else first


def _trade_setup_bullets(setup, limit: int = 3) -> list[str]:
    points = [
        f"State: {setup.trade_state_label}",
        f"Entry: {_format_price(setup.entry_price)} • Target: {_format_price(setup.target_price)} • Stop: {_format_price(setup.stop_loss_price)}",
        _truncate_copy(setup.explanation, 92),
    ]
    return [point for point in points[:limit] if point]


def _trade_action_line(setup) -> str:
    state = setup.trade_state_label.upper()
    entry = _format_price(setup.entry_price)
    if state == "ENTER NOW":
        return f"Act now around {entry} with risk defined at the stop."
    if state == "WAIT FOR PULLBACK":
        return f"Wait for pullback toward {entry} before entry."
    return "No trade now. Wait for a cleaner setup before acting."


def _rsi_tone(value: float | None) -> str:
    if value is None:
        return "neutral"
    if 50 <= value <= 60:
        return "neutral"
    if 45 <= value < 50 or 60 < value <= 70:
        return "watch"
    if value > 70 or value < 35:
        return "negative"
    return "neutral"


def _volume_tone(value: float) -> str:
    if value >= 1.25:
        return "positive"
    if value >= 0.9:
        return "watch"
    return "negative"


def _bullet_lines(items: list[str] | None, limit: int = 3) -> str:
    visible = [f"- {item}" for item in (items or [])[:limit] if item]
    if not visible:
        return "- No major points available."
    return "\n".join(visible)


def _format_price(value) -> str:
    if value is None:
        return "N/A"
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _format_pct_display(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):+.{digits}f}%"


def _format_ratio_display(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):+.{digits}f}"


def _sample_tone(is_low_sample: bool, resolved_signals: int) -> str:
    if resolved_signals == 0:
        return "neutral"
    return "watch" if is_low_sample else "neutral"


def _edge_metric_lines(row: dict) -> str:
    return "\n".join(
        [
            f"- Signals: {int(row.get('total_signals') or 0)}",
            f"- Resolved: {int(row.get('resolved_signals') or 0)}",
            f"- Wins / Losses / Flats: {int(row.get('wins') or 0)} / {int(row.get('losses') or 0)} / {int(row.get('flats') or 0)}",
            f"- Win rate: {_format_pct_display(row.get('win_rate'), 1) if row.get('win_rate') is not None else 'N/A'}",
            f"- Avg return: {_format_pct_display(row.get('avg_return_pct'))}",
            f"- Avg win / Avg loss: {_format_pct_display(row.get('avg_win_pct'))} / {_format_pct_display(row.get('avg_loss_pct'))}",
            f"- Expectancy: {_format_pct_display(row.get('expectancy_pct'))}",
            f"- Risk-adjusted view: {_format_ratio_display(row.get('risk_adjusted_view'))}",
            f"- Std return: {_format_pct_display(row.get('std_return_pct'))}",
            f"- Max loss / Max drawdown: {_format_pct_display(row.get('max_loss_pct'))} / {_format_pct_display(row.get('max_drawdown_pct'))}",
            f"- Loss streak / Risk flag: {int(row.get('max_consecutive_losses') or 0)} / {row.get('risk_flag', 'No data')}",
        ]
    )


def _entry_trigger_metric_lines(row: dict) -> str:
    return "\n".join(
        [
            f"- Resolved: {int(row.get('resolved_signals') or 0)} of {int(row.get('cohort_size') or 0)}",
            f"- Wins / Losses / Flats: {int(row.get('wins') or 0)} / {int(row.get('losses') or 0)} / {int(row.get('flats') or 0)}",
            f"- Win rate: {_format_pct_display(row.get('win_rate'), 1) if row.get('win_rate') is not None else 'N/A'}",
            f"- Avg return: {_format_pct_display(row.get('avg_return_pct'))}",
            f"- Avg win / Avg loss: {_format_pct_display(row.get('avg_win_pct'))} / {_format_pct_display(row.get('avg_loss_pct'))}",
            f"- Expectancy: {_format_pct_display(row.get('expectancy_pct'))}",
            f"- Realized PnL: {_format_pct_display(row.get('realized_pnl_pct'))}",
            f"- PnL vs baseline: {_format_pct_display(row.get('pnl_vs_baseline_pct'))}",
            f"- Risk-adjusted view: {_format_ratio_display(row.get('risk_adjusted_view'))}",
            f"- Std return: {_format_pct_display(row.get('std_return_pct'))}",
            f"- Max loss / Max drawdown: {_format_pct_display(row.get('max_loss_pct'))} / {_format_pct_display(row.get('max_drawdown_pct'))}",
            f"- Loss streak / Risk flag: {int(row.get('max_consecutive_losses') or 0)} / {row.get('risk_flag', 'No data')}",
            f"- Risk penalty: {_format_ratio_display(row.get('risk_penalty'))}",
            f"- Vs baseline: {_format_pct_display(row.get('improvement_vs_baseline_pct'))}",
        ]
    )


def _edge_discovery_table(rows: list[dict]) -> list[dict]:
    table_rows: list[dict] = []
    for row in rows:
        segment = row.get("segment", {})
        table_rows.append(
            {
                "Score Bucket": segment.get("score_bucket", "N/A"),
                "Trade State": segment.get("trade_state", "N/A"),
                "Recommendation": segment.get("recommendation_label", "N/A"),
                "Trend": segment.get("trend_direction", "N/A"),
                "Source": segment.get("source_quality", "N/A"),
                "Resolved": int(row.get("resolved_signals") or 0),
                "Wins": int(row.get("wins") or 0),
                "Losses": int(row.get("losses") or 0),
                "Win Rate": f"{row.get('win_rate'):.1f}%" if row.get("win_rate") is not None else "N/A",
                "Avg Return": _format_pct_display(row.get("avg_return_pct")),
                "Expectancy": _format_pct_display(row.get("expectancy_pct")),
            }
        )
    return table_rows


def _trade_horizon_html(setup: dict) -> str:
    return dedent(
        f"""
        <div class="detail-box">
            <div class="detail-box-title">{escape(setup['label'])}</div>
            <div class="detail-box-body">
                <strong>{setup.get('score', 'N/A')}/100</strong> • {escape(str(setup.get('trade_state', 'N/A')))} • {escape(str(setup.get('holding_period', 'N/A')))}<br/>
                Entry {_format_price(setup.get('entry_price'))} • Target {_format_price(setup.get('target_price'))} • Stop {_format_price(setup.get('stop_loss_price'))}<br/>
                {escape(str(setup.get('setup_type', 'N/A')))}<br/>
                {escape(_truncate_copy(setup.get('explanation'), 120))}
            </div>
        </div>
        """
    ).strip()


def _open_ticker(ticker: str) -> None:
    st.session_state["selected_ticker"] = ticker.upper().strip()
    st.session_state["nav_page"] = "Ticker Analysis"
    st.rerun()


def _save_watchlist(ticker: str, source: str) -> None:
    add_to_watchlist(ticker, source)
    st.success(f"{ticker.upper()} was added to the watchlist.")


def _scanner_header(scan_results: dict, title: str, copy: str) -> None:
    source = scan_results.get("source", "demo")
    source_meta = _source_meta(source)
    market_stats = scan_results.get("market_stats", {})
    long_rows = scan_results.get("long_term", [])
    short_rows = scan_results.get("short_term", [])
    top_long = long_rows[0] if long_rows else None
    top_short = short_rows[0] if short_rows else None

    st.markdown(
        f"""
        <div style="display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin:0.15rem 0 1rem;">
            <div>
                <div style="color:var(--text); font-size:1.42rem; font-weight:600; letter-spacing:-0.03em;">{escape(title)}</div>
                <div style="color:var(--text-dim); font-size:0.84rem; margin-top:0.3rem;">{escape(copy)}</div>
            </div>
            <div style="text-align:right; min-width:220px;">
                <div style="color:var(--text-muted); font-size:0.72rem; text-transform:uppercase; letter-spacing:0.06em;">Last updated</div>
                <div style="color:var(--text); font-size:0.88rem; margin-top:0.2rem;">{escape(format_timestamp(scan_results.get("updated_at")))}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    render_status_strip(
        [
            (f"MODE: {source_meta.label}", "negative" if source == "demo" else age_badge_tone(scan_results.get("updated_at"))),
            (f"UPDATED: {format_age_badge(scan_results.get('updated_at'))}", age_badge_tone(scan_results.get("updated_at"))),
            (f"UNIVERSE: {scan_results.get('universe_name', 'N/A')}", "neutral"),
            (f"ACTIONABLE: {market_stats.get('recommendation_count', 0)}", "watch" if market_stats.get("recommendation_count", 0) else "neutral"),
        ]
    )
    render_macro_strip(
        [
            {
                "label": "Stocks Scanned",
                "value": str(market_stats.get("scanned_count", 0)),
                "meta": f"Universe size {market_stats.get('universe_size', 0)}",
            },
            {
                "label": "Top Long Conviction",
                "value": top_long["ticker"] if top_long else "N/A",
                "meta": f"{top_long['long_term_score']}/100 • {top_long['recommendation_label']}" if top_long else "No qualifying idea",
            },
            {
                "label": "Top Short Conviction",
                "value": top_short["ticker"] if top_short else "N/A",
                "meta": f"{top_short['short_term_score']}/100 • {top_short['recommendation_label']}" if top_short else "No qualifying setup",
            },
            {
                "label": "Actionable Names",
                "value": str(market_stats.get("recommendation_count", len(long_rows) + len(short_rows))),
                "meta": f"{len(long_rows)} long • {len(short_rows)} short",
            },
        ]
    )
    if scan_results.get("message"):
        st.info(scan_results["message"])
    elif source_meta.banner:
        st.info(source_meta.banner)


def _render_long_term_pick(row: dict, rank: int, key_prefix: str) -> None:
    source = row.get("data_source", "demo")
    updated_at = row.get("updated_at")
    score_tone = _tone_for_score(row["long_term_score"])
    risk_flag = _risk_flag_for_long(row["tone"])
    accounting_tone = _accounting_tone(row.get("accounting_label", "Inconclusive"), row.get("shenanigan_risk_score"))

    st.markdown(
        f"""
        <div class="rank-sheet-row">
            <div class="feature-header">
                <div class="feature-identity">
                    <div class="rank-number">{rank:02d}</div>
                    <div>
                        <h3 class="rank-ticker">{escape(row["ticker"])} <span style="color:var(--text-muted);font-weight:400;">{escape(row["company_name"])}</span></h3>
                        <div class="rank-subtitle">{escape(row.get("sector") or "N/A")} • Long-term idea</div>
                    </div>
                </div>
                <div class="rank-meta-strip">
                    {recommendation_pill(_display_recommendation_label(row["recommendation_label"], source), row["tone"])}
                    {_source_badge(source, updated_at)}
                    {recommendation_pill(row.get("accounting_label", "Inconclusive"), accounting_tone)}
                    {recommendation_pill(f"Risk {risk_flag}", "negative" if risk_flag == "Elevated" else "watch")}
                </div>
            </div>
            <div class="feature-grid">
                <div class="feature-panel feature-panel-score {score_tone}">
                    <div class="feature-panel-title">Conviction score</div>
                    <div class="feature-score-value">{row["long_term_score"]}/100</div>
                    <div class="feature-score-meta">{escape(row["recommendation_label"])} • {escape(row["confidence"])}</div>
                </div>
                <div class="feature-panel">
                    <div class="feature-panel-title">Research snapshot</div>
                    <div class="detail-box-body">
                        Market cap {escape(format_large_number(row.get("market_cap")))} • News {row.get("news_score", 50)}/100<br/>
                        Valuation {escape(row["valuation_summary"])}<br/>
                        Accounting {row.get("accounting_quality_score", 70)}/100 • Completeness {row.get("accounting_data_completeness_score", 0)}/100
                    </div>
                </div>
            </div>
            <div class="feature-summary">{escape(_truncate_copy(row["summary_reasoning"], 180))}</div>
            <div class="rank-details">
                <div class="detail-box">
                    <div class="detail-box-title">Thesis</div>
                    <div class="detail-box-body">{escape(_truncate_copy(row["thesis"], 140))}</div>
                </div>
                <div class="detail-box">
                    <div class="detail-box-title">Strengths / Risks</div>
                    <div class="detail-box-body">
                        Strengths: {escape(_inline_list(row["key_strengths"]))}<br/>
                        Risks: {escape(_inline_list(row["key_risks"]))}
                    </div>
                </div>
                <div class="detail-box">
                    <div class="detail-box-title">Accounting Quality</div>
                    <div class="detail-box-body">
                        <strong>{escape(row.get("accounting_label", "Inconclusive"))}</strong><br/>
                        Shenanigan risk {row.get("shenanigan_risk_score", 30)}/100 • Confidence {escape(row.get("accounting_assessment_confidence", "Low"))}<br/>
                        {escape(_truncate_copy(row.get("accounting_explanation", "Accounting coverage is limited in the current dataset."), 120))}
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_cols = st.columns([0.28, 0.24, 0.48], gap="small")
    if action_cols[0].button("Open Analysis", key=f"{key_prefix}-open-{row['ticker']}", use_container_width=True):
        _open_ticker(row["ticker"])
    if action_cols[1].button("Save Idea", key=f"{key_prefix}-save-{row['ticker']}", use_container_width=True):
        _save_watchlist(row["ticker"], "long_term_scanner")


def _render_short_term_pick(row: dict, rank: int, key_prefix: str) -> None:
    source = row.get("data_source", "demo")
    updated_at = row.get("updated_at")
    score_tone = _tone_for_score(row["short_term_score"])
    trend_tone = _trend_tone(row["trend_direction"])
    risk_flag = _risk_flag_for_short(row["tone"])
    accounting_warning = row.get("accounting_warning")
    day_trade = row["day_trade"]
    swing_trade = row["swing_trade"]

    st.markdown(
        f"""
        <div class="rank-sheet-row">
            <div class="feature-header">
                <div class="feature-identity">
                    <div class="rank-number">{rank:02d}</div>
                    <div>
                        <h3 class="rank-ticker">{escape(row["ticker"])} <span style="color:var(--text-muted);font-weight:400;">{escape(row["company_name"])}</span></h3>
                        <div class="rank-subtitle">{escape(row.get("sector") or "N/A")} • Short-term setup</div>
                    </div>
                </div>
                <div class="rank-meta-strip">
                    {recommendation_pill(_display_recommendation_label(row["recommendation_label"], source), row["tone"])}
                    {recommendation_pill(row["trade_state"], row.get("trade_state_tone", "neutral"))}
                    {_source_badge(source, updated_at)}
                    {recommendation_pill(f"Trend {row['trend_direction']}", trend_tone)}
                </div>
            </div>
            <div class="feature-grid">
                <div class="feature-panel feature-panel-score {score_tone}">
                    <div class="feature-panel-title">Setup score</div>
                    <div class="feature-score-value">{row["short_term_score"]}/100</div>
                    <div class="feature-score-meta">{escape(row["expected_holding_period"])} • {escape(row["confidence"])}</div>
                </div>
                    <div class="feature-panel">
                    <div class="feature-panel-title">Execution plan</div>
                    <div class="detail-box-body">
                        Entry {_format_price(row.get("entry_price"))} • Target {_format_price(row.get("target_price"))} • Stop {_format_price(row.get("stop_loss_price"))}<br/>
                        Horizon {escape(row["expected_holding_period"])} • {escape("Actionable now" if row.get("is_actionable_now") else "Watchlist")}<br/>
                        {escape(row["setup_type"])}
                    </div>
                </div>
            </div>
            <div class="feature-summary">{escape(_truncate_copy(row["trade_state_explanation"], 180))}</div>
            <div class="rank-details">
                {_trade_horizon_html(day_trade)}
                {_trade_horizon_html(swing_trade)}
                <div class="detail-box">
                    <div class="detail-box-title">Reasons / Risk</div>
                    <div class="detail-box-body">
                        Reasons: {escape(_inline_list(row["reasons"], 3))}<br/>
                        Accounting: {escape(accounting_warning or "No overriding accounting warning")}
                    </div>
                </div>
                <div class="detail-box">
                    <div class="detail-box-title">Invalidation</div>
                    <div class="detail-box-body">{escape(_truncate_copy(row["invalidation_note"], 120))}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_cols = st.columns([0.28, 0.24, 0.48], gap="small")
    if action_cols[0].button("Open Analysis", key=f"{key_prefix}-open-{row['ticker']}", use_container_width=True):
        _open_ticker(row["ticker"])
    if action_cols[1].button("Save Idea", key=f"{key_prefix}-save-{row['ticker']}", use_container_width=True):
        _save_watchlist(row["ticker"], "short_term_scanner")
