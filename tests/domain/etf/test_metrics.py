from __future__ import annotations

import pandas as pd

from domain.etf.metrics import build_performance_metrics


def test_metrics_are_none_when_history_is_insufficient():
    history = pd.DataFrame(
        {
            "Open": [10, 11],
            "High": [10, 11],
            "Low": [10, 11],
            "Close": [10, 11],
            "Volume": [1000, 1000],
        },
        index=pd.date_range("2026-01-01", periods=2, freq="B"),
    )

    metrics = build_performance_metrics(history)

    assert metrics.current_price == 11
    assert metrics.annualized_volatility is None
    assert metrics.sharpe_ratio is None
    assert "volatility" in metrics.insufficient_data
    assert "sharpe" in metrics.insufficient_data
