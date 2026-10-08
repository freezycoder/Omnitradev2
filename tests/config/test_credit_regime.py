from __future__ import annotations

from datetime import date

from config.credit_regime import (
    CREDIT_MODE,
    CREDIT_RECIPE_FROZEN_ON,
    CREDIT_RECIPE_VERSION,
    HY_OAS_SERIES_ID,
    ICE_REDISTRIBUTION_NOTICE,
    IG_OAS_SERIES_ID,
    PERCENTILE_THROTTLE,
    PERCENTILE_WINDOW_SESSIONS,
    THROTTLE_WEIGHT,
    VELOCITY_WIDENING_BP,
    VELOCITY_WINDOW_SESSIONS,
    credit_recipe_manifest,
)
from providers.macro.fred_client import FRED_SERIES


def test_frozen_throttle_recipe_is_not_available_for_tuning():
    manifest = credit_recipe_manifest()

    assert CREDIT_RECIPE_VERSION == "credit-gate-v1"
    assert CREDIT_RECIPE_FROZEN_ON == "2026-09-15"
    assert CREDIT_MODE == "shadow"
    assert VELOCITY_WINDOW_SESSIONS == 20
    assert VELOCITY_WIDENING_BP == 30.0
    assert PERCENTILE_WINDOW_SESSIONS == 252
    assert PERCENTILE_THROTTLE == 80.0
    assert THROTTLE_WEIGHT == 0.50
    assert HY_OAS_SERIES_ID == "BAMLH0A0HYM2"
    assert IG_OAS_SERIES_ID == "BAMLC0A0CM"
    assert manifest["frozen"] is True
    assert manifest["do_not_tune"] is True
    assert manifest["is_stock_picker"] is False
    assert manifest["live_recommendation_changes"] is False
    assert manifest["applied_impact"] == 0
    assert manifest["gate"]["hy_ig_gap_in_gate"] is False
    assert manifest["gate"]["weekly_delta_in_gate"] is False
    assert date.fromisoformat(CREDIT_RECIPE_FROZEN_ON) <= date(2026, 9, 15)
    assert "ICE Data Indices" in ICE_REDISTRIBUTION_NOTICE
    assert "productize" in ICE_REDISTRIBUTION_NOTICE


def test_live_fred_overlay_does_not_gain_the_ig_companion_series():
    assert FRED_SERIES["high_yield_spread"]["series_id"] == "BAMLH0A0HYM2"
    assert "ig_oas" not in FRED_SERIES
    assert all(item["series_id"] != "BAMLC0A0CM" for item in FRED_SERIES.values())


def test_credit_gate_is_not_imported_by_live_recommendation_modules():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    live_paths = [
        root / "application" / "ticker_service.py",
        root / "application" / "scan_service.py",
        root / "domain" / "recommendations" / "engine.py",
        root / "api" / "main.py",
    ]
    for path in live_paths:
        text = path.read_text(encoding="utf-8")
        assert "credit_regime" not in text
        assert "CreditOasClient" not in text
        assert "credit-gate-v1" not in text
