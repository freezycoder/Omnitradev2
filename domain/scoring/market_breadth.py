from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, Mapping, Sequence
from typing import assert_never

import pandas as pd

from config.market_breadth import (
    BREADTH_MODE,
    BREADTH_RECIPE_VERSION,
    EQUAL_WEIGHT_PROXY_LABEL,
    GATE_AD_DIVERGENCE_SESSIONS,
    GATE_PCT_ABOVE_50DMA_MIN,
    MA_WINDOWS,
    MIN_HISTORY_FOR_200DMA,
    MIN_HISTORY_SESSIONS_RECOMMENDED,
    MIN_PCT_ABOVE_MA_COVERAGE,
    NEW_HIGH_LOW_LOOKBACK_SESSIONS,
    RSP_SYMBOL,
    SPY_SYMBOL,
    breadth_recipe_manifest,
)


GateStatus = Literal["open", "closed", "unknown"]

_OHLCV_CLOSE = "Close"
_OHLCV_VOLUME = "Volume"


@dataclass(frozen=True)
class BreadthGateDecision:
    status: GateStatus
    pct_above_50dma: float | None
    spy_return_nd: float | None
    ad_line_change_nd: float | None
    coverage_50dma: float | None
    reasons: tuple[str, ...]
    recipe_version: str = BREADTH_RECIPE_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class BreadthDailySnapshot:
    as_of: date
    universe_size: int
    names_quoted: int
    advances: int
    declines: int
    unchanged: int
    advance_decline_line: float | None
    ad_line_change_nd: float | None
    up_volume: float | None
    down_volume: float | None
    up_down_volume_ratio: float | None
    pct_above_20dma: float | None
    pct_above_50dma: float | None
    pct_above_200dma: float | None
    coverage_20dma: float | None
    coverage_50dma: float | None
    coverage_200dma: float | None
    spy_return_pct: float | None
    equal_weight_return_pct: float | None
    spy_minus_equal_weight_pct: float | None
    rsp_return_pct: float | None
    spy_minus_rsp_pct: float | None
    cap_vs_equal_weight_proxy: str
    spy_return_nd: float | None
    new_highs_252: int | None
    new_lows_252: int | None
    gate: BreadthGateDecision

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["gate"] = self.gate.to_dict()
        return payload


@dataclass(frozen=True)
class MarketBreadthView:
    mode: str
    status: str
    applied_impact: int
    coverage_score: int
    recipe_version: str
    as_of_date: str | None
    snapshot: dict[str, Any] | None
    gate: dict[str, Any]
    cap_vs_equal_weight_proxy: str
    rsp_available: bool
    summary: str
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BreadthPanel:
    recipe: dict[str, Any]
    universe: tuple[str, ...]
    universe_size: int
    rows: tuple[BreadthDailySnapshot, ...]
    rsp_available: bool
    cap_vs_equal_weight_proxy: str
    history_sessions_max: int
    coverage: dict[str, Any]
    abort_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe": self.recipe,
            "universe": list(self.universe),
            "universe_size": self.universe_size,
            "row_count": len(self.rows),
            "rsp_available": self.rsp_available,
            "cap_vs_equal_weight_proxy": self.cap_vs_equal_weight_proxy,
            "history_sessions_max": self.history_sessions_max,
            "coverage": self.coverage,
            "abort_reasons": list(self.abort_reasons),
            "latest": self.rows[-1].to_dict() if self.rows else None,
        }

    def snapshot_on(self, as_of: date) -> BreadthDailySnapshot | None:
        for row in reversed(self.rows):
            if row.as_of == as_of:
                return row
        return None

    def gate_status_on(self, as_of: date) -> GateStatus:
        snapshot = self.snapshot_on(as_of)
        if snapshot is None:
            return "unknown"
        return snapshot.gate.status


def gate_status_label(status: GateStatus) -> str:
    match status:
        case "open":
            return "open"
        case "closed":
            return "closed"
        case "unknown":
            return "unknown"
        case _ as unreachable:
            assert_never(unreachable)


