from __future__ import annotations

from providers.macro import fred_client


def test_fred_without_api_key_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setattr(fred_client, "_SNAPSHOT_CACHE", None)

    bundle = fred_client.FredClient(api_key="").get_macro_bundle()

    assert bundle.status == "unavailable"
    assert bundle.series == {}
    assert "FRED_API_KEY" in str(bundle.message)


def test_fred_returns_partial_bundle_without_treating_missing_series_as_neutral(monkeypatch):
    monkeypatch.setattr(fred_client, "_SNAPSHOT_CACHE", None)
    client = fred_client.FredClient(api_key="test")

    def fake_series(key, metadata):
        if key != "yield_curve_10y_2y":
            return None
        return fred_client.FredSeriesSnapshot(
            key=key,
            series_id=metadata["series_id"],
            label=metadata["label"],
            unit=metadata["unit"],
            latest_value=0.75,
            latest_date="2026-07-27",
            prior_value=-0.25,
            prior_date="2026-04-27",
            change=1.0,
        )

    monkeypatch.setattr(client, "_get_series", fake_series)
    bundle = client.get_macro_bundle()

    assert bundle.status == "partial"
    assert list(bundle.series) == ["yield_curve_10y_2y"]
