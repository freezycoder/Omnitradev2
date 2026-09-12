from __future__ import annotations

from domain.etf.normalization import infer_percent_scale, normalize_holdings


def test_normalize_holdings_converts_percent_scale_to_weights():
    snapshot = normalize_holdings(
        "QQQ",
        [
            {"ticker": "AAPL", "name": "Apple", "percent": 10},
            {"ticker": "MSFT", "name": "Microsoft", "percent": 20},
            {"name": "Cash", "percent": 1},
        ],
        source="test",
    )

    weights = {item.holding_ticker: item.weight for item in snapshot.holdings}
    assert weights["AAPL"] == 0.10
    assert weights["MSFT"] == 0.20
    assert all(item.holding_ticker != "CASH" for item in snapshot.holdings)


def test_normalize_holdings_keeps_fractional_weights():
    snapshot = normalize_holdings(
        "SPY",
        [
            {"symbol": "AAPL", "name": "Apple", "weight": 0.07},
            {"symbol": "MSFT", "name": "Microsoft", "weight": 0.06},
        ],
        source="test",
    )

    assert snapshot.holdings[0].weight == 0.07
    assert infer_percent_scale([0.07, 0.06]) is False
