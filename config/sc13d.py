from __future__ import annotations

from datetime import date
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from config.settings import DATA_DIR


# Frozen before any evaluation. Do not retune the lexicon, windows, sample
# start, N floors, or conversion rules after seeing results.

PROTOCOL_VERSION = "sc13d_activist_shadow_v1_2026-09-15"
LEXICON_VERSION = "sc13d_activist_lexicon_v1_2026-09-15"

SC13D_MODE = "shadow"
SC13D_APPLIED_IMPACT = 0
SC13D_MODELED_IMPACT = 0
AUTOMATIC_ACTIVATION = False
LIVE_RANKING_CHANGES = False

SAMPLE_START = date(2009, 1, 1)
PRIMARY_FORMS = frozenset({"SC 13D", "SC 13D/A"})
CONVERSION_REFERENCE_FORMS = frozenset({"SC 13G", "SC 13G/A"})

# Event-time windows in sessions relative to t=0 (first session on/after file date).
# Return is close[t0+end] / close[t0+start-1] - 1, in percent.
POST_WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("car_0_1", 0, 1),
    ("car_0_5", 0, 5),
    ("car_0_20", 0, 20),
    ("car_1_60", 1, 60),
)
PRE_WINDOW: tuple[str, int, int] = ("car_m20_m1", -20, -1)
PRIMARY_WINDOW_KEY = "car_0_5"
PRIMARY_BENCHMARK = "spy"
SECONDARY_BENCHMARK = "sector"

WALK_FORWARD_FOLDS = 3
WALK_FORWARD_EMBARGO_DAYS = 15
MIN_UNIQUE_EVENT_DATES_FOR_FOLDS = 8
MIN_PRIMARY_N = 40
MIN_FOLD_EVENTS = 8
REQUIRED_POSITIVE_FOLDS = 2
MIN_TRAINING_DATES_FOR_FOLD = 4

BOOTSTRAP_CONFIDENCE_LEVEL = 0.90
BOOTSTRAP_ITERATIONS = 500
BOOTSTRAP_SEED = 20260915

# Same-issuer, same-filer amendments inside this gap are one event (keep earliest).
DEDUP_CALENDAR_DAYS = 3
FORM4_OVERLAP_CALENDAR_DAYS = 5

RETURN_DEFINITION = (
    "close_to_close on the issuer session calendar: t=0 is the first session on or "
    "after the EDGAR filing date; window [a,b] is close[t0+b] / close[t0+a-1] - 1; "
    "CAR is stock window return minus SPY (primary) or sector ETF (secondary) over "
    "the same dates."
)

# Specific activist intent. Generic "may discuss with management" boilerplate is
# ambiguous, not primary. Do not add phrases after seeing results.
HOSTILE_PHRASES: tuple[str, ...] = (
    "hostile",
    "unsolicited offer",
    "unsolicited tender",
    "unsolicited proposal",
    "tender offer",
    "consent solicitation",
    "proxy contest",
    "proxy fight",
    "proxy solicitation",
    "withhold vote",
    "withhold votes",
    "replace the board",
    "replace management",
    "replace the ceo",
    "remove the board",
    "remove directors",
    "remove the ceo",
    "change in control",
    "change of control",
    "going private",
)

BOARD_SEAT_PHRASES: tuple[str, ...] = (
    "board seat",
    "board seats",
    "board representation",
    "representation on the board",
    "seek representation",
    "seeking representation",
    "nominate a director",
    "nominate directors",
    "nominating a director",
    "nominating directors",
    "nomination of a director",
    "nomination of directors",
    "slate of directors",
    "designee to the board",
    "designees to the board",
    "director designee",
    "board designee",
)

