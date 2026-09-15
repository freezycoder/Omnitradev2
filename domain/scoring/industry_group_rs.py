from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, Mapping, Sequence
from typing import assert_never

import numpy as np
import pandas as pd

from config.industry_groups import (
    INDUSTRY_GROUP_MAP,
    INDUSTRY_GROUP_MAP_VERSION,
    INDUSTRY_GROUP_SOURCE,
    INDUSTRY_GROUP_TAXONOMY,
    IndustryGroupMembership,
    industry_group_for_ticker,
    map_manifest,
    universe_coverage,
)
from domain.scoring.relative_strength import compute_raw_strength_frame


# Pre-registered RRG recipe. Do not tune these windows against in-sample IC.
RRG_WEEKLY_ANCHOR = "W-FRI"
RRG_ZSCORE_WEEKS = 52
RRG_MIN_WEEKS = 26
RRG_MOMENTUM_LAG_WEEKS = 1
RANK_LOOKBACK_SESSIONS = {
    "1w": 5,
    "1m": 21,
    "3m": 63,
    "6m": 126,
}
MIN_HISTORY_SESSIONS_FOR_RS = 253
MIN_HISTORY_SESSIONS_RECOMMENDED = 504  # ~2y trading days
INDUSTRY_GROUP_RS_MODE = "shadow"

RRGQuadrant = Literal["Leading", "Weakening", "Lagging", "Improving"]


@dataclass(frozen=True)
class IndustryGroupRelativeStrengthView:
    mode: str
    status: str
    applied_impact: int
    coverage_score: int
    map_version: str
    taxonomy: str
    group_id: str | None
    group_name: str | None
    gics_code: str | None
    constituent_count: int
    singleton_group: bool
    group_avg_rs_pct: float | None
    group_rank: int | None
    group_count: int | None
    group_rank_percentile: int | None
    rank_delta_1w: int | None
    rank_delta_1m: int | None
    rank_delta_3m: int | None
    rank_delta_6m: int | None
    rs_ratio: float | None
    rs_momentum: float | None
    rrg_quadrant: str | None
    rrg_recipe: dict[str, Any]
    summary: str
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    as_of_date: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rrg_recipe_manifest() -> dict[str, Any]:
    return {
        "weekly_anchor": RRG_WEEKLY_ANCHOR,
        "zscore_weeks": RRG_ZSCORE_WEEKS,
        "min_weeks": RRG_MIN_WEEKS,
        "momentum_lag_weeks": RRG_MOMENTUM_LAG_WEEKS,
        "normalization": "trailing_zscore_own_history",
        "rs_ratio": "zscore(weekly_group_avg_rs)",
        "rs_momentum": "zscore(diff(weekly_group_avg_rs, lag=1w))",
        "quadrants": {
            "Leading": "rs_ratio >= 0 and rs_momentum >= 0",
            "Weakening": "rs_ratio >= 0 and rs_momentum < 0",
            "Lagging": "rs_ratio < 0 and rs_momentum < 0",
            "Improving": "rs_ratio < 0 and rs_momentum >= 0",
        },
        "frozen": True,
    }


def rrg_quadrant(rs_ratio: float, rs_momentum: float) -> RRGQuadrant:
    key = (rs_ratio >= 0, rs_momentum >= 0)
    match key:
        case (True, True):
            return "Leading"
        case (True, False):
            return "Weakening"
        case (False, False):
            return "Lagging"
        case (False, True):
            return "Improving"
        case _ as unreachable:
            assert_never(unreachable)


