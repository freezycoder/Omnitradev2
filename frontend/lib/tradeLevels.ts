import type { ApiRecord, ScanPayload } from "@/lib/api";


const MAX_STOP_DISTANCE_PCT = 35;
const MAX_TARGET_DISTANCE_PCT = 75;
const MAX_ENTRY_DEVIATION_PCT = 25;
const INVALID_TRADE_LEVEL_STATE = "INVALID LEVELS — REVIEW REQUIRED";
const ACTIONABLE_TRADE_STATES = new Set([
  "ENTER NOW",
  "CONFIRMED BREAKOUT — BUY",
  "CONFIRMED BREAKDOWN — SELL"
]);
const BRACKET_FIELDS = ["entry_price", "target_price", "stop_loss_price"] as const;
const DISPLAY_LEVEL_FIELDS = ["entry", "target", "stop_loss"] as const;

type TradeLevelValidation = {
  valid: boolean;
  reason: string | null;
  risk_pct: number | null;
  reward_pct: number | null;
  entry_deviation_pct: number | null;
};

type SanitizedBracket = {
  record: ApiRecord;
  invalid: boolean;
  blockedActionable: boolean;
};

function finiteNumber(value: unknown): number | null {
  if (typeof value === "boolean" || value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function roundMetric(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

export function validateLongTradeLevels({
  entryPrice,
  targetPrice,
  stopLossPrice,
  referencePrice
}: {
  entryPrice: unknown;
  targetPrice: unknown;
  stopLossPrice: unknown;
  referencePrice?: unknown;
}): TradeLevelValidation {
  const entry = finiteNumber(entryPrice);
  const target = finiteNumber(targetPrice);
  const stop = finiteNumber(stopLossPrice);
  if (entry === null || target === null || stop === null) {
    return {
      valid: false,
      reason: "Entry, target, and stop must all be finite numeric prices.",
      risk_pct: null,
      reward_pct: null,
      entry_deviation_pct: null
    };
  }
  if (!(0 < stop && stop < entry && entry < target)) {
    return {
      valid: false,
      reason: "Trade levels must satisfy 0 < stop < entry < target.",
      risk_pct: null,
      reward_pct: null,
      entry_deviation_pct: null
    };
  }

  const riskPct = ((entry - stop) / entry) * 100;
  const rewardPct = ((target - entry) / entry) * 100;
  if (riskPct > MAX_STOP_DISTANCE_PCT) {
    return {
      valid: false,
      reason: `Stop distance exceeds the ${MAX_STOP_DISTANCE_PCT}% safety limit.`,
      risk_pct: roundMetric(riskPct),
      reward_pct: roundMetric(rewardPct),
      entry_deviation_pct: null
    };
  }
  if (rewardPct > MAX_TARGET_DISTANCE_PCT) {
    return {
      valid: false,
      reason: `Target distance exceeds the ${MAX_TARGET_DISTANCE_PCT}% plausibility limit.`,
      risk_pct: roundMetric(riskPct),
      reward_pct: roundMetric(rewardPct),
      entry_deviation_pct: null
    };
  }

  const reference = finiteNumber(referencePrice);
  const entryDeviationPct =
    reference !== null && reference > 0
      ? (Math.abs(entry - reference) / reference) * 100
      : null;
  if (entryDeviationPct !== null && entryDeviationPct > MAX_ENTRY_DEVIATION_PCT) {
    return {
      valid: false,
      reason: `Entry price is more than ${MAX_ENTRY_DEVIATION_PCT}% from the reference price.`,
      risk_pct: roundMetric(riskPct),
      reward_pct: roundMetric(rewardPct),
      entry_deviation_pct: roundMetric(entryDeviationPct)
    };
  }

  return {
    valid: true,
    reason: null,
    risk_pct: roundMetric(riskPct),
    reward_pct: roundMetric(rewardPct),
    entry_deviation_pct: entryDeviationPct === null ? null : roundMetric(entryDeviationPct)
  };
}

function isActionable(record: ApiRecord): boolean {
  const state = String(record.trade_state ?? "").trim().toUpperCase();
  return record.is_actionable_now === true || ACTIONABLE_TRADE_STATES.has(state);
}

function sanitizeBracket(
  source: ApiRecord,
  referencePrice: unknown,
  explanationField: "explanation" | "trade_state_explanation"
): SanitizedBracket {
  const record: ApiRecord = { ...source };
  if (!BRACKET_FIELDS.some((field) => field in record)) {
    return { record, invalid: false, blockedActionable: false };
  }

  const values = BRACKET_FIELDS.map((field) => record[field]);
  const wasActionable = isActionable(record);
  if (values.every((value) => value === null || value === undefined) && !wasActionable) {
    return { record, invalid: false, blockedActionable: false };
  }

  const validation = validateLongTradeLevels({
    entryPrice: record.entry_price,
    targetPrice: record.target_price,
    stopLossPrice: record.stop_loss_price,
    referencePrice
  });
  record.trade_level_validation = validation;
  if (validation.valid) {
    return { record, invalid: false, blockedActionable: false };
  }

  const reason = validation.reason ?? "Trade levels failed validation.";
  for (const field of [...BRACKET_FIELDS, ...DISPLAY_LEVEL_FIELDS]) {
    if (field in record) record[field] = null;
  }
  record.action_block_reason = reason;
  if ("is_actionable_now" in record || wasActionable) record.is_actionable_now = false;
  if (wasActionable) {
    record.trade_state = INVALID_TRADE_LEVEL_STATE;
    record.trade_state_tone = "negative";
    record[explanationField] = reason;
    if ("recommendation_label" in record) record.recommendation_label = INVALID_TRADE_LEVEL_STATE;
    if ("tone" in record) record.tone = "negative";
  }
  return { record, invalid: true, blockedActionable: wasActionable };
}

function primaryHorizonKey(row: ApiRecord): "day_trade" | "swing_trade" | null {
  const label = String(
    row.primary_horizon_label
      ?? row.primary_horizon
      ?? row.expected_holding_period
      ?? row.ranking_bucket
      ?? ""
  ).toLowerCase();
  if (label.includes("5-15") || label.includes("swing")) return "swing_trade";
  if (label.includes("1-2") || label.includes("day")) return "day_trade";
  return null;
}

export function applyScanTradeLevelPolicy(payload: ScanPayload): ScanPayload {
  const invalidRowsBefore = finiteNumber(payload.market_stats?.invalid_trade_level_rows) ?? 0;
  const blockedBefore = finiteNumber(payload.market_stats?.blocked_invalid_level_signals) ?? 0;
  let invalidRowCount = 0;
  let blockedActionableCount = 0;

  const shortRows = (Array.isArray(payload.short_term) ? payload.short_term : []).map((sourceRow) => {
    let row: ApiRecord = { ...sourceRow };
    const referencePrice = row.current_price ?? row.entry_price;
    const primaryHorizon = primaryHorizonKey(row);
    const invalidHorizons = new Set<string>();
    let rowHadInvalidLevels = false;

    for (const horizonKey of ["day_trade", "swing_trade"] as const) {
      const horizon = row[horizonKey];
      if (!horizon || typeof horizon !== "object" || Array.isArray(horizon)) continue;
      const result = sanitizeBracket(horizon as ApiRecord, referencePrice, "explanation");
      row[horizonKey] = result.record;
      if (result.invalid) {
        invalidHorizons.add(horizonKey);
        rowHadInvalidLevels = true;
      }
    }

    const parentResult = sanitizeBracket(row, row.current_price, "trade_state_explanation");
    row = parentResult.record;
    rowHadInvalidLevels = rowHadInvalidLevels || parentResult.invalid;
    let parentBlocked = parentResult.blockedActionable;

    if (primaryHorizon !== null && invalidHorizons.has(primaryHorizon) && !parentResult.invalid) {
      const horizon = row[primaryHorizon] as ApiRecord;
      const reason = String(
        horizon.action_block_reason ?? "The primary trade horizon failed level validation."
      );
      const wasActionable = isActionable(row);
      for (const field of [...BRACKET_FIELDS, ...DISPLAY_LEVEL_FIELDS]) {
        if (field in row) row[field] = null;
      }
      row.action_block_reason = reason;
      row.is_actionable_now = false;
      row.trade_level_validation = {
        valid: false,
        reason,
        risk_pct: null,
        reward_pct: null,
        entry_deviation_pct: null
      };
      if (wasActionable) {
        row.recommendation_label = INVALID_TRADE_LEVEL_STATE;
        row.trade_state = INVALID_TRADE_LEVEL_STATE;
        row.trade_state_tone = "negative";
        row.trade_state_explanation = reason;
        row.tone = "negative";
        parentBlocked = true;
      }
    }

    if (rowHadInvalidLevels) invalidRowCount += 1;
    if (parentBlocked) blockedActionableCount += 1;
    return row;
  });

  return {
    ...payload,
    short_term: shortRows,
    market_stats: {
      ...(payload.market_stats ?? {}),
      invalid_trade_level_rows: Math.max(invalidRowCount, invalidRowsBefore),
      blocked_invalid_level_signals: Math.max(blockedActionableCount, blockedBefore)
    }
  };
}
