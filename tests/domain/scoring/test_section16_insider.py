from __future__ import annotations

from domain.scoring.section16_insider import (
    build_section16_insider_view,
    build_unavailable_section16_insider_view,
)
from providers.events.section16_models import InsiderTransaction


def test_unavailable_view_is_shadow_with_zero_applied_impact():
    view = build_unavailable_section16_insider_view("No rows.")
    assert view.mode == "shadow"
    assert view.applied_impact == 0
    assert view.score is None
    assert view.coverage_score == 0


def test_stale_quarterly_zip_sets_freshness_warning():
    row = InsiderTransaction(
        accession_number="1",
        ticker="AAA",
        issuer_cik="1",
        issuer_name="AAA",
        owner_cik="1",
        owner_name="One",
        owner_title=None,
        is_director=True,
        is_officer=False,
        is_ten_percent_owner=False,
        transaction_date="2024-01-02",
        filed_at="2024-01-02",
        transaction_code="P",
        acquired_disposed="A",
        shares=100.0,
        price_per_share=10.0,
        value_usd=1000.0,
        is_10b5_1=False,
        is_derivative=False,
        source="sec_quarterly_zip",
    )
    view = build_section16_insider_view(
        ticker="AAA",
        transactions=[row],
        as_of="2024-06-01",
        freshness_source="sec_quarterly_zip",
    )
    assert view.stale_vs_sla is True
    assert view.applied_impact == 0
    assert any("SLA" in warning for warning in view.warnings)
