from application.kronos_forecast_service import _trade_level_diagnostics


def _payload() -> dict:
    return {
        "bands": {
            "p10": [98.0, 97.0, 99.0],
            "p50": [101.0, 103.0, 105.0],
            "p90": [104.0, 108.0, 112.0],
        }
    }


def test_trade_level_diagnostics_reports_aligned_bracket():
    result = _trade_level_diagnostics(
        _payload(),
        entry_price=100.0,
        stop_loss_price=95.0,
        target_price=110.0,
    )

    assert result["status"] == "aligned"
    assert result["stop_breach_in_p10"] is False
    assert result["target_reached_by_p90"] is True
    assert result["median_horizon_return_pct"] == 5.0


def test_trade_level_diagnostics_reports_quantile_conflict():
    result = _trade_level_diagnostics(
        _payload(),
        entry_price=100.0,
        stop_loss_price=98.0,
        target_price=115.0,
    )

    assert result["status"] == "conflict"
    assert result["stop_breach_in_p10"] is True
    assert result["target_reached_by_p90"] is False


def test_trade_level_diagnostics_requires_complete_levels():
    assert _trade_level_diagnostics(
        _payload(),
        entry_price=100.0,
        stop_loss_price=None,
        target_price=110.0,
    ) is None
