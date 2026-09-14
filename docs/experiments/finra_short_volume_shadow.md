# FINRA CNMS short-volume shadow experiment

Pre-registered 2026-09-14. Shadow-only. Isolated branch. Do not deploy or merge without human approval.

## Hypothesis

Daily `short_ratio = ShortVolume / TotalVolume` (and `exempt_share = ShortExemptVolume / TotalVolume`) from FINRA Reg SHO `CNMSshvol` is a calibratable shadow microstructure factor distinct from bi-monthly short interest, with measurable association to forward returns or volatility after volume/liquidity controls.

## Falsifier

The ratio (and exempt share) has no walk-forward predictive content for the pre-registered targets after those controls, the effect is not interpretable once exchange short volume is acknowledged missing, history depth is insufficient for the registered design, or commercial ToU blocks the intended use without approval.

## Primary definition

- One ratio: `ShortVolume / TotalVolume` from CNMS. Missing when `TotalVolume <= 0`.
- Secondary, reported only: `exempt_share`. Not used for post-hoc percentile thresholds.
- Provenance: `FINRA_OFF_EXCHANGE`.
- Exchange short volume is permanently documented as absent.

## Targets

- Primary: 5-session excess return versus SPY
- Secondary: 1d / 20d excess return, and 1d / 5d / 20d absolute return

## Controls

Fit on each training fold only, then apply out of sample:

- `log1p(share volume)` from price history
- `log1p(dollar volume)`
- 20-session Amihud illiquidity

Do not use FINRA `TotalVolume` as a control. Do not invent a short-interest feature; compare only if one already exists (none does).

## Walk-forward

- 3 expanding folds
- 5 calendar-day embargo
- Daily cross-sectional Spearman IC of residualized `short_ratio` versus the target
- Newey-West t-stat with lag equal to the horizon
- Significance: two-sided p < 0.05

## Data gate

FAIL as `data_blocked` if FINRA CNMS history has fewer than 180 sessions or fewer than 3 eligible folds (each fold needs at least 20 OOS dates and 8 names in a cross-section).

## Success / failure

- SUCCESS: primary target significant in at least 2 of 3 eligible folds, schema/UI distinguish short volume from short interest, ToU review recorded.
- FAIL: no signal after controls, or history too short, or commercial ToU blocks intended shipping use without approval.

## Overfitting mitigations

- No post-hoc ratio percentile thresholds
- Do not treat market-maker hedging as directional shorting
- Do not combine with short interest
- Keep the facility-coverage caveat permanent
