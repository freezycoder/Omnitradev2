# OFR STFM funding-liquidity overlay (shadow-only)

Status: **shadow research**. Isolated branch. Do not deploy or merge without
human approval. Macro/regime only. Not a stock picker. Applied impact is 0.

## Hypothesis

Daily OFR repo venue volumes (DVP/GCF totals) plus MMF aggregates and NY Fed
reference rates (SOFR/EFFR) form a funding-liquidity stress overlay that
improves equity risk-off gating beyond HY OAS / NFCI / RORO alone. Value is in
**volumes + MMF**, not SOFR alone.

Falsifier: after nesting on HY+NFCI(+RORO), STFM features add no lift; **or**
SOFR/EFFR alone match the full pack (volumes/MMF worthless). Then **KILL**.

## Frozen mnemonic set (`stfm-gate-v1`, 2026-09-17)

Freeze this list **before** eval. Do not shop additional STFM series. Do not
retune against Sep 2019 / Mar 2020 windows.

| Role | Mnemonic | Dataset | Frequency | Vintage |
| --- | --- | --- | --- | --- |
| DVP total volume | `REPO-DVP_TV_TOT-P` | repo | Daily | Preliminary |
| GCF total volume | `REPO-GCF_TV_TOT-P` | repo | Daily | Preliminary |
| MMF aggregate | `MMF-MMF_TOT-M` | mmf | Monthly | Monthly revisions |
| SOFR | `FNYR-SOFR-A` | fnyr | Daily | Current |
| EFFR | `FNYR-EFFR-A` | fnyr | Daily | Current |

Rejected on purpose (not ingested): `*-F` finals, tenor/collateral splits,
TGCR/BGCR/OBFR, MMF repo subsets, `nypd`, `tyld`, and every other STFM
mnemonic. The public catalog has hundreds of series; shopping them is the
overfitting path this freeze blocks.

Source: OFR STFM API, no token, base `https://data.financialresearch.gov/v1`.
Confirmed live 2026-09-17 via `/v1/series/dataset?dataset=repo|mmf|fnyr`.

## Frozen features and ONE stress flag

Features (causal; no look-ahead):

- z-scored DVP and GCF volumes (trailing 252 sessions, min 126 prior prints)
- 5-session and 20-session percent Δ of DVP and GCF volumes
- MMF total level, causal z-score on the monthly panel, 1-month percent Δ
- SOFR, EFFR, SOFR−EFFR spread (bp), 5-session Δ of that spread (bp)

**ONE full-pack stress flag** (`joint_volume_drop_and_spread_widen`):

Throttle long-screen weight to `0.50` when **both**:

1. DVP z-score `<= -1.0` **or** GCF z-score `<= -1.0` (volume drop), **and**
2. 5-session SOFR−EFFR change `> 3` bp (spread widen)

Otherwise `full` (weight `1.0`). Missing volume z **or** missing spread Δ →
`unknown` (dropped from gated books, kept in ungated). Null OFR prints are
**not** filled with zero.

**SOFR-only ablation flag** (control, not the challenger):

Throttle when the same 5-session SOFR−EFFR change `> 3` bp. Volumes and MMF
are absent from this control.

MMF is in the frozen feature pack and nested models. It is **not** a second
gate rule.

`mode` is always `shadow`. `applied_impact` is always `0`.

## Publish lag / null disclosure

Joins use **release date**, never the raw observation label.

| Series | Frozen lag | Verified 2026-09-17 |
| --- | --- | --- |
| Daily repo + fnyr | +1 calendar day | DVP/GCF/SOFR/EFFR obs `2026-09-15`, STFM `last_update` `2026-09-16` |
| Monthly MMF | +20 calendar days after month-end | `MMF-MMF_TOT-M` obs `2026-07-31`, `last_update` `2026-08-17` |

Nulls and disclosure revisions: skip the print (`unknown` / missing feature).
Do not interpolate. Preliminary repo vintages (`-P`) are the ingested series;
finals (`-F`) stay out of v1.

## Prior regime series (discovered, not invented)

| Series | Present? | Where |
| --- | --- | --- |
| HY OAS | Yes | Live FRED overlay `BAMLH0A0HYM2`. KEEP gate `credit-gate-v1` on `cursor/shadow-credit-hy-oas-regime-6c9c` (frozen 2026-09-15). |
| NFCI | Yes | Live FRED overlay `NFCI`. KEEP gate `nfci-gate-v1` on `cursor/shadow-nfci-regime-gate-0e2b` (frozen 2026-09-16). Funding-leg composite, not a subindex. |
| RORO | **No** | Not in `main`, not in remote shadow-regime branches. v1 does **not** invent a RORO proxy. Nested kill is HY+NFCI. |

KEEP HY OAS throttle (discovered): 20-session HY OAS change `> 30` bp **or**
causal trailing-252 percentile `>= 80`. HY−IG gap is nested-only.

KEEP NFCI throttle (discovered): 4-week Δ strictly positive for **3**
consecutive weekly prints, joined on **release date** (fallback +6 calendar
days). ANFCI/subindexes are not ingested.

If KEEP HY or NFCI cannot meet their hard minima, the nested kill **aborts**
rather than substituting a home-grown credit/funding rule.

ICE BofA OAS via FRED is research-only. Do not productize ICE-branded prints.

## Eval

Harness: `StfmFundingLiquidityEvalService` /
`scripts/run_stfm_funding_liquidity_shadow.py`

Labels: resolved long-biased long-term screens
(`long_term_3m|6m|12m`, min scan score, Strong Buy / Buy) with
`realized_return_pct`.

Walk-forward: 3 folds, 15-day embargo, same construction as calibration
research.

### Gate arms

1. ungated
2. HY-OAS-only (KEEP)
3. NFCI-only (KEEP)
4. HY+NFCI
5. SOFR-only (ablation control)
6. STFM full pack (frozen joint flag)
7. HY+NFCI+STFM (nested incremental)

RORO is a reserved unused arm (`roro_ingest_v1 = false`).

### Nested arms (OLS on realized return)

- baseline: SPY 20d realized vol
- HY+NFCI: baseline + KEEP HY + KEEP NFCI features
- SOFR-only: baseline + SOFR−EFFR level/5d Δ
- STFM full: baseline + SOFR + volume z/Δ + MMF
- HY+NFCI+STFM: HY+NFCI + STFM full features

Kill comparisons:

- **HY+NFCI+STFM versus HY+NFCI** (nested funding-leg redundancy)
- **STFM full versus SOFR-only** (volumes/MMF worthless)

## Success / fail / abort

- **SUCCESS:** the full STFM pack **beats SOFR-only** on Sharpe or max
  drawdown **and** adds incremental gated lift **or** nested IC/R² versus
  HY+NFCI, each in `>= 2/3` eligible folds.
- **FAIL / KILL no lift:** full pack does not add incremental gated /
  nested lift versus HY+NFCI.
- **FAIL / KILL SOFR-only:** volumes+MMF add `|ΔIC|` and `|ΔR²|` inside
  ±0.01 versus SOFR-only **and** the full pack shows no primary-metric gated
  lift versus SOFR-only.
- **ABORT:** STFM daily sessions `< 252`, KEEP HY sessions `< 252`, KEEP NFCI
  weeks `< 104`, or fewer than 3 eligible folds. A local outcome log with no
  long-screen hits must abort. That is the correct plumbing outcome, not a
  license to retune.

## What this does not do

- Does not change live scores, ranking, or recommendations
- Does not shop STFM mnemonics after freeze
- Does not invent RORO
- Does not wire OFR into ticker/scan/API paths
- Does not merge or deploy without human approval