ACTIVIST_PURPOSE_PHRASES: tuple[str, ...] = (
    "activist",
    "activism",
    "maximize shareholder value",
    "unlock shareholder value",
    "strategic alternatives",
    "extraordinary corporate transaction",
    "sale of the company",
    "sale of the issuer",
    "sale of all or substantially all",
    "recapitalization",
    "special dividend",
    "spin-off",
    "spinoff",
    "spin off",
    "for the purpose of changing or influencing",
    "with the effect of changing or influencing",
    "to influence the control",
    "seeking to change the board",
    "seeking to change management",
    "seeking to change control",
    "stockholder proposal",
    "shareholder proposal",
    "rule 14a-8",
    "14a-8",
    "operational improvements",
    "management change",
    "ceo replacement",
)

AMBIGUOUS_PHRASES: tuple[str, ...] = (
    "may discuss",
    "may communicate",
    "may engage",
    "from time to time",
    "depending on market conditions",
    "depending upon market conditions",
    "review its investment",
    "investment purposes",
    "ordinary investment",
)

PASSIVE_PHRASES: tuple[str, ...] = (
    "solely for investment",
    "investment purposes only",
    "passive investor",
    "passive investment",
    "ordinary course of business",
    "no present plans or proposals",
    "not acquired for the purpose",
    "not acquired with the purpose",
    "without the purpose or with the effect of changing",
    "without the purpose nor with the effect of changing",
    "not with the purpose nor with the effect",
    "not with the purpose or with the effect of changing",
    "eligible to file a statement on schedule 13g",
    "qualified institutional investor",
    "rule 13d-1(b)",
    "rule 13d-1(c)",
)

FINANCING_PHRASES: tuple[str, ...] = (
    "pipe financing",
    "pipe transaction",
    "pipe investment",
    "private placement",
    "registered direct",
    "convertible note",
    "convertible notes",
    "convertible debenture",
    "convertible preferred",
    "credit facility",
    "pledged as collateral",
    "in connection with the loan",
    "in connection with a loan",
    "in connection with the financing",
    "in connection with a financing",
    "standby equity",
    "at-the-market",
    "atm offering",
    "share purchase agreement in connection with financing",
    "warrant issued in connection",
)

CONVERSION_PHRASES: tuple[str, ...] = (
    "no longer eligible to file on schedule 13g",
    "no longer eligible to report on schedule 13g",
    "converts this schedule 13g",
    "convert this schedule 13g",
    "converting this schedule 13g",
    "converted this schedule 13g",
    "amendment to schedule 13g",
    "previously filed a schedule 13g",
    "previously filed schedule 13g",
    "supersedes the schedule 13g",
    "in lieu of schedule 13g",
)

FILTER_DOCUMENTATION = MappingProxyType(
    {
        "primary_subset": (
            "SC 13D or 13D/A filed on or after 2009-01-01 whose Item 4 / purpose "
            "text matches at least one frozen hostile, board-seat, or specific "
            "activist-purpose phrase, after HTML/SGML stripping."
        ),
        "passive_excluded": (
            "Filings whose purpose text matches a frozen passive / 13G-like phrase "
            "and do not match any primary activist phrase. Standard 'not acquired "
            "for the purpose of changing or influencing control' language is treated "
            "as passive, not activist."
        ),
        "financing_excluded": (
            "Filings whose purpose text matches a frozen financing / PIPE / collateral "
            "phrase and do not match any primary activist phrase."
        ),
        "ambiguous_secondary_only": (
            "Remaining 13D/A filings, including generic 'may discuss with management' "
            "boilerplate. Used only as a descriptive stratum, never for the success gate."
        ),
        "amendment_dedup": (
            f"Same issuer ticker and reporting CIK inside {DEDUP_CALENDAR_DAYS} calendar "
            "days collapse to the earliest accession."
        ),
    }
)

SC13D_CACHE_DIR = DATA_DIR / "sc13d_cache"
SC13D_FILINGS_FILE = SC13D_CACHE_DIR / "filings.json"
SC13D_SHADOW_LOG_FILE = SC13D_CACHE_DIR / "shadow_events.jsonl"
SC13D_LAST_RUN_FILE = SC13D_CACHE_DIR / "last_experiment.json"

