from __future__ import annotations

from domain.etf.exposure import reverse_etf_exposure, thematic_exposure_score
from domain.etf.models import EtfHolding, EtfProfile


def test_reverse_exposure_filters_by_min_weight():
    holdings = [
        EtfHolding("SMH", "NVDA", "NVIDIA", 0.20),
        EtfHolding("QQQ", "NVDA", "NVIDIA", 0.003),
        EtfHolding("SPY", "AAPL", "Apple", 0.07),
    ]
    profiles = {
        "SMH": EtfProfile(ticker="SMH", name="Semis", aum=10.0, expense_ratio=0.0035),
        "QQQ": EtfProfile(ticker="QQQ", name="Nasdaq", aum=200.0, expense_ratio=0.002),
    }

    rows = reverse_etf_exposure("NVDA", holdings, profiles, min_weight=0.005)

    assert [row.etf_ticker for row in rows] == ["SMH"]
    assert rows[0].weight == 0.20


def test_thematic_exposure_ignores_missing_stock_scores():
    holdings = [
        EtfHolding("SMH", "NVDA", "NVIDIA", 0.50),
        EtfHolding("SMH", "AVGO", "Broadcom", 0.20),
        EtfHolding("SMH", "TSM", "TSMC", 0.10),
    ]

    score, coverage, contributors = thematic_exposure_score(holdings, {"NVDA": 80.0, "AVGO": 60.0})

    assert coverage == 0.70
    assert score == (80.0 * 0.50 + 60.0 * 0.20) / 0.70
    assert [item.ticker for item in contributors] == ["NVDA", "AVGO"]
