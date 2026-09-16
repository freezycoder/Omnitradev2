# Form 144 proposed-sale intent shadow experiment

Pre-registered 2026-09-16. Shadow-only. Isolated branch. Do not deploy or merge without human approval. Not an alpha claim. Not a JoF-grade CAR study.

## Hypothesis

Form 144 notices of proposed sale of restricted/control securities provide an earlier intent signal than executed Form 4 sales. Ticker-level 144 clusters, and 144→Form4 match/conflict, improve shadow insider-sale calibration beyond Form4-only sell intensity.

## Falsifier

Match rate of Form 144 → subsequent Form 4 sale (code S / disposed) within the pre-registered window is too low to be useful; OR 144 features add no incremental information versus Form4-only sell intensity in walk-forward.

## Frozen protocol (do not retune after seeing results)

- Coverage start: `2022-10-01` (Form 144 XML v2.0 / electronic EDGAR window; corpus expected thinner than Form 4)
- Cluster: `N=3` distinct affiliate filer CIKs on the same ticker in `W=5` calendar days
- Match window `T=10` calendar days from approx sale date (fallback: filed date)
- Form 4 match codes: `S` with acquired/disposed `D` (proposed *sale*; code P is not applicable)
- Affiliate filter: filer CIK present, issuer CIK present, filer ≠ issuer; no officer/director flag exists on Form 144 XML
- Walk-forward: 3 expanding folds, 15-calendar-day embargo, success if nested lift in ≥2/3 eligible folds
- Live recommendations: unchanged (`applied_impact = 0`, `modeled_impact = 0`)
- Do not treat all 144s as bearish

## Data

- Form 144 XML (EDGAR form type 144 / 144/A), fields: proposed units, approx sale date, broker, prior 3-month sales, issuer/filer CIK
- Spec: Form 144 XML Technical Specification v2.0 (2022-10-17); filing guide at the SEC Form 144 electronic-file page
- Form 4 matching store: discover `data_store/section16_cache/open_market_transactions.json` from the prior Section-16 KEEP if present. On main, that file is absent; live SEC overlay only keeps a short-lookback `SecEventBundle`. Tests inject structured Form 4 sales.
- Prices: optional post-144 drift only. Descriptive. Not CAR. Not used for the verdict.

## Match study

Primary metric. For each eligible 144, look for a Form 4 open-market sale by the same issuer+filer (ticker fallback) inside T days. Report match rate, same-day vs subsequent split, median lead days, and false-intent rate (`1 - match_rate`). Same-day Form 4 counts as a match for the study but is *not* incremental lead for the nested model.

## Nested shadow model

Baseline: Form4-only sell count on the intent date (and a frozen 5-day lookback). Nested adds unmatched 144 intensity, the frozen cluster flag, and prior-3m 144 units. Target: subsequent Form 4 sale inside T days (excluding same-day). Metric: held-out MSE reduction with a positive unmatched-144 coefficient. This is a Form4 calibration test, not a return test.

## Success / failure

- SUCCESS (shadow calibration): match rate ≥ 40% AND nested lift in ≥2/3 eligible folds.
- SUCCESS_INFRA: match rate ≥ 40% but nested Form4-sale lift is null. Reclassify as infra conflict/intent radar, not alpha. Human call.
- FAIL: structured feed too thin after the affiliate filter; match rate below floor; or neither calibration lift nor a usable match radar.
- INCONCLUSIVE: some eligible notices but below the pre-registered count floor.

Optional post-144 drift is reported as `descriptive_only_not_car_not_alpha` and never decides the verdict.

## How to run

```bash
python scripts/run_form144_shadow.py --fixture
python scripts/run_form144_shadow.py --fixture-mode same_day
python scripts/run_form144_shadow.py --source path/to/form144.xml
```

`--fixture` is the CI-safe synthetic evaluation. Real EDGAR XML is optional and is not required to change live ranking.

## Constraints honored

- Isolated branch only
- Shadow-only: no live recommendation changes
- Do not deploy or merge without human approval
- Do not invent JoF-grade CAR claims
