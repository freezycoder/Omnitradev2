from __future__ import annotations

import pandas as pd

from config.market_breadth import (
    EQUAL_WEIGHT_PROXY_LABEL,
    GATE_AD_DIVERGENCE_SESSIONS,
    GATE_PCT_ABOVE_50DMA_MIN,
    RSP_SYMBOL,
)
from domain.scoring.market_breadth import (
    build_breadth_panel,
    build_market_breadth_view,
    evaluate_gate,
)


def _ohlcv(values: list[float], volume: float = 1_000_000, start: str = "2023-01-02") -> pd.DataFrame:
    index = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame(
        {
            "Open": values,
            "High": [value * 1.01 for value in values],
            "Low": [value * 0.99 for value in values],
            "Close": values,
            "Volume": [volume] * len(values),
        },
        index=index,
    )


def _rising(start: float, increment: float, periods: int) -> list[float]:
    return [start + increment * index for index in range(periods)]


def test_evaluate_gate_opens_only_on_frozen_participation_and_confirmation():
    opened = evaluate_gate(
        pct_above_50dma=60.0,
        coverage_50dma=0.95,
        spy_return_nd=1.2,
        ad_line_change_nd=8.0,
    )
    closed_participation = evaluate_gate(
        pct_above_50dma=40.0,
        coverage_50dma=0.95,
        spy_return_nd=1.2,
        ad_line_change_nd=8.0,
    )
    closed_divergence = evaluate_gate(
        pct_above_50dma=80.0,
        coverage_50dma=0.95,
        spy_return_nd=1.2,
        ad_line_change_nd=-4.0,
    )
    unknown_coverage = evaluate_gate(
        pct_above_50dma=80.0,
        coverage_50dma=0.50,
        spy_return_nd=1.2,
        ad_line_change_nd=8.0,
    )

    assert opened.status == "open"
    assert closed_participation.status == "closed"
    assert closed_divergence.status == "closed"
    assert unknown_coverage.status == "unknown"
    assert GATE_PCT_ABOVE_50DMA_MIN == 55.0
    assert GATE_AD_DIVERGENCE_SESSIONS == 10


def test_panel_counts_advances_declines_and_up_down_volume():
    periods = 260
    rising = _rising(100, 0.4, periods)
    falling = _rising(100, -0.3, periods)
    histories = {
        "UP1": _ohlcv(rising, volume=2_000_000),
        "UP2": _ohlcv(rising, volume=2_000_000),
        "DN1": _ohlcv(falling, volume=500_000),
        "DN2": _ohlcv(falling, volume=500_000),
    }
    spy = _ohlcv(_rising(400, 0.2, periods))

    panel = build_breadth_panel(histories, spy, universe=list(histories))
    latest = panel.rows[-1]

    assert latest.advances == 2
    assert latest.declines == 2
    assert latest.up_down_volume_ratio == 4.0
    assert latest.pct_above_50dma == 50.0
    assert latest.coverage_50dma == 1.0
    assert latest.coverage_200dma == 1.0
    assert panel.cap_vs_equal_weight_proxy == EQUAL_WEIGHT_PROXY_LABEL
    assert panel.rsp_available is False


def test_panel_uses_rsp_when_history_is_supplied():
    periods = 260
    histories = {f"T{index}": _ohlcv(_rising(50 + index, 0.2, periods)) for index in range(8)}
    spy = _ohlcv(_rising(400, 0.15, periods))
    rsp = _ohlcv(_rising(150, 0.25, periods))

    panel = build_breadth_panel(histories, spy, universe=list(histories), rsp_history=rsp)

    assert panel.rsp_available is True
    assert panel.cap_vs_equal_weight_proxy == RSP_SYMBOL
    assert panel.rows[-1].rsp_return_pct is not None
    assert panel.rows[-1].spy_minus_rsp_pct is not None


def test_gate_closes_when_spy_rises_and_ad_line_falls():
    periods = 260
    names = {f"T{index}": _ohlcv(_rising(80, 0.5, periods)) for index in range(10)}
    spy_values = _rising(400, 0.2, periods)
    # Last 10 sessions: SPY keeps rising, every name reverses lower so A/D turns negative.
    for offset in range(10):
        spy_values[-(offset + 1)] = spy_values[-11] + 0.4 * (10 - offset)
        for history in names.values():
            close = list(history["Close"])
            close[-(offset + 1)] = close[-11] - 0.8 * (10 - offset)
            history["Close"] = close
            history["Open"] = close
            history["High"] = [value * 1.01 for value in close]
            history["Low"] = [value * 0.99 for value in close]
    panel = build_breadth_panel(names, _ohlcv(spy_values), universe=list(names))
    latest = panel.rows[-1]

    assert latest.spy_return_nd is not None and latest.spy_return_nd > 0
    assert latest.ad_line_change_nd is not None and latest.ad_line_change_nd < 0
    assert latest.gate.status == "closed"


def test_short_history_aborts_200dma_coverage_and_keeps_applied_impact_zero():
    periods = 120
    histories = {f"T{index}": _ohlcv(_rising(100, 0.1, periods)) for index in range(6)}
    spy = _ohlcv(_rising(400, 0.1, periods))
    panel = build_breadth_panel(histories, spy, universe=list(histories))
    view = build_market_breadth_view(panel)

    assert panel.coverage["meets_minimum_coverage"] is False
    assert any("200 DMA" in reason for reason in panel.abort_reasons)
    assert view.mode == "shadow"
    assert view.applied_impact == 0


def test_new_highs_are_secondary_and_not_part_of_the_gate():
    periods = 260
    histories = {f"T{index}": _ohlcv(_rising(100, 0.3, periods)) for index in range(6)}
    spy = _ohlcv(_rising(400, 0.2, periods))
    panel = build_breadth_panel(histories, spy, universe=list(histories))
    latest = panel.rows[-1]

    assert latest.new_highs_252 == 6
    assert latest.new_lows_252 == 0
    assert "new_highs" not in " ".join(latest.gate.reasons)
    assert latest.gate.status in {"open", "closed", "unknown"}
