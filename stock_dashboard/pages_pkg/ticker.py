from __future__ import annotations

from html import escape
from typing import Callable

import streamlit as st

from config.universe import DEFAULT_STOCK_UNIVERSE
from stock_dashboard.pages_pkg.formatters import (
    _accounting_tone,
    _compress_thesis,
    _display_confidence,
    _display_recommendation_label,
    _format_price,
    _news_tone,
    _prioritized_risk_lines,
    _risk_flag_for_short,
    _save_watchlist,
    _source_badge,
    _source_meta,
    _tone_for_score,
    _trade_action_line,
    _trade_setup_bullets,
    _trend_tone,
    _volume_tone,
    render_section_intro,
    render_status_strip,
)
from stock_dashboard.ui import (
    age_badge_tone,
    build_macd_chart,
    build_price_chart,
    build_rsi_chart,
    build_volume_chart,
    format_age_badge,
    format_large_number,
    format_timestamp,
    recommendation_pill,
    render_overview_hero,
    render_rank_sheet_header,
    render_recommendation_summary,
    render_research_box,
    render_signal_card,
    render_trade_card,
)


def render_ticker_page(load_ticker_analysis: Callable[[str, str], object | None], data_mode: str) -> None:
    if "selected_ticker" not in st.session_state:
        st.session_state["selected_ticker"] = "AAPL"

    render_section_intro(
        "Ticker analysis",
        "Single-name research view.",
        "",
    )

    hdr_left, hdr_right = st.columns([3, 1])
    with hdr_left:
        quick_pick = st.selectbox(
            "Universe",
            options=[""] + DEFAULT_STOCK_UNIVERSE,
            index=0,
            help="Load a ticker from the current scan universe.",
        )
    with hdr_right:
        ticker_input = st.text_input(
            "Symbol Search",
            value=st.session_state.get("selected_ticker", "AAPL"),
            label_visibility="collapsed",
            placeholder="Symbol Search",
        ).upper().strip()

    next_ticker = (quick_pick or ticker_input or st.session_state["selected_ticker"]).upper().strip()
    if next_ticker and next_ticker != st.session_state["selected_ticker"]:
        st.session_state["selected_ticker"] = next_ticker
        st.rerun()

    active_ticker = st.session_state["selected_ticker"]

    analysis = load_ticker_analysis(active_ticker, data_mode)
    if analysis is None:
        st.error("This ticker could not be loaded right now. Check the symbol or try again when market data is available.")
        return

    source_tone = "negative" if analysis.data_source == "demo" else age_badge_tone(analysis.updated_at)
    intraday_tone = "positive" if analysis.intraday_source == "live" else "watch" if analysis.intraday_source == "cached_real" else "negative"
    render_status_strip(
        [
            (f"{analysis.company_name}", "neutral"),
            (f"Sector {analysis.sector}", "neutral"),
            (_source_meta(analysis.data_source).label, source_tone),
            (f"Intraday {analysis.intraday_source.replace('_', ' ').title()}", intraday_tone),
            (f"Updated {format_age_badge(analysis.updated_at)}", source_tone),
            (_display_recommendation_label(analysis.long_term_recommendation.label, analysis.data_source), analysis.long_term_recommendation.tone),
            (_display_recommendation_label(analysis.short_term_recommendation.label, analysis.data_source), analysis.short_term_recommendation.tone),
            (analysis.accounting_quality_view.label, _accounting_tone(analysis.accounting_quality_view.label, analysis.accounting_quality_view.shenanigan_risk_score)),
            (analysis.short_term_view.trade_state_label, analysis.short_term_view.trade_state_tone),
            (f"Finnhub LT news {analysis.long_term_view.news_score}/100", _news_tone(analysis.long_term_view.news_impact)),
            (f"Finnhub ST news {analysis.short_term_view.news_score}/100", _news_tone(analysis.short_term_view.news_impact)),
        ]
    )
    if analysis.status_message:
        st.info(analysis.status_message)
    elif _source_meta(analysis.data_source).banner:
        st.info(_source_meta(analysis.data_source).banner)
    if analysis.intraday_status_message:
        st.caption(f"Intraday status: {analysis.intraday_status_message}")
    if analysis.news_status_message and analysis.data_source != "demo":
        st.caption(f"Finnhub status: {analysis.news_status_message}")

    executive_cols = st.columns([0.78, 0.22])
    with executive_cols[0]:
        st.markdown(f"## {analysis.ticker} | {analysis.company_name}")
    with executive_cols[1]:
        if st.button("Add to Watchlist", use_container_width=True, key=f"watch-{active_ticker}"):
            _save_watchlist(active_ticker, "ticker_page")

    header_metrics = st.columns(5)
    header_metrics[0].metric(
        "Price",
        f"${analysis.snapshot['current_price']:,.2f}",
        f"{analysis.snapshot['daily_change_pct']:+.2f}%",
    )
    header_metrics[1].metric("Long Score", f"{analysis.long_term_view.score}/100")
    header_metrics[2].metric("Short Score", f"{analysis.short_term_view.score}/100")
    with header_metrics[3]:
        st.write("**Recommendation**")
        st.markdown(
            recommendation_pill(
                _display_recommendation_label(analysis.short_term_recommendation.label, analysis.data_source),
                analysis.short_term_recommendation.tone,
            ),
            unsafe_allow_html=True,
        )
    with header_metrics[4]:
        st.write("**Trade State**")
        st.markdown(
            recommendation_pill(analysis.short_term_view.trade_state_label, analysis.short_term_view.trade_state_tone),
            unsafe_allow_html=True,
        )

    research_cols = st.columns(3, gap="large")
    with research_cols[0]:
        st.subheader("Investment Thesis")
        with st.container(border=True):
            st.write(analysis.long_term_recommendation.thesis)
            if analysis.long_term_recommendation.reasons:
                st.caption(f"Key driver: {analysis.long_term_recommendation.reasons[0]}")

    with research_cols[1]:
        st.subheader("Technical Setup")
        with st.container(border=True):
            st.write(f"**1-2 Day:** {analysis.short_term_view.day_trade.trade_state_label} • {analysis.short_term_view.day_trade.score}/100")
            st.write(f"**5-15 Day:** {analysis.short_term_view.swing_trade.trade_state_label} • {analysis.short_term_view.swing_trade.score}/100")
            st.write(f"**Daily RSI (14):** {analysis.snapshot['rsi']:.2f}" if analysis.snapshot["rsi"] is not None else "**Daily RSI (14):** N/A")
            st.write(f"**Volume (20D):** {format_large_number(analysis.snapshot['avg_volume_20'])}")
            st.write(f"**Range High:** ${analysis.short_term_view.breakout_level:,.2f}")
            st.write(f"**Range Low:** ${analysis.short_term_view.breakdown_level:,.2f}")

    with research_cols[2]:
        st.subheader("Risk Panel")
        with st.container(border=True):
            risk_rating = _risk_flag_for_short(analysis.short_term_recommendation.tone)
            st.error(f"Risk Rating: {risk_rating}")
            risk_lines = analysis.long_term_recommendation.risks[:3] or [
                "Macro conditions",
                "Execution risk",
                "Trend deterioration",
            ]
            st.markdown("\n".join(f"- {item}" for item in risk_lines))
            if analysis.short_term_recommendation.accounting_warning:
                st.caption(analysis.short_term_recommendation.accounting_warning)

    st.divider()

    render_overview_hero(
        analysis.ticker,
        analysis.company_name,
        analysis.sector,
        analysis.snapshot,
        analysis.long_term_view,
        analysis.short_term_view,
        analysis.long_term_recommendation,
        analysis.short_term_recommendation,
        source_badge_html=_source_badge(analysis.data_source, analysis.updated_at),
    )

    latest = analysis.enriched_history.iloc[-1]
    chart_window = analysis.enriched_history.tail(126).copy()
    ma20_gap = ((float(latest["Close"]) / float(latest["MA20"])) - 1) * 100 if latest["MA20"] else 0.0
    ma50_gap = ((float(latest["Close"]) / float(latest["MA50"])) - 1) * 100 if latest["MA50"] else 0.0
    volume_average = analysis.enriched_history["Volume"].tail(20).mean()
    volume_ratio = float(latest["Volume"] / volume_average) if volume_average else 1.0
    rsi_value = analysis.snapshot["rsi"]
    momentum_tone = "positive" if rsi_value is not None and 45 <= rsi_value <= 65 else "watch"
    valuation_tone = _tone_for_score(analysis.long_term_view.score)
    risk_tone = "negative" if analysis.long_term_recommendation.tone == "negative" else "watch"

    render_recommendation_summary(
        analysis.long_term_view,
        analysis.short_term_view,
        analysis.long_term_recommendation,
        analysis.short_term_recommendation,
    )

    overview_tab, investor_tab, trader_tab = st.tabs(["Overview", "Investor", "Trader"])

    with overview_tab:
        render_section_intro(
            "Price and signals",
            "Chart, liquidity, and signal summary.",
            "",
        )
        overview_cols = st.columns([1.62, 0.98], gap="large")

        with overview_cols[0]:
            with st.container(border=True):
                st.markdown("**Price and Moving Averages**")
                st.altair_chart(build_price_chart(chart_window), use_container_width=True)
                st.caption(
                    f"Current price {analysis.snapshot['current_price']:.2f} • Daily move {analysis.snapshot['daily_change_pct']:+.2f}% • 20D volume {format_large_number(analysis.snapshot['avg_volume_20'])}"
                )

        with overview_cols[1]:
            render_section_intro(
                "Signal stack",
                "Current state of the name.",
                "",
            )
            signal_rows = st.columns(2, gap="small")
            with signal_rows[0]:
                render_signal_card("Long Score", f"{analysis.long_term_view.score}/100", analysis.long_term_recommendation.label, valuation_tone)
                render_signal_card("Trend", analysis.short_term_view.trend_direction, analysis.short_term_view.setup_type, _trend_tone(analysis.short_term_view.trend_direction))
                render_signal_card("Valuation", analysis.valuation_summary, "Long-horizon pricing context", valuation_tone)
            with signal_rows[1]:
                render_signal_card("1-2 Day Score", f"{analysis.short_term_view.day_trade.score}/100", analysis.short_term_view.day_trade.trade_state_label, analysis.short_term_view.day_trade.trade_state_tone)
                render_signal_card("5-15 Day Score", f"{analysis.short_term_view.swing_trade.score}/100", analysis.short_term_view.swing_trade.trade_state_label, analysis.short_term_view.swing_trade.trade_state_tone)
                render_signal_card("Risk", _risk_flag_for_short(analysis.short_term_recommendation.tone), "Execution and invalidation quality", risk_tone)
            render_signal_card(
                "Accounting Quality",
                f"{analysis.accounting_quality_view.accounting_quality_score}/100",
                analysis.accounting_quality_view.label,
                _accounting_tone(analysis.accounting_quality_view.label, analysis.accounting_quality_view.shenanigan_risk_score),
            )

        indicator_cols = st.columns(3, gap="large")
        with indicator_cols[0]:
            with st.container(border=True):
                st.markdown("**Volume**")
                st.altair_chart(build_volume_chart(chart_window), use_container_width=True)
                st.caption(f"20-day average volume: {format_large_number(analysis.snapshot['avg_volume_20'])}")

        with indicator_cols[1]:
            with st.container(border=True):
                st.markdown("**RSI**")
                st.altair_chart(build_rsi_chart(chart_window), use_container_width=True)
                st.caption("Balanced momentum generally sits near the middle of the RSI range.")

        with indicator_cols[2]:
            with st.container(border=True):
                st.markdown("**MACD**")
                st.altair_chart(build_macd_chart(chart_window), use_container_width=True)
                st.caption("Histogram expansion helps frame whether momentum is strengthening or fading.")

        signal_grid = st.columns(4, gap="small")
        with signal_grid[0]:
            render_signal_card("Price vs MA20", f"{ma20_gap:+.2f}%", "Distance from the 20-day average", "positive" if ma20_gap >= 0 else "negative")
        with signal_grid[1]:
            render_signal_card("Price vs MA50", f"{ma50_gap:+.2f}%", "Distance from the 50-day average", "positive" if ma50_gap >= 0 else "negative")
        with signal_grid[2]:
            render_signal_card("Volume Ratio", f"{volume_ratio:.2f}x", "Latest session versus 20-day average", "positive" if volume_ratio > 1.2 else "neutral")
        with signal_grid[3]:
            render_signal_card("Source Status", _source_meta(analysis.data_source).label, format_timestamp(analysis.updated_at), source_tone)

    with investor_tab:
        render_section_intro(
            "Long-term view",
            "Decision-first investor view.",
            "",
        )
        decision_cols = st.columns([0.95, 1.1, 0.85, 0.9], gap="small")
        decision_cols[0].metric("Long-Term Score", f"{analysis.long_term_view.score}/100")
        with decision_cols[1]:
            st.markdown("**Recommendation**")
            st.markdown(
                f"""
                <div class="recommendation-focus recommendation-{analysis.long_term_recommendation.tone}">
                    {recommendation_pill(
                        _display_recommendation_label(analysis.long_term_recommendation.label, analysis.data_source),
                        analysis.long_term_recommendation.tone,
                    )}
                </div>
                """,
                unsafe_allow_html=True,
            )
        decision_cols[2].metric("Confidence", _display_confidence(analysis.long_term_recommendation.confidence, analysis.data_source))
        decision_cols[3].metric("Accounting Quality", f"{analysis.accounting_quality_view.accounting_quality_score}/100")

        investor_cols = st.columns([1.05, 0.95], gap="large")
        with investor_cols[0]:
            with st.container(border=True):
                st.markdown("**Thesis**")
                st.write(_compress_thesis(analysis.long_term_recommendation.thesis))
            with st.container(border=True):
                st.markdown("**Key Risks**")
                st.markdown(_prioritized_risk_lines(analysis.long_term_recommendation.risks, 3))

        with investor_cols[1]:
            signal_grid = st.columns(2, gap="small")
            trend_label = "Above MA200" if latest["Close"] > latest["MA200"] else "Below MA200"
            revenue_growth = analysis.fundamentals.get("revenueGrowth")
            profit_margin = analysis.fundamentals.get("profitMargins")
            debt_to_equity = analysis.fundamentals.get("debtToEquity")
            growth_tone = (
                "positive"
                if isinstance(revenue_growth, (int, float)) and revenue_growth > 0.1
                else "negative"
                if isinstance(revenue_growth, (int, float)) and revenue_growth < 0
                else "neutral"
            )
            margin_tone = (
                "positive"
                if isinstance(profit_margin, (int, float)) and profit_margin > 0.1
                else "negative"
                if isinstance(profit_margin, (int, float)) and profit_margin < 0
                else "neutral"
            )
            balance_tone = (
                "positive"
                if isinstance(debt_to_equity, (int, float)) and debt_to_equity < 70
                else "watch"
                if isinstance(debt_to_equity, (int, float)) and debt_to_equity < 140
                else "negative"
                if isinstance(debt_to_equity, (int, float))
                else "neutral"
            )
            accounting_confidence_tone = (
                "neutral"
                if analysis.accounting_quality_view.accounting_assessment_confidence == "High"
                else "watch"
                if analysis.accounting_quality_view.accounting_assessment_confidence == "Moderate"
                else "negative"
            )
            with signal_grid[0]:
                render_signal_card("Trend", trend_label, "MA200 structure", "positive" if latest["Close"] > latest["MA200"] else "negative")
                render_signal_card("Growth", f"{revenue_growth * 100:.1f}%" if isinstance(revenue_growth, (int, float)) else "N/A", "Revenue growth", growth_tone)
                render_signal_card("Margin", f"{profit_margin * 100:.1f}%" if isinstance(profit_margin, (int, float)) else "N/A", "Profit margin", margin_tone)
                render_signal_card("Balance Sheet", f"{debt_to_equity:.1f}" if isinstance(debt_to_equity, (int, float)) else "N/A", "Debt / equity", balance_tone)
            with signal_grid[1]:
                render_signal_card(
                    "Shenanigan Risk",
                    f"{analysis.accounting_quality_view.shenanigan_risk_score}/100",
                    analysis.accounting_quality_view.label,
                    _accounting_tone(analysis.accounting_quality_view.label, analysis.accounting_quality_view.shenanigan_risk_score),
                )
                render_signal_card(
                    "Accounting Confidence",
                    analysis.accounting_quality_view.accounting_assessment_confidence,
                    f"Completeness {analysis.accounting_quality_view.accounting_data_completeness_score}/100",
                    accounting_confidence_tone,
                )
                render_signal_card("News Score", f"{analysis.long_term_view.news_score}/100", "Finnhub overlay", _news_tone(analysis.long_term_view.news_impact))

        st.markdown("")
        with st.expander("Recommendation rationale", expanded=False):
            render_research_box("Recommendation Rationale", analysis.long_term_recommendation.reasons[:4], tone="positive")
        with st.expander("Accounting overlay", expanded=False):
            accounting_content = [
                f"Accounting quality score: {analysis.accounting_quality_view.accounting_quality_score}/100",
                f"Shenanigan risk score: {analysis.accounting_quality_view.shenanigan_risk_score}/100",
                f"Data completeness score: {analysis.accounting_quality_view.accounting_data_completeness_score}/100",
                f"Assessment confidence: {analysis.accounting_quality_view.accounting_assessment_confidence}",
                analysis.accounting_quality_view.explanation,
            ]
            if analysis.long_term_recommendation.accounting_effect:
                accounting_content.append(analysis.long_term_recommendation.accounting_effect)
            if analysis.accounting_quality_view.limitations_note:
                accounting_content.append(analysis.accounting_quality_view.limitations_note)
            accounting_content.extend(analysis.accounting_quality_view.red_flags[:3])
            render_research_box(
                "Accounting Quality Overlay",
                accounting_content,
                tone=_accounting_tone(analysis.accounting_quality_view.label, analysis.accounting_quality_view.shenanigan_risk_score),
            )
        with st.expander("Long-term summary", expanded=False):
            render_research_box("Long-Term Summary", analysis.long_term_view.summary, tone="neutral")

    with trader_tab:
        render_section_intro(
            "Short-term view",
            "Setup status, levels, and execution.",
            "",
        )
        primary_trade_setup = analysis.short_term_view.day_trade
        if analysis.short_term_view.swing_trade.trade_state_label == "ENTER NOW" and primary_trade_setup.trade_state_label != "ENTER NOW":
            primary_trade_setup = analysis.short_term_view.swing_trade
        primary_trade_tone = primary_trade_setup.trade_state_tone
        trader_metrics = st.columns(5, gap="small")
        trader_metrics[0].metric("Short-Term Score", f"{analysis.short_term_view.score}/100")
        trader_metrics[1].metric("Recommendation", _display_recommendation_label(analysis.short_term_recommendation.label, analysis.data_source))
        with trader_metrics[2]:
            st.markdown("**Trade State**")
            st.markdown(
                f"""
                <div class="recommendation-focus recommendation-{primary_trade_tone}">
                    {recommendation_pill(analysis.short_term_view.trade_state_label, primary_trade_tone)}
                </div>
                """,
                unsafe_allow_html=True,
            )
        trader_metrics[3].metric("1-2 Day", analysis.short_term_view.day_trade.trade_state_label)
        trader_metrics[4].metric("5-15 Day", analysis.short_term_view.swing_trade.trade_state_label)

        trader_cols = st.columns([1.05, 0.95], gap="large")
        with trader_cols[0]:
            render_research_box(
                "1-2 Day Trade",
                _trade_setup_bullets(analysis.short_term_view.day_trade),
                tone=analysis.short_term_view.day_trade.trade_state_tone,
            )
            render_research_box(
                "5-15 Day Swing",
                _trade_setup_bullets(analysis.short_term_view.swing_trade),
                tone=analysis.short_term_view.swing_trade.trade_state_tone,
            )
            st.markdown(
                f"""
                <div class="action-line action-{primary_trade_tone}">
                    <strong>Action:</strong> {escape(_trade_action_line(primary_trade_setup))}
                </div>
                """,
                unsafe_allow_html=True,
            )
            render_research_box("Catalyst / Invalidation", analysis.short_term_recommendation.invalidation_note, tone="negative")
            render_research_box("Finnhub Catalyst Overlay", analysis.short_term_recommendation.news_effect, tone=_news_tone(analysis.short_term_view.news_impact))
            render_research_box("Recommendation Rationale", analysis.short_term_recommendation.reasons[:3], tone="watch")
            if analysis.short_term_recommendation.accounting_warning:
                render_research_box("Accounting Risk Warning", analysis.short_term_recommendation.accounting_warning, tone="negative")

        with trader_cols[1]:
            st.markdown("**Trade Setup**")
            trade_cols = st.columns(2, gap="small")
            with trade_cols[0]:
                st.markdown(
                    f"""
                    <div class="trade-state-panel trade-state-{primary_trade_tone}">
                        <div class="trade-state-label">Trade State</div>
                        <div class="trade-state-value">{escape(analysis.short_term_view.trade_state_label)}</div>
                        <div class="trade-state-meta">{escape(primary_trade_setup.holding_period_label)}</div>
                        <div class="trade-state-action"><strong>ACTION:</strong> {escape(_trade_action_line(primary_trade_setup))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                render_trade_card("1-2 Day Entry / Target", f"{_format_price(analysis.short_term_view.day_trade.entry_price)} / {_format_price(analysis.short_term_view.day_trade.target_price)}")
                render_trade_card("5-15 Day Entry / Target", f"{_format_price(analysis.short_term_view.swing_trade.entry_price)} / {_format_price(analysis.short_term_view.swing_trade.target_price)}")
            with trade_cols[1]:
                render_trade_card("Stops", f"{_format_price(analysis.short_term_view.day_trade.stop_loss_price)} / {_format_price(analysis.short_term_view.swing_trade.stop_loss_price)}")
                render_signal_card("1-2 Day", analysis.short_term_view.day_trade.trade_state_label, analysis.short_term_view.day_trade.holding_period_label, analysis.short_term_view.day_trade.trade_state_tone)
                render_signal_card("5-15 Day", analysis.short_term_view.swing_trade.trade_state_label, analysis.short_term_view.swing_trade.holding_period_label, analysis.short_term_view.swing_trade.trade_state_tone)

            st.markdown("**Momentum**")
            momentum_cols = st.columns(3, gap="small")
            with momentum_cols[0]:
                render_signal_card("Trend", analysis.short_term_view.trend_direction, analysis.short_term_view.setup_type, _trend_tone(analysis.short_term_view.trend_direction))
            with momentum_cols[1]:
                render_signal_card("RSI", f"{rsi_value:.2f}" if rsi_value is not None else "N/A", "Momentum balance", momentum_tone)
            with momentum_cols[2]:
                macd_relation = "Bullish" if latest["MACD"] > latest["MACD_SIGNAL"] else "Bearish"
                render_signal_card("MACD", macd_relation, "MACD versus signal", "positive" if macd_relation == "Bullish" else "negative")

            st.markdown("**Risk**")
            risk_cols = st.columns(3, gap="small")
            with risk_cols[0]:
                render_signal_card("Volume", f"{volume_ratio:.2f}x", "Confirmation versus 20-day average", _volume_tone(volume_ratio))
            with risk_cols[1]:
                render_signal_card("Execution Risk", _risk_flag_for_short(analysis.short_term_recommendation.tone), "Setup fragility", risk_tone)
            with risk_cols[2]:
                combined_risk_tone = _news_tone(analysis.short_term_view.news_impact)
                if combined_risk_tone == "neutral":
                    combined_risk_tone = _accounting_tone(
                        analysis.accounting_quality_view.label,
                        analysis.accounting_quality_view.shenanigan_risk_score,
                    )
                render_signal_card(
                    "Accounting / News",
                    analysis.accounting_quality_view.label,
                    f"Risk {analysis.accounting_quality_view.shenanigan_risk_score}/100 • News {analysis.short_term_view.news_score}/100",
                    combined_risk_tone,
                )

    render_section_intro(
        "Recent Finnhub headlines",
        "Recent company news used by the news overlay.",
        "",
    )
    if analysis.recent_news:
        for item in analysis.recent_news[:6]:
            with st.container(border=True):
                headline = item.get("headline") or "Untitled headline"
                url = item.get("url") or ""
                if url:
                    st.markdown(f"**[{headline}]({url})**")
                else:
                    st.markdown(f"**{headline}**")
                published_label = format_timestamp(item.get("published_at")) if item.get("published_at") else "Time unavailable"
                st.caption(f"{item.get('source', 'Finnhub')} • {published_label}")
                summary = item.get("summary") or "No summary was provided."
                st.write(summary)
    else:
        st.info("Recent Finnhub headlines are unavailable for this ticker, so the news overlay stayed neutral.")
