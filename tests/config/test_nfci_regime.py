from __future__ import annotations

from datetime import date
from pathlib import Path

from config.nfci_regime import (
    ANFCI_INGEST_V1,
    DELTA_WEEKS,
    HY_KEEP_FROZEN_ON,
    HY_KEEP_RECIPE_VERSION,
    HY_KEEP_SOURCE_BRANCH,
    HY_OAS_SERIES_ID,
    HY_VELOCITY_WIDENING_BP,
    IG_OAS_SERIES_ID,
    NFCI_MODE,
    NFCI_RECIPE_FROZEN_ON,
    NFCI_RECIPE_VERSION,
    NFCI_SERIES_ID,
    PERSISTENCE_WEEKS,
    RELEASE_LAG_CALENDAR_DAYS,
    THROTTLE_WEIGHT,
    hy_keep_recipe_manifest,
    nfci_recipe_manifest,
)
from providers.macro.fred_client import FRED_SERIES


def test_frozen_nfci_recipe_is_not_available_for_tuning():
    manifest = nfci_recipe_manifest()

    assert NFCI_RECIPE_VERSION == "nfci-gate-v1"
    assert NFCI_RECIPE_FROZEN_ON == "2026-09-16"
    assert NFCI_MODE == "shadow"
    assert NFCI_SERIES_ID == "NFCI"
    assert ANFCI_INGEST_V1 is False
    assert DELTA_WEEKS == 4
    assert PERSISTENCE_WEEKS == 3
    assert THROTTLE_WEIGHT == 0.50
    assert RELEASE_LAG_CALENDAR_DAYS == 6
    assert manifest["frozen"] is True
    assert manifest["do_not_tune"] is True
    assert manifest["is_stock_picker"] is False
    assert manifest["live_recommendation_changes"] is False
    assert manifest["applied_impact"] == 0
    assert manifest["anfci_ingest_v1"] is False
    assert manifest["gate"]["level_in_gate"] is False
    assert manifest["gate"]["anfci_in_gate"] is False
    assert manifest["alignment"]["join_on"] == "release_date"
    assert manifest["alignment"]["verified_example"]["observation_week_end"] == "2026-09-04"
    assert manifest["alignment"]["verified_example"]["fallback_release_date"] == "2026-09-10"
    assert date.fromisoformat(NFCI_RECIPE_FROZEN_ON) <= date(2026, 9, 16)


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
    assert keep["gate"]["weekly_delta_in_gate"] is False


def test_live_fred_overlay_does_not_gain_anfci_or_ig():
    assert FRED_SERIES["financial_conditions"]["series_id"] == "NFCI"
    assert FRED_SERIES["high_yield_spread"]["series_id"] == HY_OAS_SERIES_ID
    assert all(item["series_id"] != "ANFCI" for item in FRED_SERIES.values())
    assert all(item["series_id"] != IG_OAS_SERIES_ID for item in FRED_SERIES.values())


def test_nfci_gate_is_not_imported_by_live_recommendation_modules():
    root = Path(__file__).resolve().parents[2]
    live_paths = [
        root / "application" / "ticker_service.py",
        root / "application" / "scan_service.py",
        root / "domain" / "recommendations" / "engine.py",
        root / "api" / "main.py",
    ]
    for path in live_paths:
        text = path.read_text(encoding="utf-8")
        assert "nfci_regime" not in text
        assert "NfciClient" not in text
        assert "nfci-gate-v1" not in text
