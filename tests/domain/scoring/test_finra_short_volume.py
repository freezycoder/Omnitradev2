from __future__ import annotations

from datetime import date

from domain.scoring.finra_short_volume import (
    LEGAL_GATE,
    build_finra_short_volume_view,
    build_unavailable_finra_short_volume_view,
    finra_short_volume_view_from_dict,
)
from providers.market.finra_short_volume_client import FinraShortVolumeRow


def _row() -> FinraShortVolumeRow:
    return FinraShortVolumeRow(
        as_of_date=date(2026, 9, 11),
        symbol="AAPL",
        short_volume=1_000.0,
        short_exempt_volume=25.0,
        total_volume=4_000.0,
        market="B,Q,N",
    )


def test_short_volume_view_never_changes_live_score_and_is_not_short_interest():
    view = build_finra_short_volume_view(_row())

    assert view.mode == "shadow"
    assert view.applied_impact == 0
    assert view.short_ratio == 0.25
    assert view.exempt_share == 0.00625
    assert view.feature_family == "short_volume"
    assert view.not_short_interest is True
    assert view.provenance == "FINRA_OFF_EXCHANGE"
    assert view.exchange_short_volume_included is False
    assert view.short_interest_feature_present is False
    assert view.legal_gate["commercial_use_allowed"] is False
    assert view.legal_gate["shipping_allowed"] is False
    assert "not bi-monthly short interest" in " ".join(view.evidence).lower()


def test_unavailable_view_keeps_coverage_caveat_and_zero_applied_impact():
    view = build_unavailable_finra_short_volume_view("FINRA file missing.")

    assert view.status == "unavailable"
    assert view.applied_impact == 0
    assert view.coverage_score == 0
    assert view.legal_gate == LEGAL_GATE
    assert any("exchange short volume" in item.lower() for item in view.warnings)


def test_cached_finra_view_round_trip_forces_zero_applied_impact():
    view = build_finra_short_volume_view(_row())
    payload = view.to_dict()
    payload["applied_impact"] = 9
    restored = finra_short_volume_view_from_dict(payload)

    assert restored.applied_impact == 0
    assert restored.short_ratio == view.short_ratio
    assert restored.not_short_interest is True
