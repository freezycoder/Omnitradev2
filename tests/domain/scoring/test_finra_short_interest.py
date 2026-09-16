from __future__ import annotations

from datetime import date

from domain.research.lifecycle import EXPERIMENT_FINRA_SHORT_INTEREST, LifecycleLabel
from domain.scoring.finra_short_interest import (
    build_finra_short_interest_view,
    finra_short_interest_view_from_dict,
    frozen_delta_high,
    frozen_dtc_elevated,
)
from providers.market.finra_short_interest_client import parse_short_interest_record


def _row(**overrides):
    payload = {
        "symbolCode": "MSFT",
        "currentShortPositionQuantity": 50_000_000,
        "previousShortPositionQuantity": 40_000_000,
        "changePercent": 25.0,
        "daysToCoverQuantity": 6.0,
        "settlementDate": "2026-07-31",
    }
    payload.update(overrides)
    parsed = parse_short_interest_record(payload)
    assert parsed is not None
    return parsed


def test_shadow_view_uses_publication_date_and_frozen_gates():
    view = build_finra_short_interest_view(_row())

    assert view.mode == "shadow"
    assert view.applied_impact == 0
    assert view.lifecycle_label == LifecycleLabel.UNVERIFIED.value
    assert view.experiment_ids == (EXPERIMENT_FINRA_SHORT_INTEREST,)
    assert view.event_date == date(2026, 8, 11).isoformat()
    assert view.settlement_date == date(2026, 7, 31).isoformat()
    assert view.event_date != view.settlement_date
    assert view.pct_float is None
    assert view.pct_float_status == "deferred"
    assert view.delta_high is True
    assert view.dtc_elevated is True
    assert view.dtc_high is False
    assert view.squeeze_narrative is False
    assert view.not_short_volume is True
    assert "squeeze" not in view.summary.lower()


def test_frozen_thresholds_are_not_shopped_at_eval():
    assert frozen_delta_high(19.99) is False
    assert frozen_delta_high(20.0) is True
    assert frozen_dtc_elevated(4.99) is False
    assert frozen_dtc_elevated(5.0) is True


def test_cache_rebuild_discards_spoofed_live_fields_and_pct_float():
    payload = build_finra_short_interest_view(_row()).to_dict()
    payload["applied_impact"] = 9
    payload["lifecycle_label"] = "REAL"
    payload["pct_float"] = 0.42
    payload["squeeze_narrative"] = True
    restored = finra_short_interest_view_from_dict(payload)

    assert restored.applied_impact == 0
    assert restored.lifecycle_label == LifecycleLabel.UNVERIFIED.value
    assert restored.pct_float is None
    assert restored.pct_float_status == "deferred"
    assert restored.squeeze_narrative is False