SEC_EFTS_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

EXPERIMENT_PROTOCOL = MappingProxyType(
    {
        "version": PROTOCOL_VERSION,
        "lexicon_version": LEXICON_VERSION,
        "mode": SC13D_MODE,
        "applied_impact": SC13D_APPLIED_IMPACT,
        "modeled_impact": SC13D_MODELED_IMPACT,
        "automatic_activation": AUTOMATIC_ACTIVATION,
        "live_ranking_changes": LIVE_RANKING_CHANGES,
        "hypothesis": (
            "New SC 13D (/A) filings that disclose activist intent (purpose-of-transaction "
            "/ hostile or board-seat language), plus optional 13G→13D conversion flags, "
            "produce positive abnormal returns around filing that are usable as shadow "
            "event features — distinct from Form-4 insider clusters."
        ),
        "falsifier": (
            "In a modern post-2008 sample with pre-registered event filters, mean CAR "
            "around activist 13D is indistinguishable from 0 after excluding passive "
            "13G-like language and controlling for pre-filing run-up; OR the effect "
            "exists only inside (−20,0) and is fully anticipated (no tradeable post-file "
            "window)."
        ),
        "source": (
            "Brav, Jiang, Partnoy, Thomas, Journal of Finance 63(4) 2008. Activist "
            "hedge-fund Schedule 13D filings 2001–2006: ~7–8% average abnormal return "
            "in (−20,+20). This experiment retests a post-2008 sample and does not "
            "assume those magnitudes still hold."
        ),
        "sample_start": SAMPLE_START.isoformat(),
        "forms": tuple(sorted(PRIMARY_FORMS)),
        "conversion_reference_forms": tuple(sorted(CONVERSION_REFERENCE_FORMS)),
        "lexicon": MappingProxyType(
            {
                "hostile": HOSTILE_PHRASES,
                "board_seat": BOARD_SEAT_PHRASES,
                "activist_purpose": ACTIVIST_PURPOSE_PHRASES,
                "ambiguous": AMBIGUOUS_PHRASES,
                "passive_exclude": PASSIVE_PHRASES,
                "financing_exclude": FINANCING_PHRASES,
                "conversion": CONVERSION_PHRASES,
            }
        ),
        "filters": FILTER_DOCUMENTATION,
        "windows": MappingProxyType(
            {
                "post_file": tuple(
                    {"key": key, "start": start, "end": end} for key, start, end in POST_WINDOWS
                ),
                "pre_file_runup": {"key": PRE_WINDOW[0], "start": PRE_WINDOW[1], "end": PRE_WINDOW[2]},
                "primary_post_window": PRIMARY_WINDOW_KEY,
            }
        ),
        "primary_benchmark": PRIMARY_BENCHMARK,
        "secondary_benchmark": SECONDARY_BENCHMARK,
        "return_definition": RETURN_DEFINITION,
        "success_rule": (
            f"Pre-registered activist subset shows significant positive mean CAR "
            f"(bootstrap {BOOTSTRAP_CONFIDENCE_LEVEL:.0%} CI excludes 0 and mean > 0) "
            f"in at least one frozen post-file window in >={REQUIRED_POSITIVE_FOLDS} "
            f"walk-forward folds; activist event count with complete primary window "
            f">={MIN_PRIMARY_N}; passive 13G-like and pure financing excluded."
        ),
        "fail_rule": (
            "Null post-file CAR; OR activist N below the pre-registered floor; OR the "
            "only significant CAR is in the (−20,−1) run-up (fully anticipated)."
        ),
        "walk_forward": MappingProxyType(
            {
                "folds": WALK_FORWARD_FOLDS,
                "embargo_days": WALK_FORWARD_EMBARGO_DAYS,
                "split_basis": "event_date",
                "design": "expanding_window_with_calendar_embargo",
                "min_fold_events": MIN_FOLD_EVENTS,
            }
        ),
        "bootstrap": MappingProxyType(
            {
                "method": "event_date_cluster_bootstrap",
                "confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
                "iterations": BOOTSTRAP_ITERATIONS,
                "seed": BOOTSTRAP_SEED,
            }
        ),
        "orthogonality": MappingProxyType(
            {
                "form4_overlap_calendar_days": FORM4_OVERLAP_CALENDAR_DAYS,
                "role": "diagnostic_only",
                "note": (
                    "If Form-4 open-market buy events are supplied, report overlap and "
                    "CAR for 13D-only vs 13D-with-nearby-Form4. Not a success gate."
                ),
            }
        ),
        "secondary_only": ("purpose_ambiguous", "sector_car", "conversion_flag_stratum"),
        "overfitting_mitigations": (
            "Lexicon and primary window frozen before eval.",
            "Modern post-2008 sample required.",
            "Passive / financing exclusions frozen.",
            "Activist vs ambiguous is secondary only.",
        ),
    }
)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def protocol_payload() -> dict[str, Any]:
    return _thaw(EXPERIMENT_PROTOCOL)


