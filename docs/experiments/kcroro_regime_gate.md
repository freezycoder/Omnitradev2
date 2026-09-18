# KCRORO regime gate (shadow-only)

Status: **shadow research**. Isolated branch. Do not deploy or merge without
human approval. Not a stock picker. Applied impact is 0.

## Citation

Chari, Anusha, Karlye Dilts Stedman, and Christian Lundblad, 2024, "Risk-On
Risk-Off: A Multifaceted Approach to Measuring Global Investor Risk Appetite,"
Federal Reserve Bank of Kansas City Research Working Paper no. 24-12.

- Index: https://www.kansascityfed.org/data-and-trends/risk-on-risk-off-index/
- README: https://www.kansascityfed.org/documents/10930/RORO_Index_README.pdf
- FRED `KCRORO`: https://fred.stlouisfed.org/series/KCRORO

PCA of standardized daily changes. Positive ≈ risk-off, negative ≈ risk-on.
Subindexes: spreads (`KCROROS`), equities (`KCROROE`), liquidity/funding
(`KCROROL`), FX-gold (`KCROROG`).

## Hypothesis

Daily KCRORO (and optionally equity/spreads/liquidity/FX-gold subindexes)
provides a faster risk-on/off regime gate than weekly NFCI, with incremental
value for throttling long screens beyond HY OAS ± NFCI.

Falsifier: nested walk-forward shows KCRORO adds no gated lift / incremental
R² vs HY OAS + NFCI; **or** equity subindex alone drives results (circular
with SPX).

## Frozen recipe (`kcroro-gate-v1`, 2026-09-17)

Do not retune against in-sample Sharpe, IC, or gated lift.

| Item | Frozen value |
| --- | --- |
| Series | `KCRORO` headline in the gate. Subindexes ingested for ablation only. |
| **ONE throttle rule** | throttle weight `0.50` when latest released KCRORO `> 0` **or** causal 20-session sum of KCRORO shocks `> 0` |
| Subindexes in the gate | no |
| Join key | **release date**, never the observation date |
| Fallback release lag | +1 calendar day (verified 2026-09-08 obs = 0.1814 → 2026-09-09 update) |
| Mode | `shadow` |

Initial-release ALFRED vintages are preferred. If vintages are unavailable,
the frozen +1 calendar-day lag is applied so a print cannot gate that same
observation day.

## KEEP comparators (discovered, not invented)

HY OAS from `cursor/shadow-credit-hy-oas-regime-6c9c` as `credit-gate-v1`
(frozen 2026-09-15):

- HY `BAMLH0A0HYM2`, IG `BAMLC0A0CM`
- Throttle when 20-session HY OAS change `> 30` bp **or** causal trailing-252
  percentile `>= 80`

NFCI from `cursor/shadow-nfci-regime-gate-0e2b` as `nfci-gate-v1`
(frozen 2026-09-16):

- `NFCI` only; `ANFCI` not in v1
- Throttle when 4-week Δ `> 0` for 3 consecutive weekly prints
- Join on release date (fallback +6 calendar days)

If either KEEP series cannot be ingested to its hard minimum, the nested kill
switch **aborts** rather than inventing a substitute.

## Eval

Harness: `KcroroRegimeEvalService` / `scripts/run_kcroro_regime_shadow.py`

Labels: resolved long-biased long-term screens
(`long_term_3m|6m|12m`, min scan score, Strong Buy / Buy) with
`realized_return_pct`.

Walk-forward: 3 folds, 15-day embargo, same construction as calibration
research.

### Gate arms

1. ungated
2. HY-OAS-only (KEEP throttle)
3. NFCI-only (KEEP throttle)
4. RORO-only (frozen throttle)
5. HY+NFCI
6. HY+NFCI+RORO
7. RORO non-equity ablation (spreads/funding/FX-gold equal-weight mean, same rule)
8. HY+NFCI+RORO-non-equity

VIX is an optional nested control when a VIX history is supplied. It is not a
gate input.

### Nested arms (OLS on realized return)

- baseline: SPY 20d realized vol (± VIX level if present)
- HY-only / NFCI-only / RORO-only / HY+NFCI / HY+NFCI+RORO / RORO-non-equity

Kill comparison is **HY+NFCI+RORO versus HY+NFCI**, not versus ungated.

## Success / fail / abort

- **SUCCESS:** KCRORO adds incremental gated performance (HY+NFCI+RORO vs
  HY+NFCI) on Sharpe or max drawdown, **or** incremental nested IC / R² versus
  HY+NFCI, in `>= 2/3` eligible folds, **and** the equity-leg ablation still
  leaves non-zero lift from spreads/funding/FX-gold.
- **FAIL / KILL:** mean incremental IC and R² versus HY+NFCI sit inside ±0.01
  **and** HY+NFCI+RORO shows no primary-metric gated lift versus HY+NFCI; **or**
  headline lift vanishes after dropping the equity subindex
  (`kill_equity_leg_circular`).
- **ABORT:** KCRORO sessions `< 252`, KEEP HY sessions `< 252`, KEEP NFCI weeks
  `< 104`, fewer than 3 eligible folds, or ablation subindexes unavailable.

## What this does not do

- Does not change live scores, ranking, or recommendations
- Does not shop subindex stacks until significant
- Does not use the observation date as a same-day signal
- Does not merge or deploy without human approval
