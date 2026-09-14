from __future__ import annotations

from providers.events.tracefour_client import TracefourClient


def test_tracefour_disabled_never_calls_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Tracefour must not be called when disabled.")

    monkeypatch.setattr("providers.events.tracefour_client.urlopen", fail)
    client = TracefourClient(enabled=False)
    payload = client.get_clusters()
    assert payload["data"] == []
    assert payload["meta"]["terms"]["never_primary"] is True
    assert client.terms.anonymous_rate_limit_per_hour == 60
    assert "CC BY 4.0" in client.terms.license
