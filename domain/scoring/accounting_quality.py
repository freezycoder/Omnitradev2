from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from config.accounting import ACCOUNTING_LABEL_RULES, ACCOUNTING_RECOMMENDATION_CAPS, ACCOUNTING_THRESHOLDS
from domain.scoring.long_term import LongTermView


@dataclass
class AccountingQualityView:
    accounting_quality_score: int
    shenanigan_risk_score: int
    accounting_data_completeness_score: int
    accounting_assessment_confidence: str
    label: str
    red_flags: list[str] = field(default_factory=list)
    explanation: str = ""
    limitations_note: str = ""
    penalty_points: int = 0
    long_term_score_penalty: int = 0
    confidence_penalty_steps: int = 0
    recommendation_cap_label: str | None = None
    warning_flag: str = ""
    metrics: dict[str, float | None] = field(default_factory=dict)
    piotroski_score: int | None = None
    piotroski_available_checks: int = 0
    piotroski_label: str = "Unavailable"
    long_term_score_adjustment: int = 0


def _clamp_score(score: int) -> int:
    return max(0, min(100, score))


def _pick_label(score: int) -> str:
    for minimum_score, label in ACCOUNTING_LABEL_RULES:
        if score >= minimum_score:
            return label
    return ACCOUNTING_LABEL_RULES[-1][1]


def _completeness_confidence(completeness_score: int, available_high: int, available_medium: int) -> str:
    if completeness_score >= 80 and available_high >= 3:
        return "High"
    if completeness_score >= 60 and (available_high >= 2 or available_medium >= 3):
        return "Moderate"
    if completeness_score >= 35:
        return "Low"
    return "Very Low"


def _pct_change(previous: float | None, current: float | None) -> float | None:
    if previous is None or current is None:
        return None
    if abs(previous) < 1e-9:
        return None
    return (current / previous) - 1


def _coerce_series(values: list[Any] | None) -> list[float]:
    series: list[float] = []
    for value in values or []:
        if isinstance(value, (int, float)):
            series.append(float(value))
    return series


def _latest(series: list[float]) -> float | None:
    return series[-1] if series else None


def _previous(series: list[float]) -> float | None:
    return series[-2] if len(series) >= 2 else None


def _penalty_to_score_impact(penalty_points: int) -> int:
    if penalty_points >= 36:
        return 18
    if penalty_points >= 24:
        return 12
    if penalty_points >= 12:
        return 6
    if penalty_points >= 6:
        return 3
    return 0


def _confidence_penalty_steps(risk_score: int) -> int:
    if risk_score >= 80:
        return 2
    if risk_score >= 60:
        return 1
    return 0


def _piotroski_score(statement_metrics: dict[str, Any]) -> tuple[int | None, int]:
    """Calculate only the F-score criteria supported by point-in-time statements."""
    revenue = _coerce_series(statement_metrics.get("revenue"))
    net_income = _coerce_series(statement_metrics.get("net_income"))
    operating_cash_flow = _coerce_series(statement_metrics.get("operating_cash_flow"))
    total_assets = _coerce_series(statement_metrics.get("total_assets"))
    total_debt = _coerce_series(statement_metrics.get("total_debt"))
    current_assets = _coerce_series(statement_metrics.get("current_assets"))
    current_liabilities = _coerce_series(statement_metrics.get("current_liabilities"))
    common_shares = _coerce_series(statement_metrics.get("common_shares"))
    gross_profit = _coerce_series(statement_metrics.get("gross_profit"))

    checks: list[bool] = []
    if net_income and total_assets and total_assets[-1] > 0:
        current_roa = net_income[-1] / total_assets[-1]
        checks.append(current_roa > 0)
        if len(net_income) >= 2 and len(total_assets) >= 2 and total_assets[-2] > 0:
            checks.append(current_roa > net_income[-2] / total_assets[-2])
    if operating_cash_flow:
        checks.append(operating_cash_flow[-1] > 0)
    if operating_cash_flow and net_income:
        checks.append(operating_cash_flow[-1] > net_income[-1])
    if len(total_debt) >= 2 and len(total_assets) >= 2 and min(total_assets[-2:]) > 0:
        checks.append(total_debt[-1] / total_assets[-1] < total_debt[-2] / total_assets[-2])
    if (
        len(current_assets) >= 2
        and len(current_liabilities) >= 2
        and min(current_liabilities[-2:]) > 0
    ):
        checks.append(current_assets[-1] / current_liabilities[-1] > current_assets[-2] / current_liabilities[-2])
    if len(common_shares) >= 2:
        checks.append(common_shares[-1] <= common_shares[-2])
    if len(gross_profit) >= 2 and len(revenue) >= 2 and min(revenue[-2:]) > 0:
        checks.append(gross_profit[-1] / revenue[-1] > gross_profit[-2] / revenue[-2])
    if len(revenue) >= 2 and len(total_assets) >= 2 and min(total_assets[-2:]) > 0:
        checks.append(revenue[-1] / total_assets[-1] > revenue[-2] / total_assets[-2])

    if len(checks) < 5:
        return None, len(checks)
    return sum(checks), len(checks)


