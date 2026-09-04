# OmniTrade Strategy Blueprint

Updated: July 28, 2026

This document describes how the current OmniTrade scanner and portfolio engine selects stocks, ranks signals, and allocates portfolio weight. It is a research and decision-support model, not financial advice.

## 1. High-Level Objective

OmniTrade separates stock selection into two layers:

1. Scanner layer: finds stocks that look attractive either as long-term investments or short-term trading candidates.
2. Execution and portfolio layer: takes short-term signals and decides whether they are actionable enough to become portfolio positions.

The scanner can show a stock because it has a good score. The portfolio engine is stricter: a stock must be triggered, have positive expectancy after modeled costs, avoid major risk penalties, and have enough sizing edge.

## 2. Universe Selection

The model starts from a fixed, liquid universe in `config/universe.py`.

Default universe characteristics:

- Mostly large, liquid US and international equities.
- Minimum price filter.
- Minimum average volume filter.
- Minimum market-cap filter.
- Minimum historical data length filter.

The intent is to avoid tiny, illiquid, noisy names where slippage, stale data, and false signals are harder to control.

## 3. Long-Term Selection Logic

Long-term scoring starts from a neutral base around 45 and adjusts using composite factors.

Current factor groups:

- Trend factor: price above MA200, MA50 above MA200, six-month return.
- Quality factor: profit margins and return on equity.
- Growth factor: revenue growth and earnings growth.
- Valuation factor: trailing PE when available.
- Balance-sheet factor: debt/equity and current ratio.

Default scanner inclusion:

- `min_long_term_scan_score = 65`
- Recommendation label must be `Strong Buy` or `Buy`.

Interpretation:

- A strong long-term pick should have trend support plus business-quality or growth support.
- A stock can still score well with incomplete fundamentals, but missing data makes the case more dependent on trend.

## 4. Short-Term Regimes

Short-term scoring is now split into two explicit regimes.

### Momentum

Momentum is trend-following. It rewards stocks that are already moving constructively and are not yet overextended.

Typical momentum profile:

- Price above MA20 and MA50.
- Price above or near VWAP.
- 15-minute and 1-hour RSI supportive but not too stretched.
- Volume rising enough to confirm demand.
- For swing trades, MACD and moving-average structure are supportive.

### Mean Reversion

Mean reversion is a pullback setup inside a larger constructive trend. It rewards stocks that are temporarily oversold but not structurally broken.

Typical mean-reversion profile:

- Daily trend remains constructive, especially price above MA200.
- MA50 above MA200 helps confirm the larger trend.
- 15-minute or 1-hour RSI is oversold or reset.
- Price is pulling into VWAP, MA20, or MA50.
- Volume is active but not panic-like.

The app now carries regime metadata such as:

- `regime_label`
- `regime_scores`
- `ranking_bucket`
- `rank_within_regime`

This makes it possible to compare momentum stocks against other momentum stocks, and mean-reversion stocks against other mean-reversion stocks.

## 5. Short-Term Horizons

The app scores two short-term horizons:

1. 1-2 day trade:
   - Uses 15-minute RSI, 1-hour RSI, VWAP location, and volume spike.
   - Can produce either momentum or mean-reversion setups.

2. 5-15 day swing:
   - Uses daily RSI, MA20, MA50, MA200, volume ratio, and MACD.
   - Can produce either momentum continuation or mean-reversion pullback setups.

The primary short-term score is the stronger of the two horizons.

Default scanner inclusion:

- `min_short_term_scan_score = 55`
- Recommendation label must be `Strong Setup` or `Watchlist`.

## 6. Alternative-Signal Shadow Overlay

OmniTrade now collects three independent context sources:

- SEC EDGAR: recent 8-K/6-K events, offering filings, and Form 4 open-market insider transactions.
- Classified Finnhub news: near-duplicate removal, event type, ticker relevance, and source class.
- FRED macro regime: the 10Y–2Y curve, high-yield spread, financial conditions, and effective fed funds rate.

The combined overlay is capped at `±10` modeled points. It is research-only:

- `modeled_impact` records what the overlay would have contributed.
- `applied_impact` is always `0`.
- Missing sources reduce coverage and are never interpreted as neutral evidence.
- Signal snapshots retain the shadow score, component evidence, and coverage for outcome analysis.

