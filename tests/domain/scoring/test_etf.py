from __future__ import annotations

from domain.etf.metrics import EtfPerformanceMetrics
from domain.etf.models import EtfProfile
from domain.scoring.etf import build_etf_omni_score


def test_etf_omni_score_omits_missing_components_instead_of_zeroing_them():
    profile = EtfProfile(ticker="QQQ", average_volume=40_000_000, expense_ratio=0.002, aum=200_000_000_000)
    metrics = EtfPerformanceMetrics(return_1m=5.0, return_3m=8.0, annualized_volatility=18.0, maximum_drawdown=-12.0)

    score = build_etf_omni_score(profile, metrics, holdings=None)

    flows = next(component for component in score.components if component.key == "flows")
    underlying = next(component for component in score.components if component.key == "underlying_exposure")
    assert flows.available is False
    assert flows.score is None
    assert underlying.available is False
    assert score.score is not None
    assert score.predictive is False
    applied = sum(component.applied_weight for component in score.components if component.available)
    assert applied == 1
