# SC 13D activist shadow event study

Status: shadow-only research. Do not deploy or merge without human approval.
Protocol version: `sc13d_activist_shadow_v1_2026-09-15`
Lexicon version: `sc13d_activist_lexicon_v1_2026-09-15`

## Hypothesis

New SC 13D (/A) filings that disclose activist intent (purpose-of-transaction / hostile or board-seat language), plus optional 13G→13D conversion flags, produce positive abnormal returns around filing that are usable as shadow event features — distinct from Form-4 insider clusters.

## Falsifier

In a modern post-2008 sample with pre-registered event filters, mean CAR around activist 13D is indistinguishable from 0 after excluding passive 13G-like language and controlling for pre-filing run-up; OR the effect exists only inside (−20,0) and is fully anticipated (no tradeable post-file window).

## Frozen primary rules

- Sample start: 2009-01-01.
- Forms: SC 13D and SC 13D/A.
- Primary subset: purpose text matches the frozen hostile, board-seat, or specific activist-purpose lexicon.
- Exclusions: passive / 13G-like language and pure financing disclosure when no primary activist phrase is present.
- Ambiguous purpose (generic "may discuss with management") is a descriptive stratum only.
- Primary post-file window: CAR(0,+5) vs SPY. Confirmatory post-file windows: (0,+1), (0,+20), (+1,+60). Pre-window (−20,−1) is diagnostic only.
- Success: significant positive mean CAR in ≥1 frozen post-file window in ≥2 walk-forward folds, with activist N ≥ 40.
- Fail: null post-file CAR, N below 40, or signal entirely in the pre-file run-up.
- Applied impact is always 0. Live recommendations do not change.

## How to run

```bash
python scripts/run_sc13d_shadow.py --fixture
python scripts/run_sc13d_shadow.py --corpus path/to/filings.json
```

Results are written under the local `sc13d_cache` directory as a shadow log and `last_experiment.json`. They never enter the live ranking path.