def evaluate_gate(
    *,
    pct_above_50dma: float | None,
    coverage_50dma: float | None,
    spy_return_nd: float | None,
    ad_line_change_nd: float | None,
) -> BreadthGateDecision:
    reasons: list[str] = []
    if coverage_50dma is None or coverage_50dma < MIN_PCT_ABOVE_MA_COVERAGE:
        reasons.append(
            f"50DMA coverage is {None if coverage_50dma is None else round(coverage_50dma * 100, 1)}%; "
            f"{MIN_PCT_ABOVE_MA_COVERAGE * 100:.0f}% is required to read the gate."
        )
        return BreadthGateDecision(
            status="unknown",
            pct_above_50dma=pct_above_50dma,
            spy_return_nd=spy_return_nd,
            ad_line_change_nd=ad_line_change_nd,
            coverage_50dma=coverage_50dma,
            reasons=tuple(reasons),
        )
    if pct_above_50dma is None or spy_return_nd is None or ad_line_change_nd is None:
        reasons.append("A 10-session SPY return or A/D line change is missing.")
        return BreadthGateDecision(
            status="unknown",
            pct_above_50dma=pct_above_50dma,
            spy_return_nd=spy_return_nd,
            ad_line_change_nd=ad_line_change_nd,
            coverage_50dma=coverage_50dma,
            reasons=tuple(reasons),
        )

    participation_ok = pct_above_50dma >= GATE_PCT_ABOVE_50DMA_MIN
    diverging = spy_return_nd > 0 and ad_line_change_nd < 0
    if not participation_ok:
        reasons.append(
            f"% above 50DMA is {pct_above_50dma:.1f}%, below the frozen {GATE_PCT_ABOVE_50DMA_MIN:.0f}% threshold."
        )
    if diverging:
        reasons.append(
            f"A/D line fell {ad_line_change_nd:.1f} over {GATE_AD_DIVERGENCE_SESSIONS} sessions "
            f"while SPY returned {spy_return_nd:+.2f}%."
        )
    if participation_ok and not diverging:
        reasons.append(
            f"% above 50DMA is {pct_above_50dma:.1f}% and A/D is not diverging versus SPY "
            f"over {GATE_AD_DIVERGENCE_SESSIONS} sessions."
        )
        status: GateStatus = "open"
    else:
        status = "closed"
    return BreadthGateDecision(
        status=status,
        pct_above_50dma=pct_above_50dma,
        spy_return_nd=spy_return_nd,
        ad_line_change_nd=ad_line_change_nd,
        coverage_50dma=coverage_50dma,
        reasons=tuple(reasons),
    )


