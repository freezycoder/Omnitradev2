# Research promotion gates

Process / infrastructure only. This is not a market-alpha feature and it does
not auto-promote any overlay onto live recommendations. Release stays
paper/shadow. Success metric is enforcement plus tests, not a market backtest.

Shadow candidates carry a provenance label **and** a research stage.

## Provenance labels

| Label | Meaning |
| --- | --- |
| `UNVERIFIED` | Default. Evidence is being collected. Cannot touch live recommendations. |
| `PAPER` | Forward-paper or Qualified. Still cannot touch live recommendations. |
| `STALE` | Experiment evidence expired, or the candidate is retired. |
| `DEMO` | Synthetic or demo data. Never actionable. |
| `REAL` | Champion / live-eligible. Cannot be assigned by scanners. |

## Research stages (OmniTrade names)

Adapted from the Candidate → Backtest → OOS → Shadow paper → Qualified →
Champion → Retired pattern. Copy the process shape, not external claims.

| Stage | Analog | Live write |
| --- | --- | --- |
| `candidate` | Candidate | No |
| `in_sample` | Backtest | No |
| `oos_validated` | OOS | No |
| `forward_paper` | Shadow paper | No |
| `qualified` | Qualified | No. Review-eligible; release stays paper/shadow. |
| `champion` | Champion | Only if every receipt, human authorization, and the live switch are on. Switch is off. |
| `retired` | Retired | No |

Live/recommendation writers require **Qualified+** (`qualified` or `champion`).
Qualified is necessary and not sufficient. This PR does not enable Champion.

## Gate checklist (minimal pre-registered set)

All four are required before Qualified. Failed gates store `rejection_evidence`.
Monte Carlo is optional and is **not** a required gate.

1. **OOS** — at least 50 resolved directional signals, 12 distinct signal dates, positive net expectancy after costs, average coverage ≥ 70%.
2. **Walk-forward** — at least two positive chronological folds with a calendar embargo. In-sample diagnostics are not a receipt.
3. **Multiple-testing control** — pre-registered family or hierarchical cluster bootstrap whose lower interval stays positive after neighbor-threshold stability. A single in-sample screen is not a receipt. Existing `activation_ready` does **not** issue this receipt.
4. **Forward-paper period** — labeled `PAPER` live-forward tracking with recorded outcomes. Historical OOS is not a substitute.

Passing today's shadow calibration `activation_ready` flag can emit OOS and
walk-forward receipts only. It cannot enable live execution, cannot assign
`REAL` / `champion`, and cannot flip the readiness UI to live.

## Enforcement

- `domain.research.promotion.promote_shadow_candidate_to_live` is the only
  promotion entry point. It fails closed without receipts, below Qualified+,
  without human authorization, or while `LIVE_SHADOW_PROMOTION_ENABLED` is false.
- `write_live_recommendations` refuses any shadow view whose `applied_impact`
  is non-zero unless that same authorization succeeds.
- `seal_shadow_live_fields` and cache `*_from_dict` rebuilds discard spoofed
  `REAL` / `champion` values and non-zero `applied_impact`.
- Auto-promote is forbidden. Readiness never writes live recommendations.
- Calibration payloads set `cannot_flip_live: true` and `release_mode: paper_shadow`.

## In-flight experiments

Tagged in `domain.research.lifecycle.EXPERIMENTS` as `candidate` / `UNVERIFIED`
without changing live impact (still zero):

- `group_rs` — existing relative-strength shadow layer
- `pead` — earnings-intelligence post-filing 3-session move
- `form4` — Form 4 open-market insider flow inside the SEC overlay
- `finra_short_vol` — registered UNVERIFIED placeholder; no signal implemented
- `stfm_funding_liquidity` — OFR STFM DVP/GCF+MMF+SOFR/EFFR funding overlay; nested kill vs HY+NFCI and SOFR-only; RORO not discovered
