# NFCI regime gate (shadow-only)

Status: **shadow research**. Isolated branch. Do not deploy or merge without
human approval. Not a stock picker. Applied impact is 0.

## Hypothesis

NFCI level and persistence (rising vs falling) provide an equity risk-on/off
regime gate that improves long-screen conditional performance beyond KEEP’d
HY OAS / HY–IG alone.

Falsifier: nested models show NFCI adds no incremental R² / IC / gated
performance vs HY OAS (and breadth if present) in walk-forward — then **KILL**
as redundant.

## Frozen recipe (`nfci-gate-v1`, 2026-09-16)

Do not retune against in-sample Sharpe, IC, or gated lift.

| Item | Frozen value |
| --- | --- |
| Series | `NFCI` only. `ANFCI` and subindexes are **not** ingested in v1. |
| Features | level, 4-week Δ, rising-streak count |
| Persistence N | **3** consecutive weekly prints |
| Rising week | 4-week Δ `> 0` |
| **ONE throttle rule** | throttle weight `0.50` when rising streak `>= 3` |
| Level in the gate | no (level is a nested-model feature only) |
| Join key | **release date**, never the Friday week-end label |
| Fallback release lag | +6 calendar days (verified 2026-09-04 obs → 2026-09-10 update) |
| Mode | `shadow` |

Initial-release ALFRED vintages (`realtime_start` / `realtime_end` window) are
preferred. If vintages are unavailable, the frozen +6 calendar-day lag is
applied to the week-end label so a Friday print cannot gate that same Friday.

## KEEP HY OAS comparator (discovered, not invented)

Discovered on `cursor/shadow-credit-hy-oas-regime-6c9c` as `credit-gate-v1`
(frozen 2026-09-15):

- HY `BAMLH0A0HYM2`, IG `BAMLC0A0CM`
- Throttle when 20-session HY OAS change `> 30` bp **or** causal trailing-252
  percentile `>= 80`
- HY−IG gap is ingested for nested diagnostics only; it is **not** in the KEEP
  gate

If the KEEP series cannot be ingested to the hard minimum, the nested kill
switch **aborts** rather than inventing a substitute credit rule.

## Eval

Harness: `NfciRegimeEvalService` / `scripts/run_nfci_regime_shadow.py`

Labels: resolved long-biased long-term screens
(`long_term_3m|6m|12m`, min scan score, Strong Buy / Buy) with
`realized_return_pct`.

Walk-forward: 3 folds, 15-day embargo, same construction as calibration
research.

### Gate arms

1. ungated
2. HY-OAS-only (KEEP throttle)
3. NFCI-only (frozen persistence throttle)
4. HY+NFCI (product of KEEP and NFCI weights)
5. HY+NFCI+breadth when a breadth status map is supplied

### Nested arms (OLS on realized return)

- baseline: SPY 20d realized vol (± `% above 50DMA` if breadth is present)
- HY-only: baseline + KEEP HY features
- NFCI-only: baseline + NFCI level / 4w Δ / rising streak
- HY+NFCI: baseline + both

Kill comparison is **HY+NFCI versus HY-only**, not versus ungated.

## Success / fail / abort

- **SUCCESS:** NFCI adds incremental gated performance (HY+NFCI vs HY OAS) on
  Sharpe or max drawdown, **or** incremental nested IC / R² versus HY OAS, in
  `>= 2/3` eligible folds.
- **FAIL / KILL:** mean incremental IC and R² versus HY OAS sit inside ±0.01
  **and** HY+NFCI shows no primary-metric gated lift versus HY OAS alone.
- **ABORT:** NFCI weeks `< 104`, KEEP HY sessions `< 252`, or fewer than 3
  eligible folds.

## What this does not do

- Does not change live scores, ranking, or recommendations
- Does not shop ANFCI / subindexes until significant
- Does not use the week-end Friday label as a same-week signal
- Does not merge or deploy without human approval