Calibration keeps activation locked until the shadow cohort has at least 50
resolved directional signals across 12 dates, positive directional expectancy
after costs, two positive chronological validation folds, and average coverage
of at least 70%. Passing those gates only makes the overlay eligible for manual
review; it never activates itself.

## 7. Relative-Strength Shadow Layer

Every live ticker analysis compares the stock with:

- `SPY` as the market benchmark.
- A sector ETF such as `XLK`, `XLF`, `XLE`, or `XLV` when the reported sector
  has a configured mapping.
- Other successfully scanned stocks for a universe percentile.
- Other stocks in the same sector when at least three peers are available.

The time windows and weights are:

- 1 month: 15%.
- 3 months: 25%.
- 6 months: 35%.
- 12 months: 25%.

The raw leadership measure combines weighted market excess return (55%),
weighted sector excess return (30%), and sector performance versus the market
(15%). Missing comparisons reduce coverage instead of being scored as neutral.

The resulting 0–100 score is labeled leader, outperforming, neutral,
underperforming, or lagging. It remains research-only:

- `applied_impact` is always `0`.
- Live long- and short-term scores are unchanged.
- Signal snapshots retain the full time-window evidence and percentile ranks.
- Shared benchmark histories are fetched once and cached for six hours.

Calibration uses the same minimum evidence gates as the alternative-signal
overlay: 50 resolved directional signals, 12 signal dates, two positive
chronological validation folds, positive net directional expectancy, and
average coverage of at least 70%. Passing the gate only makes the factor
eligible for manual review.

## 8. Earnings-Intelligence Shadow Layer

Every live ticker analysis assembles a point-in-time earnings view from:

- The last four Finnhub EPS actual-versus-consensus results.
- Yahoo Finance's current-quarter EPS consensus range, expected year-over-year
  growth, analyst count, and 30-day upward/downward revision counts.
- The next scheduled earnings date.
- The most recent SEC 8-K item 2.02 earnings filing.
- Classified guidance headlines already collected by the news pipeline.
- The stock's first three trading sessions from the latest earnings filing.

The 0–100 score starts at 50 and receives capped contributions from the latest
EPS surprise, average surprise, beat consistency, revision breadth,
current-quarter consensus growth, and the observed post-filing price move.
Missing components reduce coverage instead of being treated as neutral.

Earnings proximity is deliberately separate from direction:

- 0–3 days: high event risk.
- 4–7 days: elevated event risk.
- 8–21 days: watch.
- More than 21 days: normal.

An imminent report never adds bullish or bearish points. It warns that gaps
can invalidate normal technical entry and stop levels.

The factor remains research-only:

- `applied_impact` is always `0`.
- Live long- and short-term scores are unchanged.
- Full evidence is stored with signal snapshots.
- Calibration requires at least 50 resolved directional signals, 12 signal
  dates, two positive chronological folds, positive expectancy after modeled
  costs, and average coverage of at least 70%.
- Passing every gate permits manual review only; activation is never automatic.

## 9. Strategy_v1 Execution Logic

Strategy_v1 is the execution layer for short-term signals.

Default requirements:

- Signal trade state must be `ENTER NOW`.
- Signal score must be at least `70`.
- Signal must be from a supported short-term family:
  - `short_term_day`
  - `short_term_swing`
- Entry waits for a pullback of `0.50%` below the original signal entry.

That means a signal can look good in the scanner but still wait in the execution layer until price reaches the trigger.

## 10. Ranking and Edge Score

The execution engine ranks candidates with an edge score.

Current default weights:

- Raw signal score: 30%
- Historical expectancy after modeled costs: 40%
- Trigger proximity: 15%
- Recency: 10%
- Lower volatility: 5%

Important behavior:

- Historical expectancy now has a larger default role than raw score.
- If raw score and expectancy strongly disagree, the row gets an explicit conflict flag.
- Ranking remains deterministic by using stable tie-breakers such as ticker, score, expectancy, and timestamp.

## 11. Transaction Costs

The model now has a simple transaction-cost scaffold.

Parameters:

- `commission_per_trade`
- `slippage_bps`
- `default_trade_notional`

Net expectancy is computed as:

`net_expectancy_pct = historical_expectancy_pct - estimated_transaction_cost_pct`

By default, costs are set to zero and the cost filter is disabled, so current behavior remains close to the original app. Once costs are configured, the portfolio engine prefers net expectancy.