def build_unavailable_industry_group_rs_view(
    *,
    ticker: str | None = None,
    membership: IndustryGroupMembership | None = None,
    message: str,
    warnings: list[str] | None = None,
) -> IndustryGroupRelativeStrengthView:
    resolved = membership or (industry_group_for_ticker(ticker) if ticker else None)
    warning_rows = list(warnings or [])
    if message not in warning_rows:
        warning_rows.append(message)
    return IndustryGroupRelativeStrengthView(
        mode=INDUSTRY_GROUP_RS_MODE,
        status="unavailable",
        applied_impact=0,
        coverage_score=0,
        map_version=INDUSTRY_GROUP_MAP_VERSION,
        taxonomy=INDUSTRY_GROUP_TAXONOMY,
        group_id=resolved.group_id if resolved else None,
        group_name=resolved.group_name if resolved else None,
        gics_code=resolved.gics_code if resolved else None,
        constituent_count=0,
        singleton_group=False,
        group_avg_rs_pct=None,
        group_rank=None,
        group_count=None,
        group_rank_percentile=None,
        rank_delta_1w=None,
        rank_delta_1m=None,
        rank_delta_3m=None,
        rank_delta_6m=None,
        rs_ratio=None,
        rs_momentum=None,
        rrg_quadrant=None,
        rrg_recipe=rrg_recipe_manifest(),
        summary=message,
        warnings=list(dict.fromkeys(warning_rows)),
        updated_at=datetime.now(UTC).isoformat(),
    )


def industry_group_rs_view_from_dict(
    payload: dict[str, Any] | None,
    *,
    ticker: str | None = None,
) -> IndustryGroupRelativeStrengthView:
    if not isinstance(payload, dict):
        return build_unavailable_industry_group_rs_view(
            ticker=ticker,
            message="The cached snapshot predates industry-group relative-strength analysis.",
        )
    values = dict(payload)
    values.setdefault("rrg_recipe", rrg_recipe_manifest())
    values.setdefault("evidence", [])
    values.setdefault("warnings", [])
    return IndustryGroupRelativeStrengthView(**values)


def _stub_view_for_membership(
    membership: IndustryGroupMembership | None,
    *,
    ticker: str,
    message: str,
) -> IndustryGroupRelativeStrengthView:
    if membership is None:
        return build_unavailable_industry_group_rs_view(
            ticker=ticker,
            message=message,
        )
    return IndustryGroupRelativeStrengthView(
        mode=INDUSTRY_GROUP_RS_MODE,
        status="mapped",
        applied_impact=0,
        coverage_score=20,
        map_version=INDUSTRY_GROUP_MAP_VERSION,
        taxonomy=INDUSTRY_GROUP_TAXONOMY,
        group_id=membership.group_id,
        group_name=membership.group_name,
        gics_code=membership.gics_code,
        constituent_count=0,
        singleton_group=False,
        group_avg_rs_pct=None,
        group_rank=None,
        group_count=None,
        group_rank_percentile=None,
        rank_delta_1w=None,
        rank_delta_1m=None,
        rank_delta_3m=None,
        rank_delta_6m=None,
        rs_ratio=None,
        rs_momentum=None,
        rrg_quadrant=None,
        rrg_recipe=rrg_recipe_manifest(),
        summary=message,
        warnings=[message],
        updated_at=datetime.now(UTC).isoformat(),
    )


def build_mapped_industry_group_rs_stub(
    ticker: str,
    mapping: Mapping[str, IndustryGroupMembership] | None = None,
) -> IndustryGroupRelativeStrengthView:
    membership = industry_group_for_ticker(ticker, mapping=mapping)
    if membership is None:
        return build_unavailable_industry_group_rs_view(
            ticker=ticker,
            message="No frozen industry-group membership is available for this ticker.",
        )
    return _stub_view_for_membership(
        membership,
        ticker=ticker,
        message=(
            f"Mapped to {membership.group_name} ({membership.group_id}) on "
            f"{INDUSTRY_GROUP_MAP_VERSION}. Group rank and RRG require a full scan."
        ),
    )


def _as_naive_index(index: pd.Index) -> pd.DatetimeIndex:
    converted = pd.to_datetime(index)
    if getattr(converted, "tz", None) is not None:
        converted = converted.tz_localize(None)
    return pd.DatetimeIndex(converted)


