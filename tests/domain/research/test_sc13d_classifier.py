from __future__ import annotations

from domain.research.sc13d_classifier import classify_filing, classify_purpose
from providers.events.sc13d_models import Sc13dFiling


def test_specific_activist_language_is_primary():
    purpose_class, groups, phrases, reason = classify_purpose(
        "The Reporting Person will seek board representation and may nominate directors "
        "in a proxy contest to maximize shareholder value."
    )
    assert purpose_class == "activist"
    assert "board_seat" in groups or "hostile" in groups or "activist_purpose" in groups
    assert reason is None
    assert phrases


def test_passive_13g_like_language_is_excluded_even_if_control_phrase_appears_negated():
    purpose_class, groups, phrases, reason = classify_purpose(
        "The securities were acquired solely for investment. The Reporting Person has "
        "no present plans or proposals and did not acquire the shares for the purpose "
        "of changing or influencing control of the issuer."
    )
    assert purpose_class == "passive_excluded"
    assert reason == "passive_13g_like_language"
    assert "passive_exclude" in groups
    assert phrases


def test_generic_may_discuss_boilerplate_is_ambiguous_not_primary():
    purpose_class, _groups, phrases, _reason = classify_purpose(
        "The Reporting Person acquired the shares for investment purposes and may "
        "discuss the investment with management from time to time depending on "
        "market conditions."
    )
    assert purpose_class == "ambiguous"
    assert phrases


def test_pipe_financing_without_activist_intent_is_excluded():
    purpose_class, _groups, _phrases, reason = classify_purpose(
        "The shares were issued in a private placement PIPE financing in connection "
        "with a convertible note and were pledged as collateral."
    )
    assert purpose_class == "financing_excluded"
    assert reason == "pure_financing_disclosure"


def test_classify_filing_keeps_conversion_flag():
    event = classify_filing(
        Sc13dFiling(
            accession_number="1",
            form="SC 13D",
            filed_at="2016-03-01",
            ticker="AAA",
            issuer_cik="1",
            issuer_name="AAA",
            reporting_cik="100",
            reporting_name="Fund",
            url="https://sec",
            purpose_text="The Reporting Person seeks board seats. This statement converts this Schedule 13G.",
            percent_of_class=6.0,
            conversion_text_flag=True,
        )
    )
    assert event.purpose_class == "activist"
    assert event.filing.conversion_13g_to_13d is True
    assert "conversion" in event.matched_groups
