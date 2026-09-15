from __future__ import annotations

from datetime import date

from providers.events import sc13d_edgar
from providers.events.sc13d_edgar import Sc13dEdgarClient


SAMPLE_13D = b"""
Item 4. Purpose of Transaction
The Reporting Person seeks board representation and may nominate directors.
Item 5. Interest in Securities of the Issuer
Percent of Class Represented by Amount in Row (11) 8.1%
Item 6. Contracts
"""


def test_ingest_ticker_submissions_parses_13d_and_keeps_13g_for_conversion(monkeypatch):
    submissions = {
        "name": "AAA Inc",
        "filings": {
            "recent": {
                "accessionNumber": ["0001-13d", "0001-13g"],
                "filingDate": ["2016-03-01", "2015-06-01"],
                "reportDate": ["2016-03-01", "2015-06-01"],
                "form": ["SC 13D", "SC 13G"],
                "primaryDocument": ["d.htm", "g.htm"],
                "items": ["", ""],
            }
        },
    }

    def fake_json(url, **kwargs):
        if url.endswith("company_tickers.json"):
            return {"0": {"ticker": "AAA", "cik_str": 1}}
        return submissions

    monkeypatch.setattr(sc13d_edgar, "_request_json", fake_json)
    monkeypatch.setattr(sc13d_edgar, "_request_bytes", lambda *args, **kwargs: SAMPLE_13D)

    payload = Sc13dEdgarClient(user_agent="OmniTrade test@example.com").ingest_ticker_submissions(
        ["AAA"],
        since=date(2009, 1, 1),
    )
    assert len(payload["sc13d"]) == 1
    assert payload["sc13d"][0].ticker == "AAA"
    assert payload["sc13d"][0].percent_of_class == 8.1
    assert "board representation" in payload["sc13d"][0].purpose_text.lower()
    assert len(payload["sc13g"]) == 1
    assert payload["sc13g"][0].form == "SC 13G"