def build_breadth_panel(
    stock_histories: Mapping[str, pd.DataFrame],
    spy_history: pd.DataFrame,
    *,
    universe: Sequence[str] | None = None,
    rsp_history: pd.DataFrame | None = None,
) -> BreadthPanel:
    requested = tuple(
        dict.fromkeys(
            str(ticker).upper().strip()
            for ticker in (universe if universe is not None else stock_histories)
            if str(ticker).strip()
        )
    )
    closes = _aligned_frame(stock_histories, requested, _OHLCV_CLOSE)
    volumes = _aligned_frame(stock_histories, requested, _OHLCV_VOLUME)
    spy_close = _series(spy_history, _OHLCV_CLOSE)
    rsp_close = _series(rsp_history, _OHLCV_CLOSE) if rsp_history is not None else pd.Series(dtype=float)
    rsp_available = not rsp_close.empty
    proxy = RSP_SYMBOL if rsp_available else EQUAL_WEIGHT_PROXY_LABEL
    history_sessions_max = int(closes.notna().sum(axis=0).max()) if not closes.empty else 0
    universe_size = len(requested)

    if closes.empty or spy_close.empty:
        coverage = _empty_coverage(universe_size, rsp_available=rsp_available)
        abort_reasons = []
        if closes.empty:
            abort_reasons.append("No usable universe close series were supplied.")
        if spy_close.empty:
            abort_reasons.append(f"{SPY_SYMBOL} history is missing; the cap-weight leg of the proxy cannot be built.")
        return BreadthPanel(
            recipe=breadth_recipe_manifest(),
            universe=requested,
            universe_size=universe_size,
            rows=(),
            rsp_available=rsp_available,
            cap_vs_equal_weight_proxy=proxy,
            history_sessions_max=history_sessions_max,
            coverage=coverage,
            abort_reasons=tuple(abort_reasons),
        )

    daily_return = closes.pct_change()
    quoted = daily_return.notna()
    advances = (daily_return > 0).sum(axis=1).astype(int)
    declines = (daily_return < 0).sum(axis=1).astype(int)
    unchanged = ((daily_return == 0) & quoted).sum(axis=1).astype(int)
    names_quoted = quoted.sum(axis=1).astype(int)
    ad_line = (advances - declines).cumsum().astype(float)
    ad_line_change = ad_line.diff(GATE_AD_DIVERGENCE_SESSIONS)

    up_volume = volumes.where(daily_return > 0).sum(axis=1, min_count=1)
    down_volume = volumes.where(daily_return < 0).sum(axis=1, min_count=1)
    up_down_ratio = up_volume / down_volume.replace(0, pd.NA)

    ma_pct: dict[int, pd.Series] = {}
    ma_coverage: dict[int, pd.Series] = {}
    for window in MA_WINDOWS:
        ma = closes.rolling(window=window, min_periods=window).mean()
        valid = ma.notna()
        above = (closes > ma) & valid
        valid_count = valid.sum(axis=1)
        ma_pct[window] = (above.sum(axis=1) / valid_count.replace(0, pd.NA)) * 100.0
        ma_coverage[window] = valid_count / max(universe_size, 1)

    equal_weight_return = daily_return.mean(axis=1, skipna=True) * 100.0
    spy_return = spy_close.pct_change() * 100.0
    spy_return, equal_weight_return = spy_return.align(equal_weight_return, join="outer")
    spy_minus_ew = spy_return - equal_weight_return
    spy_return_nd = spy_close.pct_change(GATE_AD_DIVERGENCE_SESSIONS) * 100.0

    rsp_return = rsp_close.pct_change() * 100.0 if rsp_available else pd.Series(dtype=float)
    spy_minus_rsp = (spy_return - rsp_return) if rsp_available else pd.Series(dtype=float)

    roll_max = closes.rolling(NEW_HIGH_LOW_LOOKBACK_SESSIONS, min_periods=NEW_HIGH_LOW_LOOKBACK_SESSIONS).max()
    roll_min = closes.rolling(NEW_HIGH_LOW_LOOKBACK_SESSIONS, min_periods=NEW_HIGH_LOW_LOOKBACK_SESSIONS).min()
    new_highs = ((closes >= roll_max) & roll_max.notna()).sum(axis=1).astype(int)
    new_lows = ((closes <= roll_min) & roll_min.notna()).sum(axis=1).astype(int)
    highs_ready = roll_max.notna().sum(axis=1) > 0

    index = closes.index.union(spy_close.index).sort_values()
    rows: list[BreadthDailySnapshot] = []
    for stamp in index:
        as_of = pd.Timestamp(stamp).tz_localize(None).date() if pd.Timestamp(stamp).tzinfo else pd.Timestamp(stamp).date()
        coverage_50 = _optional_float(ma_coverage[50].get(stamp))
        pct_50 = _optional_float(ma_pct[50].get(stamp))
        spy_nd = _optional_float(spy_return_nd.get(stamp))
        ad_change = _optional_float(ad_line_change.get(stamp))
        gate = evaluate_gate(
            pct_above_50dma=pct_50,
            coverage_50dma=coverage_50,
            spy_return_nd=spy_nd,
            ad_line_change_nd=ad_change,
        )
        highs_ok = bool(highs_ready.get(stamp, False))
        rows.append(
            BreadthDailySnapshot(
                as_of=as_of,
                universe_size=universe_size,
                names_quoted=int(names_quoted.get(stamp, 0) or 0),
                advances=int(advances.get(stamp, 0) or 0),
                declines=int(declines.get(stamp, 0) or 0),
                unchanged=int(unchanged.get(stamp, 0) or 0),
                advance_decline_line=_optional_float(ad_line.get(stamp)),
                ad_line_change_nd=ad_change,
                up_volume=_optional_float(up_volume.get(stamp)),
                down_volume=_optional_float(down_volume.get(stamp)),
                up_down_volume_ratio=_optional_float(up_down_ratio.get(stamp)),
                pct_above_20dma=_optional_float(ma_pct[20].get(stamp)),
                pct_above_50dma=pct_50,
                pct_above_200dma=_optional_float(ma_pct[200].get(stamp)),
                coverage_20dma=_optional_float(ma_coverage[20].get(stamp)),
                coverage_50dma=coverage_50,
                coverage_200dma=_optional_float(ma_coverage[200].get(stamp)),
                spy_return_pct=_optional_float(spy_return.get(stamp)),
                equal_weight_return_pct=_optional_float(equal_weight_return.get(stamp)),
                spy_minus_equal_weight_pct=_optional_float(spy_minus_ew.get(stamp)),
                rsp_return_pct=_optional_float(rsp_return.get(stamp)) if rsp_available else None,
                spy_minus_rsp_pct=_optional_float(spy_minus_rsp.get(stamp)) if rsp_available else None,
                cap_vs_equal_weight_proxy=proxy,
                spy_return_nd=spy_nd,
                new_highs_252=int(new_highs.get(stamp, 0) or 0) if highs_ok else None,
                new_lows_252=int(new_lows.get(stamp, 0) or 0) if highs_ok else None,
                gate=gate,
            )
        )

    coverage = summarize_panel_coverage(rows, universe_size=universe_size, rsp_available=rsp_available)
    coverage["history_sessions_max"] = history_sessions_max
    coverage["below_recommended_history"] = history_sessions_max < MIN_HISTORY_SESSIONS_RECOMMENDED
    abort_reasons = panel_abort_reasons(
        rows,
        coverage=coverage,
        history_sessions_max=history_sessions_max,
        spy_available=not spy_close.empty,
    )
    return BreadthPanel(
        recipe=breadth_recipe_manifest(),
        universe=requested,
        universe_size=universe_size,
        rows=tuple(rows),
        rsp_available=rsp_available,
        cap_vs_equal_weight_proxy=proxy,
        history_sessions_max=history_sessions_max,
        coverage=coverage,
        abort_reasons=abort_reasons,
    )


