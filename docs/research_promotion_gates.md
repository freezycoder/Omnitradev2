# Research promotion gates

Process / infrastructure only. This is not a market-alpha feature and it does
not auto-promote any overlay onto live recommendations.

Shadow candidates carry an explicit lifecycle label:

| Label | Meaning |
| --- | --- |
| `UNVERIFIED` | Default. Evidence is being collected. Cannot touch live recommendations. |
| `PAPER` | Has a forward-paper receipt. Still cannot touch live recommendations. |
| `STALE` | Experiment evidence or source is expired/unavailable for promotion. |
| `DEMO` | Synthetic or demo data. Never actionable. |
| `REAL` | Live-eligible. Cannot be assigned by scanners. Requires every gate receipt, explicit human authorization, and the hard `LIVE_SHADOW_PROMOTION_ENABLED` switch (off). |

## Gate checklist (all required before any live-rec touch)

1. **OOS** — at least 50 resolved directional signals, 12 distinct signal dates, positive net expectancy after costs, average coverage ≥ 70%.
2. **Walk-forward** — at least two positive chronological folds with a calendar embargo. In-sample diagnostics are not a receipt.
3. **Multiple-testing** — pre-registered family or hierarchical cluster bootstrap whose lower interval stays positive after neighbor-threshold stability. A single in-sample screen is not a receipt. Existing `activation_ready` does **not** issue this receipt.
4. **Forward-paper** — labeled `PAPER` live-forward tracking with recorded outcomes. Historical OOS is not a substitute.

Passing today's shadow calibration `activation_ready` flag can emit OOS and
walk-forward receipts only. It cannot enable live execution and cannot assign
`REAL`.

## Enforcement

- `domain.research.promotion.promote_shadow_candidate_to_live` is the only
  promotion entry point. It fails closed without receipts, without human
  authorization, or while `LIVE_SHADOW_PROMOTION_ENABLED` is false.
- `write_live_recommendations` refuses any shadow view whose `applied_impact`
  is non-zero unless that same authorization succeeds.
- `seal_shadow_live_fields` and cache `*_from_dict` rebuilds discard spoofed
  `REAL` labels and non-zero `applied_impact` values.
- Auto-promote is forbidden. Readiness never writes live recommendations.

## In-flight experiments

Tagged in `domain.research.lifecycle.EXPERIMENTS` without changing live impact
(still zero):

- `group_rs` — existing relative-strength shadow layer
- `pead` — earnings-intelligence post-filing 3-session move
- `form4` — Form 4 open-market insider flow inside the SEC overlay
- `finra_short_vol` — registered UNVERIFIED placeholder; no signal implemented
