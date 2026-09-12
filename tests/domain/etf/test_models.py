from __future__ import annotations

from domain.etf.models import EtfProfile, optional_float, optional_int, optional_str


def test_optional_float_keeps_zero_and_rejects_unknown():
    assert optional_float(0) == 0.0
    assert optional_float("0") == 0.0
    assert optional_float(None) is None
    assert optional_float("") is None
    assert optional_float("not-a-number") is None
    assert optional_float(float("nan")) is None
    assert optional_float(float("inf")) is None


def test_optional_helpers_do_not_invent_values():
    assert optional_int(None) is None
    assert optional_int(3.9) == 3
    assert optional_str("  ") is None
    assert optional_str("Invesco") == "Invesco"


def test_as_fraction_converts_percent_scale_without_zeroing_unknown():
    from domain.etf.models import as_fraction

    assert as_fraction(None) is None
    assert as_fraction(0.002, percent_if_above=0.02) == 0.002
    assert as_fraction(0.03, percent_if_above=0.02) == 0.0003
    assert as_fraction(0.18, percent_if_above=0.02) == 0.0018
    assert as_fraction(0.20, percent_if_above=0.02) == 0.002
    assert as_fraction(18) == 0.18
    assert as_fraction(0, percent_if_above=0.05) == 0.0


def test_etf_profile_tracks_unavailable_fields_without_zero_fill():
    profile = EtfProfile(ticker="QQQ", expense_ratio=0.002, aum=None, unavailable_fields=("aum", "dividend_yield"))
    payload = profile.to_dict()

    assert payload["expense_ratio"] == 0.002
    assert payload["aum"] is None
    assert payload["dividend_yield"] is None
    assert "aum" in payload["unavailable_fields"]