def summarize_panel_coverage(
    rows: Sequence[BreadthDailySnapshot],
    *,
    universe_size: int,
    rsp_available: bool,
) -> dict[str, Any]:
    evaluable_50 = [row for row in rows if row.coverage_50dma is not None]
    evaluable_200 = [row for row in rows if row.coverage_200dma is not None]
    open_days = sum(row.gate.status == "open" for row in rows)
    closed_days = sum(row.gate.status == "closed" for row in rows)
    unknown_days = sum(row.gate.status == "unknown" for row in rows)
    mean_coverage_20 = _mean([row.coverage_20dma for row in rows if row.coverage_20dma is not None])
    mean_coverage_50 = _mean([row.coverage_50dma for row in evaluable_50])
    mean_coverage_200 = _mean([row.coverage_200dma for row in evaluable_200])
    quoted_share = _mean(
        [row.names_quoted / max(universe_size, 1) for row in rows if universe_size]
    )
    return {
        "universe_size": universe_size,
        "session_count": len(rows),
        "mean_quoted_share": quoted_share,
        "mean_coverage_20dma": mean_coverage_20,
        "mean_coverage_50dma": mean_coverage_50,
        "mean_coverage_200dma": mean_coverage_200,
        "meets_minimum_coverage": (
            mean_coverage_50 is not None
            and mean_coverage_50 >= MIN_PCT_ABOVE_MA_COVERAGE
            and mean_coverage_200 is not None
            and mean_coverage_200 >= MIN_PCT_ABOVE_MA_COVERAGE
        ),
        "history_sessions_recommended": MIN_HISTORY_SESSIONS_RECOMMENDED,
        "below_recommended_history": False,  # filled by caller with history_sessions_max
        "gate_open_days": open_days,
        "gate_closed_days": closed_days,
        "gate_unknown_days": unknown_days,
        "rsp_available": rsp_available,
        "cap_vs_equal_weight_proxy": RSP_SYMBOL if rsp_available else EQUAL_WEIGHT_PROXY_LABEL,
    }


