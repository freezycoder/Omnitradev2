from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class ScannerThresholdConfig:
    min_short_term_scan_score: int = 55
    min_long_term_scan_score: int = 65
    min_short_results: int = 5
    min_long_results: int = 5


@dataclass(frozen=True)
class ExecutionThresholdConfig:
    min_execution_score: int = 70
    execution_pullback_pct: float = 0.50


@dataclass(frozen=True)
class ThresholdSet:
    """Single object that can be copied with overrides during research sweeps."""

    scanner: ScannerThresholdConfig = field(default_factory=ScannerThresholdConfig)
    execution: ExecutionThresholdConfig = field(default_factory=ExecutionThresholdConfig)

    def with_scanner_overrides(self, **overrides: object) -> "ThresholdSet":
        return replace(self, scanner=replace(self.scanner, **overrides))

    def with_execution_overrides(self, **overrides: object) -> "ThresholdSet":
        return replace(self, execution=replace(self.execution, **overrides))


DEFAULT_SCANNER_THRESHOLDS = ScannerThresholdConfig()
DEFAULT_EXECUTION_THRESHOLDS = ExecutionThresholdConfig()
DEFAULT_THRESHOLD_SET = ThresholdSet(
    scanner=DEFAULT_SCANNER_THRESHOLDS,
    execution=DEFAULT_EXECUTION_THRESHOLDS,
)


__all__ = [
    "DEFAULT_EXECUTION_THRESHOLDS",
    "DEFAULT_SCANNER_THRESHOLDS",
    "DEFAULT_THRESHOLD_SET",
    "ExecutionThresholdConfig",
    "ScannerThresholdConfig",
    "ThresholdSet",
]
