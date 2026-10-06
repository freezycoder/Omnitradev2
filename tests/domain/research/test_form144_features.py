from __future__ import annotations

from config.form144 import CLUSTER_MIN_AFFILIATES
from domain.research.form144_features import detect_clusters, eligible_notices
from domain.research.form144_fixture import aligned_form144_inputs
from providers.events.form144_models import ProposedSaleNotice


def test_pre_mandate_notices_are_dropped() -> None:
    notice = ProposedSaleNotice(
        accession_number="old",
        ticker="AAA",
        issuer_cik="0000320193",
        issuer_name="Issuer",
        filer_cik="0001000001",
        filer_name="Filer",
        relationship="Officer",
        filed_at="2022-01-01",
        approx_sale_date="2022-01-02",
        proposed_units=1000.0,
        aggregate_market_value=None,
        broker=None,
        prior_3m_units=None,
        prior_3m_proceeds=None,
        securities_class=None,
        source="fixture",
    )
    assert eligible_notices([notice]) == []


def test_two_affiliates_do_not_cluster() -> None:
    notices, _sales, _panel = aligned_form144_inputs(mode="lead")
    two = [row for row in notices if row.filer_cik in {"0001000001", "0001000002"}]
    assert detect_clusters(two) == []
    assert CLUSTER_MIN_AFFILIATES == 3