def panel_abort_reasons(
    rows: Sequence[BreadthDailySnapshot],
    *,
    coverage: Mapping[str, Any],
    history_sessions_max: int,
    spy_available: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not spy_available:
        reasons.append(f"{SPY_SYMBOL} history is missing.")
    if not rows:
        reasons.append("The daily breadth panel is empty.")
    if history_sessions_max < MIN_HISTORY_FOR_200DMA:
        reasons.append(
            f"Longest overlapping history is {history_sessions_max} sessions; "
            f"{MIN_HISTORY_FOR_200DMA} are required for a 200 DMA."
        )
    if not coverage.get("meets_minimum_coverage"):
        coverage_50 = coverage.get("mean_coverage_50dma")
        coverage_200 = coverage.get("mean_coverage_200dma")
        reasons.append(
            f"%above-MA coverage is 50DMA={_pct_label(coverage_50)} / "
            f"200DMA={_pct_label(coverage_200)}; both must average "
            f"{MIN_PCT_ABOVE_MA_COVERAGE * 100:.0f}% of the universe."
        )
    return tuple(reasons)


def build_market_breadth_view(panel: BreadthPanel) -> MarketBreadthView:
    latest = panel.rows[-1] if panel.rows else None
    warnings = list(panel.abort_reasons)
    if not panel.rsp_available:
        warnings.append(
            f"{RSP_SYMBOL} history was unavailable; cap-weight versus equal-weight uses "
            f"{EQUAL_WEIGHT_PROXY_LABEL} constructed from the scanned universe."
        )
    if latest is None:
        return MarketBreadthView(
            mode=BREADTH_MODE,
            status="unavailable",
            applied_impact=0,
            coverage_score=0,
            recipe_version=BREADTH_RECIPE_VERSION,
            as_of_date=None,
            snapshot=None,
            gate=evaluate_gate(
                pct_above_50dma=None,
                coverage_50dma=None,
                spy_return_nd=None,
                ad_line_change_nd=None,
            ).to_dict(),
            cap_vs_equal_weight_proxy=panel.cap_vs_equal_weight_proxy,
            rsp_available=panel.rsp_available,
            summary="Universe participation metrics are unavailable.",
            warnings=list(dict.fromkeys(warnings)),
            updated_at=datetime.now(UTC).isoformat(),
        )

    coverage_score = int(
        round(
            min(
                100.0,
                100.0
                * (
                    (latest.coverage_50dma or 0.0) * 0.6
                    + (latest.coverage_200dma or 0.0) * 0.4
                ),
            )
        )
    )
    gate_status = latest.gate.status
    match gate_status:
        case "open":
            summary = (
                "Universe participation is constructive on the frozen gate "
                "(% above 50DMA and A/D not diverging versus SPY). "
                "This does not change live recommendations."
            )
            status = "constructive"
        case "closed":
            summary = (
                "Universe participation fails the frozen gate. Single-name shadow hits "
                "should be treated as unconfirmed. This does not change live recommendations."
            )
            status = "cautious"
        case "unknown":
            summary = (
                "Universe participation cannot be read on the frozen gate because coverage "
                "or the 10-session A/D versus SPY inputs are missing."
            )
            status = "unavailable"
        case _ as unreachable:
            assert_never(unreachable)

    evidence = [
        f"Advances {latest.advances} / declines {latest.declines} with A/D line "
        f"{_fmt(latest.advance_decline_line)}.",
        f"% above 20/50/200 DMA: {_fmt(latest.pct_above_20dma)} / "
        f"{_fmt(latest.pct_above_50dma)} / {_fmt(latest.pct_above_200dma)}.",
        (
            f"{SPY_SYMBOL} versus equal-weight universe: {_fmt(latest.spy_minus_equal_weight_pct, signed=True)} pp."
            if not panel.rsp_available
            else (
                f"{SPY_SYMBOL} versus {RSP_SYMBOL}: {_fmt(latest.spy_minus_rsp_pct, signed=True)} pp; "
                f"versus equal-weight universe: {_fmt(latest.spy_minus_equal_weight_pct, signed=True)} pp."
            )
        ),
        f"Frozen gate is {gate_status_label(gate_status)}.",
    ]
    return MarketBreadthView(
        mode=BREADTH_MODE,
        status=status,
        applied_impact=0,
        coverage_score=coverage_score,
        recipe_version=BREADTH_RECIPE_VERSION,
        as_of_date=latest.as_of.isoformat(),
        snapshot=latest.to_dict(),
        gate=latest.gate.to_dict(),
        cap_vs_equal_weight_proxy=panel.cap_vs_equal_weight_proxy,
        rsp_available=panel.rsp_available,
        summary=summary,
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings + list(latest.gate.reasons))),
        updated_at=datetime.now(UTC).isoformat(),
    )


