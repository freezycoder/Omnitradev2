# Shadow industry-group RS + RRG experiment

Status: shadow-only plumbing + offline nested-model harness. Do not deploy or merge without human approval. Live recommendations and ranking surfaces are unchanged.

## Hypothesis

Group-level relative strength (industry rotation) plus RRG axes add incremental predictive / calibration signal beyond the existing single-name shadow RS versus SPY and the sector ETF, including universe and sector percentile ranks.

Falsifier: after matching the existing single-name RS features, group RS / rank / RRG features show no lift on forward returns or rank-stability metrics in held-out periods, or only spurious lift that dies under walk-forward.

## Map (A)

IBD's ~197 industry groups are not a public, redistributable membership file. This experiment freezes a **GICS sub-industry proxy**:

- Version: `gics-subindustry-proxy-v1`
- Frozen on: `2026-09-14`
- Taxonomy label: `gics_subindustry_proxy`
- Source: public GICS structure (MSCI/S&P), applied to `DEFAULT_STOCK_UNIVERSE`
- Coverage abort: mapped share of the evaluated liquid universe `< 80%`

The proxy is coarser than IBD 197 and is labeled as a proxy in every payload. Lift on this map is not evidence for IBD's proprietary taxonomy.

No prior RS-extension KILL was found in the research execution log or repository history.

## Shadow features (B, C)

During a full scan, after single-name RS and percentile ranks are assigned:

- Equal-weight group average of constituent `raw_strength_pct`
- Group rank (1 = strongest) and rank percentile
- Rank deltas at 1W / 1M / 3M / 6M (5 / 21 / 63 / 126 sessions)
- Pre-registered RRG recipe (do not tune to in-sample IC):
  - Weekly last observation (`W-FRI`)
  - RS-Ratio = trailing 52-week z-score of weekly group average RS (`min_periods=26`)
  - RS-Momentum = trailing 52-week z-score of the 1-week change in weekly group average RS
  - Quadrants: Leading / Weakening / Lagging / Improving from the signs of those axes

`mode` is always `shadow`. `applied_impact` is always `0`. Signal snapshots store `industry_group_relative_strength` beside `relative_strength`. Scanner sort keys remain `long_term_score` and `short_term_score`.

## Offline eval (D)

`IndustryGroupRsEvalService` walk-forwards nested OLS models:

1. Baseline: existing single-name RS features only
2. Nested: baseline + group RS / rank / RRG features

Pre-registered primary horizon: **20 trading-day excess versus SPY**.
Pre-registered primary metrics: Spearman IC and top-decile hit rate.
Secondary (reported, not used to pick a winner): 5d and 60d excess.

Success: nested beats baseline on at least one primary 20d metric with positive lift in at least 2 of 3 walk-forward folds, and no live surface change.

Fail: no significant lift after controlling for single-name RS; or map coverage `< 80%`; or compute/latency beyond the shadow budget.

## Abort / data-gap criteria

Abort the live walk-forward claim when any of these hold:

- Map coverage of the evaluated liquid universe `< 80%`
- Longest overlapping constituent daily history `< 504` sessions (~2y recommended for RS windows + RRG tails)
- Fewer than 12 weekly cross-sections or fewer than 20 observations per fold after the 15-day embargo
- Group features drop out of a fold (`< 50%` non-null coverage)

If production caches are shorter than two years, ship the shadow logs anyway and treat the nested-model verdict as aborted until a price panel with sufficient history is supplied to `evaluate_price_panel`.

## Overfitting controls

- One frozen RRG recipe and one primary horizon/metric pair
- Frozen map version
- Singletons included in the primary eval (group RS equals name RS); singleton share is reported as a diagnostic, not used to cherry-pick
- 5d / 60d and singleton-excluded runs are sensitivity only
