from __future__ import annotations

from providers.news.finnhub_client import FinnhubClient, FinnhubResponse


def test_company_earnings_uses_normalized_symbol_and_bounded_limit(monkeypatch):
    client = FinnhubClient(api_key="fixture")
    captured: dict[str, object] = {}

    def fake_request(path, params):
        captured["path"] = path
        captured["params"] = params
        return FinnhubResponse(payload=[])

    monkeypatch.setattr(client, "_request", fake_request)

    response = client.get_company_earnings(" aapl ", limit=50)

    assert response.error is None
    assert captured == {
        "path": "stock/earnings",
        "params": {"symbol": "AAPL", "limit": 12},
    }
