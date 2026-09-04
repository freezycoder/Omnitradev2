from __future__ import annotations

from datetime import date

from providers.events import sec_edgar_client


def test_sec_edgar_classifies_material_event_and_open_market_purchase(monkeypatch):
    filing_date = date.today().isoformat()
    submissions = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
                "filingDate": [filing_date, filing_date],
                "reportDate": [filing_date, filing_date],
                "form": ["8-K", "4"],
                "primaryDocument": ["event.htm", "ownership.xml"],
                "items": ["1.01", ""],
            }
        }
    }

    def fake_json(url, **kwargs):
        if url.endswith("company_tickers.json"):
            return {"0": {"ticker": "AAPL", "cik_str": 320193}}
        return submissions

    form4_xml = b"""
    <ownershipDocument>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>1000</value></transactionShares>
            <transactionPricePerShare><value>250</value></transactionPricePerShare>
            <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
          </transactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>
    """
    monkeypatch.setattr(sec_edgar_client, "_request_json", fake_json)
    monkeypatch.setattr(sec_edgar_client, "_request_bytes", lambda *args, **kwargs: form4_xml)

    bundle = sec_edgar_client.SecEdgarClient(user_agent="OmniTrade test@example.com").get_company_events("AAPL")

    assert bundle.status == "available"
    assert bundle.cik == "0000320193"
    assert {event.category for event in bundle.events} >= {"material_agreement", "insider_purchase"}
    purchase = next(event for event in bundle.events if event.category == "insider_purchase")
    assert purchase.direction == 1
    assert purchase.transaction_value == 250_000


def test_sec_edgar_reports_not_applicable_when_ticker_has_no_cik(monkeypatch):
    monkeypatch.setattr(sec_edgar_client, "_request_json", lambda *args, **kwargs: {})

    bundle = sec_edgar_client.SecEdgarClient(user_agent="OmniTrade test@example.com").get_company_events("NOSEC")

    assert bundle.status == "not_applicable"
    assert bundle.events == []
