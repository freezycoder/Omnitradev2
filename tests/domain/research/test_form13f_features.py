from __future__ import annotations

from config.form13f import CLUSTER_MIN_NOTABLE_MANAGERS, NOTABLE_AUM_FLOOR_USD
from config.form13f_taxonomy_v1 import NAMED_NOTABLE_MANAGERS, PASSIVE_INDEX_MANAGERS, normalize_cik
from domain.research.form13f_features import (
    classify_manager,
    detect_clusters,
    detect_streaks,
    event_date_is_lag_correct,
    primary_cluster_events,
)
from domain.research.form13f_fixture import NOTABLE_CIKS, PASSIVE_CIKS, holding


def _row(ticker: str, cik: str, quarter: str, filed: str, *, value_usd: float = 50_000_000.0):
    name = NAMED_NOTABLE_MANAGERS.get(cik) or PASSIVE_INDEX_MANAGERS.get(cik) or cik
    return holding(
        ticker=ticker,
        manager_cik=cik,
        manager_name=name,
        reportable_quarter=quarter,
        filed_at=filed,
        accession=f"{cik}-{quarter}-{ticker}-{filed}",
        value_usd=value_usd,
    )


def test_passive_exclusions_are_never_notable_even_above_aum_floor() -> None:
    passive = next(iter(PASSIVE_INDEX_MANAGERS))
    notable, is_passive, reason = classify_manager(passive, NOTABLE_AUM_FLOOR_USD * 5)
    assert notable is False
    assert is_passive is True
    assert reason == "passive_index_exclusion"


def test_named_and_aum_floor_are_notable() -> None:
    named = next(iter(NAMED_NOTABLE_MANAGERS))
    assert classify_manager(named, 1.0)[0] is True
    unknown = "0001999999"
    assert classify_manager(unknown, NOTABLE_AUM_FLOOR_USD - 1)[0] is False
    assert classify_manager(unknown, NOTABLE_AUM_FLOOR_USD) == (True, False, "aum_floor")
    assert normalize_cik("1037389") == "0001037389"


def test_cluster_requires_three_notable_new_enters_and_uses_kth_filing_date() -> None:
    prior = [
        _row("DDD", NOTABLE_CIKS[0], "2021-12-31", "2022-02-14"),
        _row("DDD", NOTABLE_CIKS[1], "2021-12-31", "2022-02-14"),
        _row("DDD", NOTABLE_CIKS[2], "2021-12-31", "2022-02-14"),
    ]
    two = prior + [
        _row("AAA", NOTABLE_CIKS[0], "2022-03-31", "2022-05-16"),
        _row("AAA", NOTABLE_CIKS[1], "2022-03-31", "2022-05-17"),
        _row("DDD", NOTABLE_CIKS[0], "2022-03-31", "2022-05-16"),
        _row("DDD", NOTABLE_CIKS[1], "2022-03-31", "2022-05-17"),
        _row("DDD", NOTABLE_CIKS[2], "2022-03-31", "2022-05-18"),
    ]
    assert detect_clusters(two) == []

    three = two + [
        _row("AAA", NOTABLE_CIKS[2], "2022-03-31", "2022-05-18"),
    ]
    clusters = detect_clusters(three)
    assert len(clusters) == 1
    assert clusters[0].notable_count == CLUSTER_MIN_NOTABLE_MANAGERS
    assert clusters[0].direction == "entry"
    assert clusters[0].event_date == "2022-05-18"
    assert event_date_is_lag_correct(clusters[0].event_date, clusters[0].reportable_quarter)
    assert clusters[0].event_date != clusters[0].reportable_quarter


def test_two_passives_mark_etf_churn_and_leave_primary_book() -> None:
    rows = [
        _row("DDD", NOTABLE_CIKS[0], "2021-12-31", "2022-02-14"),
        _row("DDD", NOTABLE_CIKS[1], "2021-12-31", "2022-02-14"),
        _row("DDD", NOTABLE_CIKS[2], "2021-12-31", "2022-02-14"),
        _row("DDD", PASSIVE_CIKS[0], "2021-12-31", "2022-02-14"),
        _row("DDD", PASSIVE_CIKS[1], "2021-12-31", "2022-02-14"),
        _row("AAA", NOTABLE_CIKS[0], "2022-03-31", "2022-05-16"),
        _row("AAA", NOTABLE_CIKS[1], "2022-03-31", "2022-05-16"),
        _row("AAA", NOTABLE_CIKS[2], "2022-03-31", "2022-05-16"),
        _row("AAA", PASSIVE_CIKS[0], "2022-03-31", "2022-05-16"),
        _row("AAA", PASSIVE_CIKS[1], "2022-03-31", "2022-05-16"),
        _row("DDD", NOTABLE_CIKS[0], "2022-03-31", "2022-05-16"),
        _row("DDD", NOTABLE_CIKS[1], "2022-03-31", "2022-05-16"),
        _row("DDD", NOTABLE_CIKS[2], "2022-03-31", "2022-05-16"),
        _row("DDD", PASSIVE_CIKS[0], "2022-03-31", "2022-05-16"),
        _row("DDD", PASSIVE_CIKS[1], "2022-03-31", "2022-05-16"),
    ]
    clusters = detect_clusters(rows)
    assert clusters[0].etf_churn_suspect is True
    assert primary_cluster_events(clusters) == []


def test_streak_requires_two_consecutive_net_add_quarters() -> None:
    rows = [
        _row("DDD", NOTABLE_CIKS[0], "2021-12-31", "2022-02-14"),
        _row("DDD", NOTABLE_CIKS[1], "2021-12-31", "2022-02-14"),
        _row("AAA", NOTABLE_CIKS[0], "2022-03-31", "2022-05-16"),
        _row("DDD", NOTABLE_CIKS[0], "2022-03-31", "2022-05-16"),
        _row("DDD", NOTABLE_CIKS[1], "2022-03-31", "2022-05-16"),
        _row("AAA", NOTABLE_CIKS[0], "2022-06-30", "2022-08-15"),
        _row("AAA", NOTABLE_CIKS[1], "2022-06-30", "2022-08-15"),
        _row("DDD", NOTABLE_CIKS[0], "2022-06-30", "2022-08-15"),
        _row("DDD", NOTABLE_CIKS[1], "2022-06-30", "2022-08-15"),
    ]
    streaks = detect_streaks(rows)
    assert len(streaks) == 1
    assert streaks[0].quarters == 2
    assert streaks[0].event_date == "2022-08-15"
    assert streaks[0].reportable_quarter == "2022-06-30"