def _cap_label_for_risk(risk_score: int) -> str | None:
    for minimum_risk, label, _ in ACCOUNTING_RECOMMENDATION_CAPS:
        if risk_score >= minimum_risk:
            return label
    return None


def build_accounting_quality_view(
    fundamentals: dict[str, Any],
    statement_metrics: dict[str, Any] | None,
) -> AccountingQualityView:
    thresholds = ACCOUNTING_THRESHOLDS
    score = thresholds.base_quality_score
    penalty_points = 0
    red_flags: list[str] = []
    metrics: dict[str, float | None] = {}
    observed_checks = 0
    available_high_confidence_checks = 0
    available_medium_confidence_checks = 0
    available_low_confidence_checks = 0

    statement_metrics = statement_metrics or {}
    piotroski_score, piotroski_available_checks = _piotroski_score(statement_metrics)
    revenue = _coerce_series(statement_metrics.get("revenue"))
    net_income = _coerce_series(statement_metrics.get("net_income"))
    operating_cash_flow = _coerce_series(statement_metrics.get("operating_cash_flow"))
    free_cash_flow = _coerce_series(statement_metrics.get("free_cash_flow"))
    receivables = _coerce_series(statement_metrics.get("receivables"))
    total_assets = _coerce_series(statement_metrics.get("total_assets"))
    operating_expense = _coerce_series(statement_metrics.get("operating_expense"))
    goodwill = _coerce_series(statement_metrics.get("goodwill"))
    intangibles = _coerce_series(statement_metrics.get("intangibles"))
    total_debt = _coerce_series(statement_metrics.get("total_debt"))
    special_items = _coerce_series(statement_metrics.get("special_items"))

    check_weights = {
        "cash_conversion": ("high", 16),
        "fcf_conversion": ("high", 12),
        "receivables_growth": ("high", 14),
        "dso_trend": ("high", 10),
        "expense_deferral": ("medium", 12),
        "goodwill_ratio": ("medium", 10),
        "acquisition_growth": ("medium", 8),
        "special_items": ("low", 8),
        "debt_growth": ("high", 14),
        "debt_to_ocf": ("high", 10),
        "debt_to_equity_overlay": ("low", 6),
    }
    total_possible_weight = sum(weight for _, weight in check_weights.values())
    available_weight = 0

    def mark_available(check_name: str) -> None:
        nonlocal available_weight, available_high_confidence_checks, available_medium_confidence_checks, available_low_confidence_checks
        tier, weight = check_weights[check_name]
        available_weight += weight
        if tier == "high":
            available_high_confidence_checks += 1
        elif tier == "medium":
            available_medium_confidence_checks += 1
        else:
            available_low_confidence_checks += 1

    def apply_penalty(points: int, message: str) -> None:
        nonlocal score, penalty_points
        score -= points
        penalty_points += points
        if message not in red_flags:
            red_flags.append(message)

    latest_revenue = _latest(revenue)
    previous_revenue = _previous(revenue)
    latest_net_income = _latest(net_income)
    latest_ocf = _latest(operating_cash_flow)
    latest_fcf = _latest(free_cash_flow)
    latest_receivables = _latest(receivables)
    previous_receivables = _previous(receivables)
    latest_assets = _latest(total_assets)
    previous_assets = _previous(total_assets)
    latest_opex = _latest(operating_expense)
    previous_opex = _previous(operating_expense)
    latest_goodwill = _latest(goodwill)
    latest_intangibles = _latest(intangibles)
    previous_goodwill = _previous(goodwill)
    previous_intangibles = _previous(intangibles)
    latest_debt = _latest(total_debt)
    previous_debt = _previous(total_debt)

    if latest_net_income and latest_net_income > 0 and latest_ocf is not None:
        observed_checks += 1
        mark_available("cash_conversion")
        cash_conversion = latest_ocf / latest_net_income
        metrics["cash_conversion"] = cash_conversion
        if latest_ocf <= 0 or cash_conversion < thresholds.cash_conversion_severe:
            apply_penalty(16, "Operating cash flow is not supporting reported earnings.")
        elif cash_conversion < thresholds.cash_conversion_warning:
            apply_penalty(8, "Cash conversion versus net income is weaker than ideal.")

    if latest_net_income and latest_net_income > 0 and latest_fcf is not None:
        observed_checks += 1
        mark_available("fcf_conversion")
        fcf_conversion = latest_fcf / latest_net_income
        metrics["fcf_conversion"] = fcf_conversion
        if latest_fcf <= 0 or fcf_conversion < thresholds.fcf_conversion_severe:
            apply_penalty(12, "Free cash flow conversion is poor relative to reported earnings.")
        elif fcf_conversion < thresholds.fcf_conversion_warning:
            apply_penalty(6, "Free cash flow is trailing reported earnings.")

    revenue_growth = _pct_change(previous_revenue, latest_revenue)
    receivables_growth = _pct_change(previous_receivables, latest_receivables)
    if revenue_growth is not None and receivables_growth is not None:
        observed_checks += 1
        mark_available("receivables_growth")
        metrics["revenue_growth"] = revenue_growth
        metrics["receivables_growth"] = receivables_growth
        growth_gap = receivables_growth - revenue_growth
        metrics["receivables_growth_gap"] = growth_gap
        if growth_gap > thresholds.receivables_growth_gap_severe:
            apply_penalty(12, "Receivables are growing materially faster than revenue, which can point to aggressive revenue recognition.")
        elif growth_gap > thresholds.receivables_growth_gap_warning:
            apply_penalty(6, "Receivables are outgrowing revenue, which warrants more skepticism on revenue quality.")

    if all(value is not None for value in (latest_revenue, previous_revenue, latest_receivables, previous_receivables)) and latest_revenue and previous_revenue:
        observed_checks += 1
        mark_available("dso_trend")
        latest_dso = latest_receivables / (latest_revenue / 365)
        previous_dso = previous_receivables / (previous_revenue / 365)
        dso_change = _pct_change(previous_dso, latest_dso)
        metrics["dso"] = latest_dso
        metrics["dso_change"] = dso_change
        if dso_change is not None:
            if dso_change > thresholds.dso_growth_severe:
                apply_penalty(10, "Days sales outstanding is rising sharply, which can indicate collection quality is slipping.")
            elif dso_change > thresholds.dso_growth_warning:
                apply_penalty(5, "Days sales outstanding is drifting higher.")

    asset_growth = _pct_change(previous_assets, latest_assets)
    opex_growth = _pct_change(previous_opex, latest_opex)
    if asset_growth is not None and revenue_growth is not None and opex_growth is not None:
        observed_checks += 1
        mark_available("expense_deferral")
        metrics["asset_growth"] = asset_growth
        metrics["operating_expense_growth"] = opex_growth
        asset_gap = asset_growth - revenue_growth
        metrics["asset_growth_gap"] = asset_gap
        if asset_gap > thresholds.asset_growth_gap_severe and opex_growth < revenue_growth - 0.05:
            apply_penalty(10, "Asset growth is outrunning revenue while expenses stay unusually subdued, which can signal cost deferral.")
        elif asset_gap > thresholds.asset_growth_gap_warning and opex_growth < revenue_growth:
            apply_penalty(5, "Balance-sheet growth is outpacing the business more than operating expenses suggest.")

    if latest_assets and latest_assets > 0:
        goodwill_intangibles = (latest_goodwill or 0.0) + (latest_intangibles or 0.0)
        goodwill_ratio = goodwill_intangibles / latest_assets
        metrics["goodwill_intangibles_ratio"] = goodwill_ratio
        observed_checks += 1
        mark_available("goodwill_ratio")
        if goodwill_ratio > thresholds.goodwill_asset_ratio_severe:
            apply_penalty(10, "Goodwill and intangibles make up a large share of the asset base, which raises roll-up risk.")
        elif goodwill_ratio > thresholds.goodwill_asset_ratio_warning:
            apply_penalty(5, "Goodwill and intangibles are elevated relative to total assets.")

        acquisition_asset_growth = _pct_change(
            (previous_goodwill or 0.0) + (previous_intangibles or 0.0),
            goodwill_intangibles,
        )
        if acquisition_asset_growth is not None and revenue_growth is not None:
            observed_checks += 1
            mark_available("acquisition_growth")
            metrics["acquisition_asset_growth"] = acquisition_asset_growth
            acquisition_gap = acquisition_asset_growth - revenue_growth
            metrics["acquisition_growth_gap"] = acquisition_gap
            if acquisition_gap > thresholds.acquisition_growth_gap_severe:
                apply_penalty(10, "Acquisition-related assets are growing much faster than revenue, which can distort organic performance.")
            elif acquisition_gap > thresholds.acquisition_growth_gap_warning:
                apply_penalty(5, "Acquisition-heavy growth is outpacing the underlying business trend.")

    if special_items:
        observed_checks += 1
        mark_available("special_items")
        materiality_base = max(abs(latest_revenue or 0.0), abs(latest_net_income or 0.0), 1.0)
        recurring_count = sum(
            1 for item in special_items if abs(item) / materiality_base >= thresholds.special_items_materiality_ratio
        )
        metrics["recurring_special_items_count"] = float(recurring_count)
        if recurring_count >= thresholds.repeated_special_items_count + 1:
            apply_penalty(10, "Special or nonrecurring items are showing up repeatedly, which weakens adjustment quality.")
        elif recurring_count >= thresholds.repeated_special_items_count:
            apply_penalty(5, "Nonrecurring adjustments appear often enough to deserve skepticism.")

    debt_growth = _pct_change(previous_debt, latest_debt)
    if debt_growth is not None and revenue_growth is not None:
        observed_checks += 1
        mark_available("debt_growth")
        metrics["debt_growth"] = debt_growth
        debt_gap = debt_growth - revenue_growth
        metrics["debt_growth_gap"] = debt_gap
        if debt_gap > thresholds.debt_growth_gap_severe:
            apply_penalty(12, "Debt is growing much faster than revenue, which contradicts the quality of reported growth.")
        elif debt_gap > thresholds.debt_growth_gap_warning:
            apply_penalty(6, "Debt is rising faster than the business, which adds balance-sheet stress.")

    if latest_debt is not None and latest_ocf and latest_ocf > 0:
        observed_checks += 1
        mark_available("debt_to_ocf")
        debt_to_ocf = latest_debt / latest_ocf
        metrics["debt_to_operating_cash_flow"] = debt_to_ocf
        if debt_to_ocf > thresholds.debt_to_ocf_severe:
            apply_penalty(12, "Debt is heavy relative to operating cash flow.")
        elif debt_to_ocf > thresholds.debt_to_ocf_warning:
            apply_penalty(6, "Debt load looks elevated relative to operating cash flow.")

    debt_to_equity = fundamentals.get("debtToEquity")
    if isinstance(debt_to_equity, (int, float)):
        mark_available("debt_to_equity_overlay")
        metrics["debt_to_equity"] = float(debt_to_equity)
        if debt_to_equity > 250 and penalty_points >= 12:
            apply_penalty(6, "Leverage is elevated and reinforces the broader earnings-quality concerns.")

    completeness_score = _clamp_score(int(round((available_weight / max(total_possible_weight, 1)) * 100)))
    assessment_confidence = _completeness_confidence(
        completeness_score,
        available_high_confidence_checks,
        available_medium_confidence_checks,
    )

    if observed_checks < 3:
        apply_penalty(thresholds.limited_data_penalty, "Statement coverage is limited, so the accounting overlay stays cautious.")
        score = min(score, 74)

    long_term_score_adjustment = 0
    if piotroski_score is not None:
        metrics["piotroski_score"] = float(piotroski_score)
        metrics["piotroski_available_checks"] = float(piotroski_available_checks)
        if piotroski_score >= 7:
            long_term_score_adjustment = 4
        elif piotroski_score <= 3:
            apply_penalty(8, "The Piotroski F-score is weak, indicating broad deterioration across profitability, leverage, or efficiency.")
            long_term_score_adjustment = -4

    accounting_quality_score = _clamp_score(int(round(score)))
    shenanigan_risk_score = _clamp_score(
        int(round((100 - accounting_quality_score) + min(15, len(red_flags) * 3)))
    )
    label = _pick_label(accounting_quality_score)

    if completeness_score < thresholds.limited_visibility_threshold and shenanigan_risk_score < 70:
        label = "Limited Visibility"
    elif completeness_score < thresholds.inconclusive_threshold and shenanigan_risk_score < 60:
        label = "Inconclusive"
    elif (
        label == "Clean Reporting"
        and (completeness_score < thresholds.clean_reporting_min_completeness or assessment_confidence != "High")
    ):
        label = "Generally Acceptable"
    elif label == "Generally Acceptable" and completeness_score < thresholds.generally_acceptable_min_completeness:
        label = "Inconclusive"

    long_term_score_penalty = _penalty_to_score_impact(penalty_points)
    confidence_penalty_steps = _confidence_penalty_steps(shenanigan_risk_score)
    if assessment_confidence == "Low":
        confidence_penalty_steps = max(confidence_penalty_steps, thresholds.low_confidence_penalty_steps)
    elif assessment_confidence == "Very Low":
        confidence_penalty_steps = max(confidence_penalty_steps, thresholds.very_low_confidence_penalty_steps)
    recommendation_cap_label = _cap_label_for_risk(shenanigan_risk_score)
    if piotroski_score is not None and piotroski_score <= 3:
        recommendation_cap_label = "Hold"
    warning_flag = ""
    if shenanigan_risk_score >= thresholds.short_term_warning_risk_threshold:
        warning_flag = f"{label} • review cash conversion and balance-sheet quality before relying on the tape."
    elif assessment_confidence in {"Low", "Very Low"}:
        warning_flag = f"{label} • accounting visibility is limited, so treat the fundamental overlay with caution."

    limitations: list[str] = []
    if completeness_score < thresholds.clean_reporting_min_completeness:
        limitations.append("Key statement fields are missing or incomplete.")
    if assessment_confidence in {"Low", "Very Low"}:
        limitations.append("The accounting conclusion has limited confidence because too few high-confidence checks were available.")
    limitations_note = " ".join(limitations)

    if red_flags:
        explanation = (
            f"{label}. The accounting overlay is flagging "
            + "; ".join(red_flags[:2]).rstrip(".")
            + "."
        )
    elif label in {"Limited Visibility", "Inconclusive"}:
        explanation = (
            f"{label}. Available statements are too incomplete to make a strong accounting-quality conclusion."
        )
    else:
        explanation = (
            f"{label}. Cash conversion, receivables, and balance-sheet trend checks do not currently show major red flags."
        )

    return AccountingQualityView(
        accounting_quality_score=accounting_quality_score,
        shenanigan_risk_score=shenanigan_risk_score,
        accounting_data_completeness_score=completeness_score,
        accounting_assessment_confidence=assessment_confidence,
        label=label,
        red_flags=red_flags[:4],
        explanation=explanation,
        limitations_note=limitations_note,
        penalty_points=penalty_points,
        long_term_score_penalty=long_term_score_penalty,
        confidence_penalty_steps=confidence_penalty_steps,
        recommendation_cap_label=recommendation_cap_label,
        warning_flag=warning_flag,
        metrics=metrics,
        piotroski_score=piotroski_score,
        piotroski_available_checks=piotroski_available_checks,
        piotroski_label=(
            "Strong"
            if piotroski_score is not None and piotroski_score >= 7
            else "Weak"
            if piotroski_score is not None and piotroski_score <= 3
            else "Mixed"
            if piotroski_score is not None
            else "Unavailable"
        ),
        long_term_score_adjustment=long_term_score_adjustment,
    )


def apply_accounting_overlay(view: LongTermView, accounting_view: AccountingQualityView) -> LongTermView:
    if (
        accounting_view.long_term_score_penalty <= 0
        and accounting_view.long_term_score_adjustment == 0
        and not accounting_view.red_flags
    ):
        return view

    risks = list(view.risks)
    summary = view.summary
    if accounting_view.red_flags:
        accounting_risk = f"Accounting quality warning: {accounting_view.red_flags[0]}"
        if accounting_risk not in risks:
            risks.insert(0, accounting_risk)
        summary = f"{view.summary} {accounting_view.label}."

    return replace(
        view,
        score=_clamp_score(
            view.score
            - accounting_view.long_term_score_penalty
            + accounting_view.long_term_score_adjustment
        ),
        risks=risks,
        summary=summary.strip(),
    )


__all__ = [
    "AccountingQualityView",
    "apply_accounting_overlay",
    "build_accounting_quality_view",
]
