from __future__ import annotations

from domain.research.form144_fixture import FORM144_XML_FIXTURE, FORM4_SALE_XML_FIXTURE
from providers.events.form144_xml import parse_form144_xml
from providers.events.form4_sale_xml import parse_form4_sale_xml


def test_form144_xml_reads_proposed_units_date_broker_and_ciks() -> None:
    notice = parse_form144_xml(
        FORM144_XML_FIXTURE,
        accession_number="0001000001-23-000001",
        filed_at="2023-03-15",
    )
    assert notice.issuer_cik == "0000320193"
    assert notice.filer_cik == "0001000001"
    assert notice.ticker == "AAA"
    assert notice.proposed_units == 12000
    assert notice.approx_sale_date == "2023-03-15"
    assert notice.broker == "Goldman Sachs & Co. LLC"
    assert notice.prior_3m_units == 500
    assert notice.prior_3m_proceeds == 75000
    assert notice.securities_class == "Common Stock"


def test_form4_sale_xml_keeps_open_market_sales_only() -> None:
    sales = parse_form4_sale_xml(
        FORM4_SALE_XML_FIXTURE,
        accession_number="0001000001-23-000002",
        filed_at="2023-03-18",
    )
    assert len(sales) == 1
    assert sales[0].transaction_code == "S"
    assert sales[0].acquired_disposed == "D"
    assert sales[0].filer_cik == "0001000001"
    assert sales[0].shares == 12000
    assert sales[0].value_usd == 1_800_000
