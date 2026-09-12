from config.etf import DEFAULT_ETF_UNIVERSE, ETF_OMNISCORE_WEIGHTS
import pytest


def test_etf_universe_is_deduped_and_includes_core_liquid_funds():
    assert "QQQ" in DEFAULT_ETF_UNIVERSE
    assert "SPY" in DEFAULT_ETF_UNIVERSE
    assert "SMH" in DEFAULT_ETF_UNIVERSE
    assert len(DEFAULT_ETF_UNIVERSE) == len(set(DEFAULT_ETF_UNIVERSE))


def test_omniscore_weights_are_positive():
    total = (
        ETF_OMNISCORE_WEIGHTS.momentum
        + ETF_OMNISCORE_WEIGHTS.risk
        + ETF_OMNISCORE_WEIGHTS.liquidity
        + ETF_OMNISCORE_WEIGHTS.fund_quality
        + ETF_OMNISCORE_WEIGHTS.flows
        + ETF_OMNISCORE_WEIGHTS.underlying_exposure
    )
    assert total == pytest.approx(1.0)