def _aligned_frame(
    histories: Mapping[str, pd.DataFrame],
    tickers: Sequence[str],
    column: str,
) -> pd.DataFrame:
    series_map: dict[str, pd.Series] = {}
    for ticker in tickers:
        history = histories.get(ticker)
        series = _series(history, column) if history is not None else pd.Series(dtype=float)
        if not series.empty:
            series_map[ticker] = series
    if not series_map:
        return pd.DataFrame()
    frame = pd.DataFrame(series_map)
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame.sort_index()


def _series(history: pd.DataFrame | None, column: str) -> pd.Series:
    if history is None or history.empty or column not in history.columns:
        return pd.Series(dtype=float)
    series = pd.to_numeric(history[column], errors="coerce").dropna().sort_index()
    if series.empty:
        return pd.Series(dtype=float)
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    number = float(value)
    if number != number:  # NaN
        return None
    return number


def _mean(values: Sequence[float | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 6)


def _pct_label(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _fmt(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    if signed:
        return f"{value:+.2f}"
    return f"{value:.2f}"


def _empty_coverage(universe_size: int, *, rsp_available: bool) -> dict[str, Any]:
    return {
        "universe_size": universe_size,
        "session_count": 0,
        "mean_quoted_share": None,
        "mean_coverage_20dma": None,
        "mean_coverage_50dma": None,
        "mean_coverage_200dma": None,
        "meets_minimum_coverage": False,
        "history_sessions_recommended": MIN_HISTORY_SESSIONS_RECOMMENDED,
        "history_sessions_max": 0,
        "below_recommended_history": True,
        "gate_open_days": 0,
        "gate_closed_days": 0,
        "gate_unknown_days": 0,
        "rsp_available": rsp_available,
        "cap_vs_equal_weight_proxy": RSP_SYMBOL if rsp_available else EQUAL_WEIGHT_PROXY_LABEL,
    }


__all__ = [
    "BreadthDailySnapshot",
    "BreadthGateDecision",
    "BreadthPanel",
    "GateStatus",
    "MarketBreadthView",
    "build_breadth_panel",
    "build_market_breadth_view",
    "evaluate_gate",
    "gate_status_label",
    "panel_abort_reasons",
    "summarize_panel_coverage",
]
