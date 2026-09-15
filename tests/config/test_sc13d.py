from __future__ import annotations

from config.sc13d import (
    LEXICON_VERSION,
    MIN_PRIMARY_N,
    PRIMARY_WINDOW_KEY,
    PROTOCOL_VERSION,
    REQUIRED_POSITIVE_FOLDS,
    SAMPLE_START,
    SC13D_APPLIED_IMPACT,
    SC13D_MODELED_IMPACT,
    all_primary_phrases,
    protocol_payload,
)


def test_protocol_is_frozen_before_eval():
    payload = protocol_payload()
    assert payload["version"] == PROTOCOL_VERSION
    assert payload["lexicon_version"] == LEXICON_VERSION
    assert payload["mode"] == "shadow"
    assert payload["applied_impact"] == 0
    assert payload["live_ranking_changes"] is False
    assert payload["automatic_activation"] is False
    assert payload["windows"]["primary_post_window"] == PRIMARY_WINDOW_KEY
    assert SAMPLE_START.isoformat() == "2009-01-01"
    assert MIN_PRIMARY_N == 40
    assert REQUIRED_POSITIVE_FOLDS == 2
    assert SC13D_APPLIED_IMPACT == 0
    assert SC13D_MODELED_IMPACT == 0
    assert "board seat" in all_primary_phrases()
    assert "proxy contest" in all_primary_phrases()
    assert "may discuss" not in all_primary_phrases()
