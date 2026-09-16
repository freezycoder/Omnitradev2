# FINRA biweekly short-interest shadow experiment

Pre-registered 2026-09-16. Shadow-only. Isolated branch. Do not deploy or merge without human approval. No squeeze narrative products.

## Hypothesis

Biweekly FINRA short-interest levels (shares short, Δ vs prior settlement, days-to-cover, and % float when float is available) contain calibratable shadow information distinct from daily FINRA short-sale volume ratio (flow), usable for screens/gates without squeeze storytelling.

## Falsifier

After lag-correct dating to publication date, SI level/Δ/DTC features show no walk-forward association with pre-registered targets once daily short-volume ratio and liquidity controls are included; OR %float cannot be built at usable coverage.

## Event dating

- Source: FINRA Rule 4560 twice-monthly settlement reports.
- Publication: 7th business day after settlement.
- **Event date = publication date**, never settlement date.
- v1 weekday lag: the 7th Monday–Friday after settlement. Official FINRA calendars skip exchange holidays, so a holiday can move the true print by 1–2 sessions. That caveat is documented; settlement dating is still forbidden.

## Features

- `shortShares` / `log_short_shares`
- `pctChangePrior`
- `daysToCover`
- Frozen gates (not shopped): Δ ≥ +20%, Δ ≤ −20%, DTC ≥ 5, DTC ≥ 10
- `%float`: **deferred**. Not a native FINRA field. No frozen public-float series exists in OmniTrade. Pre-registered coverage floor if a float feed is later frozen: 70%.

## Nested design

- Baseline: daily FINRA `shortVolume / totalVolume` as-of joined to the SI publication session (lookback ≤ 10 calendar days).
- Nested: two-step Frisch-Waugh on each publication session — residualize SI on liquidity, residualize daily `short_ratio` on liquidity, then residualize SI on the short-volume residual.
- Primary target: 20-session excess return versus SPY.
- Secondary: 60-session excess, 20/60-session absolute return.
- Walk-forward: 3 expanding folds, 15-calendar-day embargo, publication-date cross-sectional Spearman IC, Newey–West lag in publication-cycle units (2 for 20d, 6 for 60d), two-sided p < 0.05.

## Success / failure

- SUCCESS: ≥1 SI feature (`log_short_shares`, `pct_change_prior`, `days_to_cover`) adds significant incremental lift vs short-volume-only in ≥2/3 eligible folds on `excess_20d`; lag dating documented; %float deferred (or later ships at coverage ≥ 70%).
- FAIL: fully redundant with daily short volume after controls; OR publication lag / coverage blocks the design.

## Constraints

- Shadow only. `applied_impact` stays 0. No live recommendation changes.
- No squeeze narrative products or labels.
- Do not deploy or merge without human approval.
