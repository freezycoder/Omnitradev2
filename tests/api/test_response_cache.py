from __future__ import annotations

import asyncio

from api import main
from api.response_cache import TtlResponseCache


def test_ttl_cache_reuses_and_defensively_copies_payload() -> None:
    now = [100.0]
    calls: list[int] = []
    cache = TtlResponseCache(clock=lambda: now[0])

    def factory() -> dict[str, list[int]]:
        calls.append(1)
        return {"values": [1, 2]}

    first = cache.get_or_create("key", ttl_seconds=120, factory=factory)
    first["values"].append(3)
    second = cache.get_or_create("key", ttl_seconds=120, factory=factory)

    assert calls == [1]
    assert second == {"values": [1, 2]}


def test_ttl_cache_expires_and_can_be_invalidated() -> None:
    now = [100.0]
    calls: list[int] = []
    cache = TtlResponseCache(clock=lambda: now[0])

    def factory() -> dict[str, int]:
        calls.append(1)
        return {"call": len(calls)}

    assert cache.get_or_create("key", ttl_seconds=60, factory=factory) == {"call": 1}
    now[0] = 161.0
    assert cache.get_or_create("key", ttl_seconds=60, factory=factory) == {"call": 2}
    cache.invalidate()
    assert cache.get_or_create("key", ttl_seconds=60, factory=factory) == {"call": 3}


def test_performance_route_caches_expensive_payload(monkeypatch) -> None:
    calls: list[str] = []
    main._ANALYTICS_RESPONSE_CACHE.invalidate()
    monkeypatch.setattr(
        main,
        "_performance_payload",
        lambda *, price_mode: calls.append(price_mode) or {"overall": {"resolved_signals": 1}},
    )

    first = asyncio.run(main.performance_lab("cached"))
    second = asyncio.run(main.performance_lab("cached"))

    assert first == second
    assert calls == ["cached"]
    main._ANALYTICS_RESPONSE_CACHE.invalidate()


def test_calibration_route_caches_clustered_research_payload(monkeypatch) -> None:
    calls: list[int] = []
    main._ANALYTICS_RESPONSE_CACHE.invalidate()
    monkeypatch.setattr(
        main,
        "_calibration_payload",
        lambda: calls.append(1) or {"research_calibration": {"status": "research_only"}},
    )

    first = asyncio.run(main.calibration())
    second = asyncio.run(main.calibration())

    assert first == second
    assert calls == [1]
    main._ANALYTICS_RESPONSE_CACHE.invalidate()