def _trailing_zscore(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    mean = series.rolling(window=window, min_periods=min_periods).mean()
    std = series.rolling(window=window, min_periods=min_periods).std(ddof=0)
    return (series - mean) / std.replace(0, np.nan)


def _percentile_rank(value: float, values: list[float], *, minimum_peers: int) -> int | None:
    if len(values) < minimum_peers:
        return None
    below = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    denominator = len(values) - 1
    if denominator <= 0:
        return None
    mid_rank = below + (equal - 1) / 2
    return int(round(mid_rank / denominator * 100))


def compute_name_feature_frames(
    histories: Mapping[str, pd.DataFrame],
    market_history: pd.DataFrame,
    sector_histories: Mapping[str, pd.DataFrame] | None = None,
    sectors_by_ticker: Mapping[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    sector_histories = sector_histories or {}
    sectors_by_ticker = sectors_by_ticker or {}
    for ticker, history in histories.items():
        sector = sectors_by_ticker.get(ticker, "")
        sector_history = sector_histories.get(sector, pd.DataFrame())
        frame = compute_raw_strength_frame(history, market_history, sector_history)
        if frame.empty or "raw_strength_pct" not in frame.columns:
            continue
        frame = frame.copy()
        frame.index = _as_naive_index(frame.index)
        frames[str(ticker).upper().strip()] = frame
    return frames


def compute_group_avg_rs_frame(
    name_frames: Mapping[str, pd.DataFrame],
    memberships: Mapping[str, IndustryGroupMembership],
) -> pd.DataFrame:
    series_by_group: dict[str, list[pd.Series]] = {}
    for ticker, frame in name_frames.items():
        membership = memberships.get(ticker)
        if membership is None or "raw_strength_pct" not in frame.columns:
            continue
        series_by_group.setdefault(membership.group_id, []).append(frame["raw_strength_pct"])
    if not series_by_group:
        return pd.DataFrame()
    columns = {
        group_id: pd.concat(series, axis=1).mean(axis=1, skipna=True)
        for group_id, series in series_by_group.items()
        if series
    }
    grouped = pd.DataFrame(columns).sort_index()
    grouped.index = _as_naive_index(grouped.index)
    return grouped


def compute_group_rank_frame(group_avg_rs: pd.DataFrame) -> pd.DataFrame:
    if group_avg_rs.empty:
        return pd.DataFrame()
    return group_avg_rs.rank(axis=1, method="average", ascending=False, na_option="keep")


def compute_rrg_frame(group_avg_rs: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if group_avg_rs.empty:
        return {"rs_ratio": pd.DataFrame(), "rs_momentum": pd.DataFrame()}
    weekly = group_avg_rs.resample(RRG_WEEKLY_ANCHOR).last()
    rs_ratio = weekly.apply(
        lambda column: _trailing_zscore(column, RRG_ZSCORE_WEEKS, RRG_MIN_WEEKS)
    )
    weekly_change = weekly.diff(RRG_MOMENTUM_LAG_WEEKS)
    rs_momentum = weekly_change.apply(
        lambda column: _trailing_zscore(column, RRG_ZSCORE_WEEKS, RRG_MIN_WEEKS)
    )
    return {"rs_ratio": rs_ratio, "rs_momentum": rs_momentum}


def _latest_numeric(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    valid = series.dropna()
    if valid.empty:
        return None
    return float(valid.iloc[-1])


def _rank_delta(rank_series: pd.Series | None, sessions: int) -> int | None:
    if rank_series is None:
        return None
    valid = rank_series.dropna()
    if len(valid) <= sessions:
        return None
    current = float(valid.iloc[-1])
    previous = float(valid.iloc[-(sessions + 1)])
    return int(round(previous - current))


def _coverage_score(
    *,
    mapped: bool,
    constituent_count: int,
    has_group_avg: bool,
    has_rank: bool,
    has_rrg: bool,
    history_sessions: int,
) -> int:
    if not mapped:
        return 0
    score = 20
    if constituent_count > 0 and has_group_avg:
        score += 25
    if has_rank:
        score += 15
    if has_rrg:
        score += 25
    if history_sessions >= MIN_HISTORY_SESSIONS_RECOMMENDED:
        score += 15
    elif history_sessions >= MIN_HISTORY_SESSIONS_FOR_RS:
        score += 8
    return min(score, 100)


def _status_for(view_kwargs: dict[str, Any]) -> str:
    if view_kwargs.get("group_id") is None:
        return "unmapped"
    if view_kwargs.get("group_avg_rs_pct") is None:
        return "mapped"
    if view_kwargs.get("rrg_quadrant"):
        return "complete"
    return "partial"


def assign_industry_group_relative_strength(
    results: Sequence[Any],
    *,
    market_history: pd.DataFrame | None = None,
    sector_histories: Mapping[str, pd.DataFrame] | None = None,
    mapping: Mapping[str, IndustryGroupMembership] | None = None,
) -> dict[str, Any]:
    catalog = mapping if mapping is not None else INDUSTRY_GROUP_MAP
    coverage = universe_coverage(
        [getattr(result, "ticker", "") for result in results],
        mapping=catalog,
    )
    memberships = {
        str(getattr(result, "ticker", "")).upper().strip(): industry_group_for_ticker(
            getattr(result, "ticker", ""),
            mapping=catalog,
        )
        for result in results
    }
    mapped_memberships = {
        ticker: membership
        for ticker, membership in memberships.items()
        if membership is not None
    }
    current_strength: dict[str, float] = {}
    histories: dict[str, pd.DataFrame] = {}
    sectors_by_ticker: dict[str, str] = {}
    for result in results:
        ticker = str(getattr(result, "ticker", "")).upper().strip()
        rs_view = getattr(result, "relative_strength_view", None)
        raw_strength = getattr(rs_view, "raw_strength_pct", None) if rs_view is not None else None
        coverage_score = getattr(rs_view, "coverage_score", 0) if rs_view is not None else 0
        if isinstance(raw_strength, (int, float)) and coverage_score >= 40:
            current_strength[ticker] = float(raw_strength)
        history = getattr(result, "history", None)
        if isinstance(history, pd.DataFrame) and not history.empty:
            histories[ticker] = history
        sectors_by_ticker[ticker] = str(getattr(result, "sector", "") or "")

    group_to_tickers: dict[str, list[str]] = {}
    for ticker, membership in mapped_memberships.items():
        group_to_tickers.setdefault(membership.group_id, []).append(ticker)

    group_avg_now: dict[str, float] = {}
    for group_id, tickers in group_to_tickers.items():
        values = [current_strength[ticker] for ticker in tickers if ticker in current_strength]
        if values:
            group_avg_now[group_id] = float(sum(values) / len(values))

    ranked_groups = sorted(group_avg_now, key=lambda group_id: (-group_avg_now[group_id], group_id))
    group_rank_now = {group_id: index for index, group_id in enumerate(ranked_groups, start=1)}
    group_rank_values = [float(rank) for rank in group_rank_now.values()]

    name_frames: dict[str, pd.DataFrame] = {}
    group_avg_frame = pd.DataFrame()
    group_rank_frame = pd.DataFrame()
    rrg_frames = {"rs_ratio": pd.DataFrame(), "rs_momentum": pd.DataFrame()}
    history_warnings: list[str] = []
    if market_history is not None and not market_history.empty and histories:
        name_frames = compute_name_feature_frames(
            histories,
            market_history,
            sector_histories=sector_histories,
            sectors_by_ticker=sectors_by_ticker,
        )
        group_avg_frame = compute_group_avg_rs_frame(name_frames, mapped_memberships)
        group_rank_frame = compute_group_rank_frame(group_avg_frame)
        rrg_frames = compute_rrg_frame(group_avg_frame)
    elif histories:
        history_warnings.append(
            "Market benchmark history was unavailable, so rank deltas and RRG axes were not computed."
        )

    max_history_sessions = 0
    if histories:
        max_history_sessions = max(len(frame) for frame in histories.values())
    if max_history_sessions and max_history_sessions < MIN_HISTORY_SESSIONS_RECOMMENDED:
        history_warnings.append(
            f"Longest constituent history is {max_history_sessions} sessions; "
            f"{MIN_HISTORY_SESSIONS_RECOMMENDED} (~2y) is recommended for RRG tails."
        )

    as_of_date: str | None = None
    for frame in name_frames.values():
        if not frame.empty:
            as_of_date = pd.Timestamp(frame.index[-1]).date().isoformat()
            break

    singleton_groups = sum(1 for tickers in group_to_tickers.values() if len(tickers) == 1)
    for result in results:
        ticker = str(getattr(result, "ticker", "")).upper().strip()
        membership = memberships.get(ticker)
        warnings = list(history_warnings)
        if membership is None:
            result.industry_group_rs_view = build_unavailable_industry_group_rs_view(
                ticker=ticker,
                message="No frozen industry-group membership is available for this ticker.",
                warnings=warnings,
            )
            continue

        constituents = group_to_tickers.get(membership.group_id, [])
        group_avg = group_avg_now.get(membership.group_id)
        rank = group_rank_now.get(membership.group_id)
        rank_percentile = (
            _percentile_rank(float(rank), group_rank_values, minimum_peers=2)
            if rank is not None
            else None
        )
        rank_series = (
            group_rank_frame[membership.group_id]
            if membership.group_id in group_rank_frame.columns
            else None
        )
        ratio_series = (
            rrg_frames["rs_ratio"][membership.group_id]
            if membership.group_id in rrg_frames["rs_ratio"].columns
            else None
        )
        momentum_series = (
            rrg_frames["rs_momentum"][membership.group_id]
            if membership.group_id in rrg_frames["rs_momentum"].columns
            else None
        )
        rs_ratio = _round_optional(_latest_numeric(ratio_series), 4)
        rs_momentum = _round_optional(_latest_numeric(momentum_series), 4)
        quadrant: str | None = None
        if rs_ratio is not None and rs_momentum is not None:
            quadrant = rrg_quadrant(rs_ratio, rs_momentum)

        history_sessions = len(histories.get(ticker, []))
        evidence = [
            INDUSTRY_GROUP_SOURCE,
            f"{membership.group_name} currently has {len(constituents)} mapped scan constituents.",
        ]
        if group_avg is not None:
            evidence.append(f"Equal-weight group average RS is {group_avg:.2f}%.")
        if rank is not None:
            evidence.append(f"Group rank is {rank} of {len(ranked_groups)} (1 = strongest).")
        if quadrant:
            evidence.append(f"Pre-registered weekly RRG quadrant is {quadrant}.")
        if len(constituents) <= 1:
            warnings.append(
                "This industry group has a single mapped constituent, so group RS equals the name RS."
            )

        coverage_score = _coverage_score(
            mapped=True,
            constituent_count=len(constituents),
            has_group_avg=group_avg is not None,
            has_rank=rank is not None,
            has_rrg=quadrant is not None,
            history_sessions=history_sessions,
        )
        payload = {
            "group_id": membership.group_id,
            "group_avg_rs_pct": group_avg,
            "rrg_quadrant": quadrant,
        }
        status = _status_for(payload)
        summary = _summary_for(
            status=status,
            membership=membership,
            rank=rank,
            group_count=len(ranked_groups),
            quadrant=quadrant,
        )
        result.industry_group_rs_view = IndustryGroupRelativeStrengthView(
            mode=INDUSTRY_GROUP_RS_MODE,
            status=status,
            applied_impact=0,
            coverage_score=coverage_score,
            map_version=INDUSTRY_GROUP_MAP_VERSION,
            taxonomy=INDUSTRY_GROUP_TAXONOMY,
            group_id=membership.group_id,
            group_name=membership.group_name,
            gics_code=membership.gics_code,
            constituent_count=len(constituents),
            singleton_group=len(constituents) <= 1,
            group_avg_rs_pct=_round_optional(group_avg, 2),
            group_rank=rank,
            group_count=len(ranked_groups) if ranked_groups else None,
            group_rank_percentile=rank_percentile,
            rank_delta_1w=_rank_delta(rank_series, RANK_LOOKBACK_SESSIONS["1w"]),
            rank_delta_1m=_rank_delta(rank_series, RANK_LOOKBACK_SESSIONS["1m"]),
            rank_delta_3m=_rank_delta(rank_series, RANK_LOOKBACK_SESSIONS["3m"]),
            rank_delta_6m=_rank_delta(rank_series, RANK_LOOKBACK_SESSIONS["6m"]),
            rs_ratio=rs_ratio,
            rs_momentum=rs_momentum,
            rrg_quadrant=quadrant,
            rrg_recipe=rrg_recipe_manifest(),
            summary=summary,
            evidence=evidence,
            warnings=list(dict.fromkeys(warnings)),
            as_of_date=as_of_date,
            updated_at=datetime.now(UTC).isoformat(),
        )

    return {
        "map": map_manifest(),
        "coverage": coverage,
        "group_count": len(group_to_tickers),
        "ranked_group_count": len(ranked_groups),
        "singleton_group_count": singleton_groups,
        "singleton_group_share": (
            round(singleton_groups / len(group_to_tickers), 4) if group_to_tickers else None
        ),
        "history_sessions_max": max_history_sessions or None,
        "rrg_available": bool(
            not rrg_frames["rs_ratio"].empty and rrg_frames["rs_ratio"].notna().any().any()
        ),
        "warnings": list(dict.fromkeys(history_warnings)),
    }


def _round_optional(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _summary_for(
    *,
    status: str,
    membership: IndustryGroupMembership,
    rank: int | None,
    group_count: int,
    quadrant: str | None,
) -> str:
    if status == "unmapped":
        return "No frozen industry-group membership is available for this ticker."
    if status == "mapped":
        return (
            f"Mapped to GICS proxy group {membership.group_name}, but group RS is unavailable."
        )
    rank_text = (
        f" Group rank {rank} of {group_count}."
        if rank is not None and group_count
        else ""
    )
    quadrant_text = f" RRG quadrant {quadrant}." if quadrant else ""
    return (
        f"Shadow industry-group RS uses the frozen GICS proxy {membership.group_name}."
        f"{rank_text}{quadrant_text} Applied impact remains 0."
    )


def overlay_does_not_change_live_view(view: IndustryGroupRelativeStrengthView) -> bool:
    return view.mode == INDUSTRY_GROUP_RS_MODE and view.applied_impact == 0


def copy_view_with_zero_impact(
    view: IndustryGroupRelativeStrengthView,
) -> IndustryGroupRelativeStrengthView:
    if view.applied_impact == 0:
        return view
    return replace(view, applied_impact=0)


__all__ = [
    "INDUSTRY_GROUP_RS_MODE",
    "IndustryGroupRelativeStrengthView",
    "MIN_HISTORY_SESSIONS_FOR_RS",
    "MIN_HISTORY_SESSIONS_RECOMMENDED",
    "RANK_LOOKBACK_SESSIONS",
    "RRG_MIN_WEEKS",
    "RRG_MOMENTUM_LAG_WEEKS",
    "RRG_WEEKLY_ANCHOR",
    "RRG_ZSCORE_WEEKS",
    "assign_industry_group_relative_strength",
    "build_mapped_industry_group_rs_stub",
    "build_unavailable_industry_group_rs_view",
    "compute_group_avg_rs_frame",
    "compute_group_rank_frame",
    "compute_name_feature_frames",
    "compute_rrg_frame",
    "industry_group_rs_view_from_dict",
    "overlay_does_not_change_live_view",
    "rrg_quadrant",
    "rrg_recipe_manifest",
]
