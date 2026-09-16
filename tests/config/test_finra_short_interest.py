from __future__ import annotations

from config.finra_short_interest import (
    DAYS_TO_COVER_ELEVATED,
    DAYS_TO_COVER_HIGH,
    PCT_CHANGE_HIGH,
    PCT_CHANGE_LOW,
    PCT_FLOAT_STATUS,
    PUBLICATION_LAG_BUSINESS_DAYS,
)


def test_frozen_thresholds_and_deferred_float_are_pre_registered():
    assert PUBLICATION_LAG_BUSINESS_DAYS == 7
    assert PCT_CHANGE_HIGH == 20.0
    assert PCT_CHANGE_LOW == -20.0
    assert DAYS_TO_COVER_ELEVATED == 5.0
    assert DAYS_TO_COVER_HIGH == 10.0
    assert PCT_FLOAT_STATUS == "deferred"
