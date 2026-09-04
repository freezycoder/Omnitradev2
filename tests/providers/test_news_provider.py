from __future__ import annotations

from providers.news.news_provider import build_news_items


def test_news_items_classify_events_sources_and_relevance():
    items = build_news_items(
        [
            {
                "headline": "Apple raises guidance after quarterly results",
                "summary": "AAPL reported stronger demand.",
                "source": "Reuters",
                "related": "AAPL",
                "datetime": 1_785_200_000,
            }
        ],
        ticker="AAPL",
        company_name="Apple Inc.",
    )

    assert len(items) == 1
    assert items[0].event_type == "guidance"
    assert items[0].source_quality == "established_reporting"
    assert items[0].relevance_score == 100
    assert items[0].direction == 1


def test_news_items_remove_near_duplicate_coverage():
    items = build_news_items(
        [
            {"headline": "Apple raises guidance after strong quarterly results", "source": "Reuters"},
            {"headline": "Apple raises guidance following strong quarterly results", "source": "Other"},
        ],
        ticker="AAPL",
    )

    assert len(items) == 1