## 12. Reward/Risk Filter

The execution layer can compute a simple reward/risk ratio using:

- Planned entry or trigger price.
- Target price.
- Stop-loss price.

Default RR setting:

- `min_reward_risk = 2.0`
- `reward_risk_filter_enabled = False`

When enabled, a triggered signal can be rejected if the target/stop structure does not meet the minimum reward/risk requirement.

## 13. Time Stop

The engine now includes a time-stop diagnostic scaffold.

Default settings:

- `time_stop_enabled = False`
- `time_stop_max_holding_days = 5`
- `time_stop_min_favorable_move_pct = 1.0`

When enabled, a triggered trade that fails to move in favor after the configured window can be marked as eligible for exit or downgrade.

This is currently diagnostic because the app does not yet have a true broker-fill or live position ledger.

## 14. Turnover Awareness

The engine estimates per-ticker trading frequency using recent logged signals.

Default settings:

- `turnover_lookback_days = 90`
- `high_turnover_annualized_signal_count = 48`
- `max_turnover_penalty = 0.30`

If a ticker produces too many signals, its raw portfolio weight can be penalized. The purpose is to avoid names that look active but churn too often.

## 15. Portfolio Eligibility

A stock must pass the execution layer before becoming a portfolio holding.

Portfolio eligibility requires:

- Trigger status is `triggered`.
- Net expectancy is positive when available.
- Position size is positive.
- Execution decision is not rejected.
- Risk penalty and turnover penalty do not reduce raw weight to zero.

Fragile cohorts can still be reduced sharply by the existing risk logic.

## 16. Research Logging

The strategy now supports append-only diagnostics logging.

Logging is controlled in `config/performance.py`:

- `RESEARCH_LOGGING_ENABLED = False`
- Log output: `data_store/research_logs/strategy_execution_diagnostics.jsonl`

When enabled, each execution row logs:

- Timestamp and ticker.
- Regime and horizon.
- Raw scores and labels.
- Historical expectancy and net expectancy.
- Edge score.
- Thresholds in effect.
- Estimated costs.
- Reward/risk.
- Turnover metrics.
- Execution decision.
- Rejection reason when applicable.

This JSONL file is meant for offline analysis and future backtesting.

## 17. Main Tuning Knobs

Primary files:

- `domain/backtest/thresholds.py`
- `config/performance.py`

Core thresholds:

- `min_short_term_scan_score`
- `min_long_term_scan_score`
- `min_execution_score`
- `execution_pullback_pct`

Ranking weights:

- `EDGE_SCORE_WEIGHTS.raw_signal_score`
- `EDGE_SCORE_WEIGHTS.historical_expectancy`
- `EDGE_SCORE_WEIGHTS.trigger_proximity`
- `EDGE_SCORE_WEIGHTS.recency`
- `EDGE_SCORE_WEIGHTS.lower_volatility`

Cost model:

- `COMMISSION_PER_TRADE`
- `SLIPPAGE_BPS`
- `DEFAULT_TRADE_NOTIONAL`
- `COST_FILTER_ENABLED`

Risk and execution:

- `REWARD_RISK_FILTER_ENABLED`
- `MIN_REWARD_RISK`
- `TIME_STOP_ENABLED`
- `TIME_STOP_MAX_HOLDING_DAYS`
- `TIME_STOP_MIN_FAVORABLE_MOVE_PCT`

Turnover:

- `TURNOVER_LOOKBACK_DAYS`
- `HIGH_TURNOVER_ANNUALIZED_SIGNAL_COUNT`
- `MAX_TURNOVER_PENALTY`

## 18. Current Strategy Summary

The current default strategy is conservative in execution:

- It scans broadly inside a liquid large-cap universe.
- It separates long-term investing logic from short-term trading logic.
- It now separates short-term momentum from short-term mean reversion.
- It requires `ENTER NOW` plus score >= 70 before Strategy_v1 considers execution.
- It waits for a 0.50% pullback.
- It ranks candidates with stronger emphasis on historical expectancy.
- It sizes only positive-expectancy triggered candidates after risk and turnover adjustments.

The main improvement opportunity is to turn the new diagnostics into offline research:

- Compare momentum vs mean-reversion expectancy separately.
- Sweep score thresholds and pullback percentages.
- Test whether RR filtering improves realized returns.
- Test whether cost and turnover penalties reduce churn without removing too much edge.
