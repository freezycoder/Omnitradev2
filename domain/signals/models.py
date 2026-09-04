from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

from config.performance import ALL_SIGNAL_STRATEGIES, PERFORMANCE_MODEL_VERSION, SIGNAL_DEDUPE_ENTRY_MOVE_THRESHOLD_PCT


def parse_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def normalize_timestamp(value: str | datetime) -> str:
    return parse_timestamp(value).isoformat()


def signal_date_bucket(value: str | datetime) -> str:
    return parse_timestamp(value).date().isoformat()


def quantize_entry_price(
    entry_price: float | None,
    threshold_pct: float = SIGNAL_DEDUPE_ENTRY_MOVE_THRESHOLD_PCT,
) -> str:
    if entry_price is None:
        return "na"
    if entry_price <= 0:
        return "0.0000"
    bucket_size = max(entry_price * (threshold_pct / 100.0), 0.01)
    quantized = round(round(entry_price / bucket_size) * bucket_size, 4)
    return f"{quantized:.4f}"


def build_dedupe_key(
    *,
    ticker: str,
    strategy_family: str,
    source_quality: str,
    signal_origin: str,
    created_at: str | datetime,
    trade_state: str | None,
    recommendation_label: str,
    entry_price: float | None,
    model_version: str = PERFORMANCE_MODEL_VERSION,
) -> str:
    base = "|".join(
        [
            ticker.upper().strip(),
            strategy_family,
            source_quality,
            signal_origin,
            signal_date_bucket(created_at),
            (trade_state or "na").strip().upper(),
            recommendation_label.strip().upper(),
            quantize_entry_price(entry_price),
            model_version,
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SignalRecord:
    signal_id: str
    dedupe_key: str
    created_at: str
    ticker: str
    company_name: str
    strategy_family: str
    signal_origin: str
    source_quality: str
    model_version: str
    recommendation_label: str
    recommendation_confidence: str
    trade_state: str | None
    holding_period_label: str | None
    score: float
    entry_price: float | None
    target_price: float | None
    stop_loss_price: float | None
    trend_direction: str | None
    setup_type: str | None
    invalidation_note: str | None
    accounting_quality_score: float | None
    shenanigan_risk_score: float | None
    accounting_data_completeness_score: float | None
    accounting_assessment_confidence: str | None
    news_score: float | None
    news_impact: float | None
    feature_snapshot_json: str
    evaluated: int = 0

    def __post_init__(self) -> None:
        if self.strategy_family not in ALL_SIGNAL_STRATEGIES:
            raise ValueError(f"Unsupported strategy_family: {self.strategy_family}")

    @classmethod
    def from_row(cls, row: Any) -> "SignalRecord":
        return cls(
            signal_id=row["signal_id"],
            dedupe_key=row["dedupe_key"],
            created_at=row["created_at"],
            ticker=row["ticker"],
            company_name=row["company_name"] or "",
            strategy_family=row["strategy_family"],
            signal_origin=row["signal_origin"],
            source_quality=row["source_quality"],
            model_version=row["model_version"],
            recommendation_label=row["recommendation_label"],
            recommendation_confidence=row["recommendation_confidence"],
            trade_state=row["trade_state"],
            holding_period_label=row["holding_period_label"],
            score=float(row["score"]),
            entry_price=float(row["entry_price"]) if row["entry_price"] is not None else None,
            target_price=float(row["target_price"]) if row["target_price"] is not None else None,
            stop_loss_price=float(row["stop_loss_price"]) if row["stop_loss_price"] is not None else None,
            trend_direction=row["trend_direction"],
            setup_type=row["setup_type"],
            invalidation_note=row["invalidation_note"],
            accounting_quality_score=float(row["accounting_quality_score"]) if row["accounting_quality_score"] is not None else None,
            shenanigan_risk_score=float(row["shenanigan_risk_score"]) if row["shenanigan_risk_score"] is not None else None,
            accounting_data_completeness_score=float(row["accounting_data_completeness_score"]) if row["accounting_data_completeness_score"] is not None else None,
            accounting_assessment_confidence=row["accounting_assessment_confidence"],
            news_score=float(row["news_score"]) if row["news_score"] is not None else None,
            news_impact=float(row["news_impact"]) if row["news_impact"] is not None else None,
            feature_snapshot_json=row["feature_snapshot_json"],
            evaluated=int(row["evaluated"]),
        )

    def to_db_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def created_at_datetime(self) -> datetime:
        return parse_timestamp(self.created_at)

    @property
    def created_at_date(self) -> date:
        return self.created_at_datetime.date()

    @property
    def feature_snapshot(self) -> dict[str, Any]:
        try:
            return json.loads(self.feature_snapshot_json)
        except Exception:
            return {}


__all__ = [
    "SignalRecord",
    "build_dedupe_key",
    "normalize_timestamp",
    "parse_timestamp",
    "quantize_entry_price",
    "signal_date_bucket",
]