def all_primary_phrases() -> tuple[str, ...]:
    return HOSTILE_PHRASES + BOARD_SEAT_PHRASES + ACTIVIST_PURPOSE_PHRASES


def lexicon_groups() -> Sequence[tuple[str, tuple[str, ...]]]:
    return (
        ("hostile", HOSTILE_PHRASES),
        ("board_seat", BOARD_SEAT_PHRASES),
        ("activist_purpose", ACTIVIST_PURPOSE_PHRASES),
        ("ambiguous", AMBIGUOUS_PHRASES),
        ("passive_exclude", PASSIVE_PHRASES),
        ("financing_exclude", FINANCING_PHRASES),
        ("conversion", CONVERSION_PHRASES),
    )


__all__ = [
    "AMBIGUOUS_PHRASES",
    "ACTIVIST_PURPOSE_PHRASES",
    "AUTOMATIC_ACTIVATION",
    "BOARD_SEAT_PHRASES",
    "BOOTSTRAP_CONFIDENCE_LEVEL",
    "BOOTSTRAP_ITERATIONS",
    "BOOTSTRAP_SEED",
    "CONVERSION_PHRASES",
    "CONVERSION_REFERENCE_FORMS",
    "DEDUP_CALENDAR_DAYS",
    "EXPERIMENT_PROTOCOL",
    "FILTER_DOCUMENTATION",
    "FINANCING_PHRASES",
    "FORM4_OVERLAP_CALENDAR_DAYS",
    "HOSTILE_PHRASES",
    "LEXICON_VERSION",
    "LIVE_RANKING_CHANGES",
    "MIN_FOLD_EVENTS",
    "MIN_PRIMARY_N",
    "MIN_TRAINING_DATES_FOR_FOLD",
    "MIN_UNIQUE_EVENT_DATES_FOR_FOLDS",
    "PASSIVE_PHRASES",
    "POST_WINDOWS",
    "PRE_WINDOW",
    "PRIMARY_BENCHMARK",
    "PRIMARY_FORMS",
    "PRIMARY_WINDOW_KEY",
    "PROTOCOL_VERSION",
    "REQUIRED_POSITIVE_FOLDS",
    "RETURN_DEFINITION",
    "SAMPLE_START",
    "SC13D_APPLIED_IMPACT",
    "SC13D_CACHE_DIR",
    "SC13D_FILINGS_FILE",
    "SC13D_LAST_RUN_FILE",
    "SC13D_MODE",
    "SC13D_MODELED_IMPACT",
    "SC13D_SHADOW_LOG_FILE",
    "SEC_EFTS_SEARCH_URL",
    "WALK_FORWARD_EMBARGO_DAYS",
    "WALK_FORWARD_FOLDS",
    "all_primary_phrases",
    "lexicon_groups",
    "protocol_payload",
]
