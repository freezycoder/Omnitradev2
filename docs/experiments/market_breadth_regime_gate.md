# Shadow market-breadth regime gate

Status: shadow-only daily panel + frozen-gate eval harness. Do not deploy or merge without human approval. Live recommendations, ranking, and buy lists are unchanged.

## Hypothesis

Universe participation metrics (daily A/D, up/down volume, % of the liquid universe above 20/50/200 DMA, and cap-weight versus equal-weight) form a **regime layer** that improves the conditional performance of existing single-name shadow signals (RS / earnings / Form 4) when used as a **gate**, not as a buy list.

Falsifier: after pre-registering the metric set and one gate rule, gated single-name shadow hits show no lift (or worse hit-rate / IC) versus ungated in walk-forward folds; **or** breadth features are redundant with existing RS-percentile aggregates.

## Frozen recipe (`breadth-gate-v1`, 2026-09-14)

Do not retune these numbers against in-sample IC or hit-rate. Sensitivity belongs in an appendix only.

Metric set:

- Advances / declines (close-to-close)
- Cumulative A/D line
- Up / down volume and their ratio
- % of the universe above 20 / 50 / 200 DMA (full window required)
- `SPY` return versus equal-weight universe; `RSP` when the download succeeds
- Optional secondary, not in the gate: 252-session new highs / new lows

Explicitly excluded (no TICK/intraday series to drop post-hoc): `TICK`, `TRIN`, intraday tick.

Equal-weight proxy: prefer `RSP`. If `RSP` is missing, construct an equal-weight daily return from `DEFAULT_STOCK_UNIVERSE` and label the proxy `equal_weight_universe`.

Gate **open** iff all of:

1. 50DMA coverage ≥ 80% of the requested universe
2. `% above 50DMA ≥ 55`
3. A/D is **not** diverging versus SPY over **10** sessions: closed when SPY's 10-session return is strictly positive **and** the A/D line declined over those same 10 sessions

Otherwise the gate is `closed`. If coverage or the 10-session inputs are missing, the gate is `unknown` (dropped from the gated cohort, kept in ungated).

`mode` is always `shadow`. `applied_impact` is always `0`.

## Eval

`MarketBreadthEvalService` joins existing resolved short-term shadow snapshots (RS / earnings / SEC Form 4 `sec_events` impact) onto the daily panel and walk-forwards three expanding windows with a 15-day calendar embargo.

Primary metrics (gated versus ungated on each validation fold):

- Spearman IC of the frozen signed shadow score versus realized return
- Top-decile hit-rate (share of the top 10% signed shadow scores with a positive realized return)

Nested model: OLS of realized return on RS-percentile aggregates (name universe/sector percentile, RS score, daily mean/median universe percentile) versus those features plus the frozen breadth set. Incremental IC and R² inside ±0.01 count as zero (redundancy fail).

Signed shadow score (frozen, not tuned): mean of available `(universe_percentile or RS score) - 50`, `earnings_score - 50`, and Form 4 `sec_events.modeled_impact`. News/macro overlay impact is not used as Form 4.

## Success / fail / abort

SUCCESS: the frozen gate improves ≥1 primary metric in ≥2/3 eligible folds; panel mean 50DMA and 200DMA coverage ≥ 80%; nested breadth is not redundant with RS percentiles.

FAIL: no gate lift, **or** nested R²/IC gain ≈ 0.

ABORT when any of these hold:

- Longest overlapping daily history `< 200` sessions (200 DMA cannot be built)
- Mean %above-MA coverage for 50DMA or 200DMA `< 80%`
- `SPY` history missing
- Fewer than 12 signed shadow hits per fold or 4 signal dates per fold after the embargo (3 eligible folds required)
- Gated validation sample `< 8` hits in a fold (that fold is ineligible)

History `< 504` sessions is flagged as below the recommended 2y walk-forward budget but is **not** a hard abort once 200 DMA coverage clears.

Demo OHLCV in `data_store/demo_data.json` is 190 sessions and has no `SPY`/`RSP`. A demo-only run must abort. A 2y live download can still abort: emerging/new-listing names in `DEFAULT_STOCK_UNIVERSE` pull mean 200DMA coverage below 80%, and a walk-forward claim also needs the local shadow signal outcome log. Re-run `scripts/run_market_breadth_shadow.py` against a 2y panel plus that log; do not drop short-history names post-hoc to clear the coverage gate.

## What this does not do

- No live buy list
- No live recommendation, score, or ranking change
- No threshold shopping on `%above-MA` or the A/D window
- No merge or deploy without human approval
