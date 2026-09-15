# Shadow HY OAS credit regime gate

Status: shadow-only daily ingest + frozen-throttle eval harness. Do not deploy or merge without human approval. Live recommendations, ranking, and buy lists are unchanged. This is **not** a stock picker.

## Hypothesis

Daily HY OAS level and short-horizon widening velocity (and optionally the HY−IG OAS gap), from FRED ICE BofA series, form a credit risk-on/off regime gate that improves conditional performance of long-biased shadow equity screens when used to throttle aggressiveness. Complementary to equity-internal breadth KEEP.

Falsifier: after pre-registering the level/velocity rule, gated long-screen performance is no better (or worse) than ungated / breadth-only gates in walk-forward; **or** credit features add nothing once equity vol / breadth controls are included.

## Frozen recipe (`credit-gate-v1`, 2026-09-15)

Do not retune these numbers against in-sample Sharpe or drawdown. Sensitivity belongs in an appendix only. March 2020 is descriptive only and is not a tune target.

Ingest:

- `BAMLH0A0HYM2` HY OAS level
- `BAMLC0A0CM` IG OAS for the HY−IG gap
- Derived: 20-session Δ (bp), 5-session weekly Δ (bp), causal trailing-252 percentile

ONE throttle rule (picked once):

Reduce long-screen aggressiveness when **either**:

1. 20-session HY OAS change `> 30` bp, **or**
2. Causal trailing-252 HY OAS percentile `≥ 80` (minimum 126 prior observations)

Otherwise the gate is `full` (weight `1.0`). If HY OAS or the 20-session change is missing, the gate is `unknown` (dropped from the credit-gated book, kept in ungated).

Throttle weight is frozen at `0.50` (half gross exposure; remainder cash). Weekly Δ and HY−IG gap are ingested and used in nested diagnostics; they are **not** in the OR gate.

`mode` is always `shadow`. `applied_impact` is always `0`.

Why these numbers (pre-registered, not crisis-fit): 20 sessions is the practitioner horizon; 30 bp is a round widening that is larger than typical day-to-day noise and far smaller than 2020 spike magnitudes. The trailing-252 80th percentile adapts to the post-2023 tight-spread regime without installing a 2020-era 5%+ level that would never fire.

## History plan

The public FRED window from April 2026 is about three years. That is enough for this frozen recipe (20-session velocity, trailing-252 percentile, three walk-forward folds).

- Hard minimum: 252 HY OAS observations. Below that: **FAIL data-blocked**.
- Recommended: 504 observations. Below that, still eligible if the hard minimum clears.
- If FRED is shorter than 504, pull ALFRED vintage `2026-03-31` (pre-truncation) and merge.
- Public FRED CSV is a research fallback when no API key is configured. Same ICE constraints apply.
- March 2020 is outside the current public window; do not extend history post-hoc to chase that anecdote.

Do not commit ICE observation dumps to git.

## Eval

`CreditRegimeEvalService` joins existing resolved **long-biased** shadow screens (`Strong Buy` / `Buy`, score ≥ scanner min) onto the daily credit panel and walk-forwards three expanding windows with a 15-day calendar embargo.

Comparators on each validation fold:

- Ungated long-screen book (equal-weight daily mean return)
- Credit-gated book (weight `1.0` on `full`, `0.50` on `throttle`)
- Breadth-gated book if KEEP breadth ships a date→status map; otherwise `not_available`
- Both: KEEP breadth `open` **and** the credit throttle weight

Primary metrics (credit-gated versus ungated):

- Annualized Sharpe of the daily book
- Max drawdown of the cumulative book (signed peak-to-trough; higher is better)

Nested model: OLS of realized return on equity vol (`SPY` 20-session realized vol) and, when present, breadth `% above 50DMA`, versus those controls plus the frozen credit feature set. Incremental IC and R² inside ±0.01 count as zero (credit is subsumed).

Lead/lag of 20-session HY OAS change versus SPY returns at offsets `{-20,-10,-5,0,+5,+10,+20}` is reported descriptively and is not a gate input.

## Success / fail / abort

SUCCESS: the frozen credit throttle improves ≥1 primary metric in ≥2/3 eligible folds; HY OAS ingest meets the hard minimum; nested credit is not redundant with vol (or breadth+vol).

FAIL: no incremental lift; **or** nested R²/IC gain ≈ 0; **or** the intended surface is a productized ICE-branded display without an ICE license.

ABORT / data-blocked when any of these hold:

- HY OAS observations `< 252`
- Empty credit panel or fewer than 20 sessions with a 20-session change
- Fewer than 12 long-screen hits per fold or 4 signal dates per fold after the embargo (3 eligible folds required)
- Credit-gated validation book `< 4` days in a fold (that fold is ineligible)

A local outcome log with no long-term screen hits must abort. That is the correct plumbing outcome, not a license to retune the gate.

## What this does not do

- No stock picking
- No live recommendation, score, ranking, or buy-list change
- No threshold shopping on OAS level or 20-session widening
- No merge or deploy without human approval
- No productized ICE-branded display; see `docs/legal/ice_bofa_fred_redistribution.md`
