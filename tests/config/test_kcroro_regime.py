from __future__ import annotations

from datetime import date
from pathlib import Path

from config.kcroro_regime import (
    HY_KEEP_FROZEN_ON,
    HY_KEEP_RECIPE_VERSION,
    HY_KEEP_SOURCE_BRANCH,
    HY_OAS_SERIES_ID,
    HY_VELOCITY_WIDENING_BP,
    IG_OAS_SERIES_ID,
    KCRORO_EQUITY_SERIES_ID,
    KCRORO_FXGOLD_SERIES_ID,
    KCRORO_LIQUIDITY_SERIES_ID,
    KCRORO_MODE,
    KCRORO_RECIPE_FROZEN_ON,
    KCRORO_RECIPE_VERSION,
    KCRORO_SERIES_ID,
    KCRORO_SPREADS_SERIES_ID,
    LEVEL_THROTTLE,
    NFCI_KEEP_FROZEN_ON,
    NFCI_KEEP_RECIPE_VERSION,
    NFCI_KEEP_SOURCE_BRANCH,
    NFCI_PERSISTENCE_WEEKS,
    NFCI_SERIES_ID,
    RELEASE_LAG_CALENDAR_DAYS,
    SHOCK_SUM_THROTTLE,
    SHOCK_SUM_WINDOW_SESSIONS,
    THROTTLE_WEIGHT,
    hy_keep_recipe_manifest,
    kcroro_recipe_manifest,
    nfci_keep_recipe_manifest,
)
from providers.macro.fred_client import FRED_SERIES


def test_frozen_kcroro_recipe_is_not_available_for_tuning():
    manifest = kcroro_recipe_manifest()

    assert KCRORO_RECIPE_VERSION == "kcroro-gate-v1"
    assert KCRORO_RECIPE_FROZEN_ON == "2026-09-17"
    assert KCRORO_MODE == "shadow"
    assert KCRORO_SERIES_ID == "KCRORO"
    assert KCRORO_SPREADS_SERIES_ID == "KCROROS"
    assert KCRORO_EQUITY_SERIES_ID == "KCROROE"
    assert KCRORO_LIQUIDITY_SERIES_ID == "KCROROL"
    assert KCRORO_FXGOLD_SERIES_ID == "KCROROG"
    assert LEVEL_THROTTLE == 0.0
    assert SHOCK_SUM_WINDOW_SESSIONS == 20
    assert SHOCK_SUM_THROTTLE == 0.0
    assert THROTTLE_WEIGHT == 0.50
    assert RELEASE_LAG_CALENDAR_DAYS == 1
    assert manifest["frozen"] is True
    assert manifest["do_not_tune"] is True
    assert manifest["is_stock_picker"] is False
    assert manifest["live_recommendation_changes"] is False
    assert manifest["applied_impact"] == 0
    assert manifest["gate"]["subindexes_in_gate"] is False
    assert manifest["gate"]["equity_subindex_in_gate"] is False
    assert manifest["alignment"]["join_on"] == "release_date"
    assert manifest["alignment"]["verified_example"]["observation_date"] == "2026-09-08"
    assert manifest["alignment"]["verified_example"]["kcroro"] == 0.1814
    assert manifest["alignment"]["verified_example"]["fallback_release_date"] == "2026-09-09"
    assert date.fromisoformat(KCRORO_RECIPE_FROZEN_ON) <= date(2026, 9, 17)
    assert "Chari" in manifest["citation"]["text"]
    assert "24-12" in manifest["citation"]["text"]


def test_hy_oas_keep_comparator_is_discovered_not_invented():
    keep = hy_keep_recipe_manifest()

    assert HY_KEEP_RECIPE_VERSION == "credit-gate-v1"
    assert HY_KEEP_FROZEN_ON == "2026-09-15"
    assert HY_KEEP_SOURCE_BRANCH == "cursor/shadow-credit-hy-oas-regime-6c9c"
    assert keep["invented_on_this_branch"] is False
    assert HY_OAS_SERIES_ID == "BAMLH0A0HYM2"
    assert IG_OAS_SERIES_ID == "BAMLC0A0CM"
    assert HY_VELOCITY_WIDENING_BP == 30.0
    assert keep["gate"]["hy_ig_gap_in_gate"] is False


def test_nfci_keep_comparator_is_discovered_not_invented():
    keep = nfci_keep_recipe_manifest()

    assert NFCI_KEEP_RECIPE_VERSION == "nfci-gate-v1"
    assert NFCI_KEEP_FROZEN_ON == "2026-09-16"
    assert NFCI_KEEP_SOURCE_BRANCH == "cursor/shadow-nfci-regime-gate-0e2b"
    assert keep["invented_on_this_branch"] is False
    assert NFCI_SERIES_ID == "NFCI"
    assert NFCI_PERSISTENCE_WEEKS == 3
    assert keep["series"]["anfci_in_v1"] is False


def test_live_fred_overlay_does_not_gain_kcroro_or_ig():
    assert FRED_SERIES["financial_conditions"]["series_id"] == "NFCI"
    assert FRED_SERIES["high_yield_spread"]["series_id"] == HY_OAS_SERIES_ID
    assert all(item["series_id"] != KCRORO_SERIES_ID for item in FRED_SERIES.values())
    assert all(item["series_id"] != IG_OAS_SERIES_ID for item in FRED_SERIES.values())
    assert all(item["series_id"] != "ANFCI" for item in FRED_SERIES.values())


def test_kcroro_gate_is_not_imported_by_live_recommendation_modules():
    root = Path(__file__).resolve().parents[2]
    live_paths = [
        root / "application" / "ticker_service.py",
        root / "application" / "scan_service.py",
        root / "domain" / "recommendations" / "engine.py",
        root / "api" / "main.py",
    ]
    for path in live_paths:
        text = path.read_text(encoding="utf-8")
        assert "kcroro_regime" not in text
        assert "KcroroClient" not in text
        assert "kcroro-gate-v1" not in text
