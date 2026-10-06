from __future__ import annotations

from datetime import date
from pathlib import Path

from config.stfm_funding_liquidity import (
    ANFCI_INGEST_V1,
    FROZEN_MNEMONICS,
    HY_KEEP_FROZEN_ON,
    HY_KEEP_RECIPE_VERSION,
    HY_KEEP_SOURCE_BRANCH,
    HY_OAS_SERIES_ID,
    HY_VELOCITY_WIDENING_BP,
    IG_OAS_SERIES_ID,
    MNEMONIC_DVP_VOLUME,
    MNEMONIC_EFFR,
    MNEMONIC_GCF_VOLUME,
    MNEMONIC_MMF_TOTAL,
    MNEMONIC_SOFR,
    NFCI_KEEP_FROZEN_ON,
    NFCI_KEEP_RECIPE_VERSION,
    NFCI_KEEP_SOURCE_BRANCH,
    NFCI_SERIES_ID,
    RORO_INGEST_V1,
    SOFR_EFFR_WIDEN_BP,
    STFM_MODE,
    STFM_RECIPE_FROZEN_ON,
    STFM_RECIPE_VERSION,
    THROTTLE_WEIGHT,
    VOLUME_ZSCORE_DROP,
    hy_keep_recipe_manifest,
    nfci_keep_recipe_manifest,
    stfm_recipe_manifest,
)
from providers.macro.fred_client import FRED_SERIES


def test_frozen_stfm_recipe_is_not_available_for_tuning():
    manifest = stfm_recipe_manifest()

    assert STFM_RECIPE_VERSION == "stfm-gate-v1"
    assert STFM_RECIPE_FROZEN_ON == "2026-09-17"
    assert STFM_MODE == "shadow"
    assert FROZEN_MNEMONICS == (
        MNEMONIC_DVP_VOLUME,
        MNEMONIC_GCF_VOLUME,
        MNEMONIC_MMF_TOTAL,
        MNEMONIC_SOFR,
        MNEMONIC_EFFR,
    )
    assert MNEMONIC_DVP_VOLUME == "REPO-DVP_TV_TOT-P"
    assert MNEMONIC_GCF_VOLUME == "REPO-GCF_TV_TOT-P"
    assert MNEMONIC_MMF_TOTAL == "MMF-MMF_TOT-M"
    assert MNEMONIC_SOFR == "FNYR-SOFR-A"
    assert MNEMONIC_EFFR == "FNYR-EFFR-A"
    assert VOLUME_ZSCORE_DROP == -1.0
    assert SOFR_EFFR_WIDEN_BP == 3.0
    assert THROTTLE_WEIGHT == 0.50
    assert manifest["frozen"] is True
    assert manifest["do_not_tune"] is True
    assert manifest["mnemonic_shopping"] is False
    assert manifest["is_stock_picker"] is False
    assert manifest["live_recommendation_changes"] is False
    assert manifest["applied_impact"] == 0
    assert manifest["gate"]["mmf_in_gate"] is False
    assert manifest["sofr_only_control"]["volumes_in_gate"] is False
    assert manifest["alignment"]["join_on"] == "release_date"
    assert date.fromisoformat(STFM_RECIPE_FROZEN_ON) <= date(2026, 9, 17)


def test_hy_and_nfci_keep_comparators_are_discovered_not_invented():
    hy = hy_keep_recipe_manifest()
    nfci = nfci_keep_recipe_manifest()

    assert HY_KEEP_RECIPE_VERSION == "credit-gate-v1"
    assert HY_KEEP_FROZEN_ON == "2026-09-15"
    assert HY_KEEP_SOURCE_BRANCH == "cursor/shadow-credit-hy-oas-regime-6c9c"
    assert hy["invented_on_this_branch"] is False
    assert HY_OAS_SERIES_ID == "BAMLH0A0HYM2"
    assert IG_OAS_SERIES_ID == "BAMLC0A0CM"
    assert HY_VELOCITY_WIDENING_BP == 30.0
    assert hy["gate"]["hy_ig_gap_in_gate"] is False

    assert NFCI_KEEP_RECIPE_VERSION == "nfci-gate-v1"
    assert NFCI_KEEP_FROZEN_ON == "2026-09-16"
    assert NFCI_KEEP_SOURCE_BRANCH == "cursor/shadow-nfci-regime-gate-0e2b"
    assert nfci["invented_on_this_branch"] is False
    assert NFCI_SERIES_ID == "NFCI"
    assert ANFCI_INGEST_V1 is False
    assert nfci["gate"]["anfci_in_gate"] is False


def test_roro_is_discovered_absent_and_not_invented():
    manifest = stfm_recipe_manifest()
    assert RORO_INGEST_V1 is False
    assert manifest["roro"]["discovered"] is False
    assert manifest["roro"]["invented_on_this_branch"] is False
    assert manifest["roro"]["ingest_v1"] is False


def test_live_fred_overlay_does_not_gain_stfm_or_ig_or_anfci():
    assert FRED_SERIES["financial_conditions"]["series_id"] == "NFCI"
    assert FRED_SERIES["high_yield_spread"]["series_id"] == HY_OAS_SERIES_ID
    assert all(item["series_id"] != "ANFCI" for item in FRED_SERIES.values())
    assert all(item["series_id"] != IG_OAS_SERIES_ID for item in FRED_SERIES.values())
    assert all("REPO-" not in item["series_id"] for item in FRED_SERIES.values())


def test_stfm_gate_is_not_imported_by_live_recommendation_modules():
    root = Path(__file__).resolve().parents[2]
    live_paths = [
        root / "application" / "ticker_service.py",
        root / "application" / "scan_service.py",
        root / "domain" / "recommendations" / "engine.py",
        root / "api" / "main.py",
    ]
    for path in live_paths:
        text = path.read_text(encoding="utf-8")
        assert "stfm_funding_liquidity" not in text
        assert "OfrStfmClient" not in text
        assert "stfm-gate-v1" not in text
