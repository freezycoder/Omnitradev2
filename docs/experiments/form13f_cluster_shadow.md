# Form 13F notable-cluster shadow experiment

Pre-registered 2026-09-15. Shadow-only. Isolated branch. Do not deploy or merge without human approval.

## Hypothesis

Names with ≥K “notable” 13F managers newly entering (or exiting) the same reportable quarter, and/or multi-quarter accumulation streaks, show calibratable forward excess returns after the public filing window — orthogonal to Form 4 daily insider flow.

## Falsifier

After freezing notable-fund taxonomy v1 and K=3, cluster-entry (exit) portfolios earn no excess vs matched non-cluster names in walk-forward once ETF/index churn is filtered; OR any edge is subsumed by size/liquidity factors.

## Frozen protocol (do not retune after seeing returns)

- Taxonomy version: `v1`
- Cluster K: `3` notable managers newly entering or exiting the same ticker and reportable quarter
- Streak: `≥2` consecutive quarters of net notable adds
- Event date: filing availability date of the K-th notable manager (`SUBMISSION.FILING_DATE`), never quarter-end
- Forward windows: 20 / 60 / 120 sessions; primary = 20d size/liquidity-matched excess
- Walk-forward: 3 expanding folds, 45-calendar-day embargo, ≥8 primary events per fold, success if ≥2/3 folds have mean matched excess > 0
- Live recommendations: unchanged (`applied_impact = 0`)

## Notable-manager taxonomy v1

Frozen before evaluation. A manager is notable if:

1. The CIK is on the named activist or quant/HF list, or
2. Same-filing 13F equity AUM ≥ $10B

unless the CIK is on the passive/index exclusion list (Vanguard, BlackRock, State Street, Geode, Invesco, Fidelity/FMR, Schwab, Northern Trust, BNY Mellon). Named lists are identity/style labels, not return-tuned.

## Data

- SEC Form 13F data sets: https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets
- INFOTABLE flattened to TSV inside quarterly (through 2023Q4) then publication-window ZIPs (2024+)
- Coverage from May 2013 XML onward
- VALUE units: thousands before 2023-01-03 filing date, dollars on/after that cutover
- CUSIP→ticker: frozen 8-character map plus issuer-name fallback; unmapped CUSIPs are dropped from clusters and counted in data quality
- Options (`PUT`/`CALL`) and ETF-titled rows are dropped

## ETF / index reconstitution filter

A cluster is `etf_churn_suspect` when ≥2 frozen passive/index 13F filers also newly enter or exit the same ticker in that reportable quarter. Those events are removed from the primary book.

Reportable quarter-ends in March/June/September/December are labeled as S&P (and June as Russell) reconstitution windows. The label is residual-risk documentation; it does not drop a cluster by itself.

### Residual churn risk

- Closet indexers that are not on the passive exclusion list can still enter index adds and count toward K.
- Publication-window ZIPs can mix late amendments across reportable quarters; event dating still uses each filing date.
- No paid S&P/Russell membership calendar is used. Unlisted reconstitutions can remain in the book.
- FMR is excluded as index-adjacent; other mixed active/passive 13F umbrellas may still leak.

## Baselines

- No cluster feature
- Single notable new-holder (exactly one notable entry, not a cluster)
- Size/liquidity-matched non-cluster names (nearest 20-session dollar ADV, max log-distance 0.75)

## Orthogonality to Form 4

Form 4 is a different filer set and a daily window. If Form 4 cluster keys are supplied, nested matched excess is reported on 13F cluster-entry names without a same-date Form 4 cluster. Missing Form 4 data does not fail the experiment.

## Success / failure

- SUCCESS: pre-registered K=3 cluster-entry (or streak) mean matched 20d excess > 0 in ≥2/3 eligible folds after lag-correct dating; coverage adequate.
- FAIL: no matched excess; OR taxonomy would have to be retuned to recover a result; OR ETF churn explains the book; OR SPY-excess is subsumed by the size/liquidity match.
- INCONCLUSIVE: fewer than two eligible folds or fewer than eight primary events.

## How to run

```bash
python scripts/run_form13f_shadow.py --fixture
python scripts/run_form13f_shadow.py --source path/to/2023q4_form13f.zip
```

`--fixture` is the CI-safe synthetic evaluation. Real SEC ZIPs are optional and are not required to change live ranking.

## Constraints honored

- Isolated branch only
- Shadow-only: no live recommendation changes
- Do not deploy or merge without human approval
