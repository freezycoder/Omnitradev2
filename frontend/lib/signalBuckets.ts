import type { ApiRecord, ScanPayload } from "@/lib/api";


export type ShortTermSignalBucket = "active" | "waiting" | "excluded";

export const ACTIVE_BUCKET: ShortTermSignalBucket = "active";
export const WAITING_BUCKET: ShortTermSignalBucket = "waiting";
export const EXCLUDED_BUCKET: ShortTermSignalBucket = "excluded";

const ACTIONABLE_TRADE_STATES = new Set([
  "ENTER NOW",
  "CONFIRMED BREAKOUT — BUY",
  "CONFIRMED BREAKDOWN — SELL"
]);
const WAITING_TRADE_STATES = new Set([
  "WAIT FOR PULLBACK",
  "BREAKOUT WATCH",
  "BREAKDOWN WATCH"
]);
const WAITING_RECOMMENDATIONS = new Set([
  "STRONG SETUP",
  "WATCHLIST"
]);

function normalized(value: unknown): string {
  return String(value ?? "").trim().toUpperCase();
}

export function classifyShortTermSignal(row: ApiRecord): ShortTermSignalBucket {
  const tradeState = normalized(row.trade_state);
  const recommendation = normalized(row.recommendation_label);
  const isBlocked = String(row.action_block_reason ?? "").trim().length > 0;

  if (
    !isBlocked
    && row.is_actionable_now === true
    && ACTIONABLE_TRADE_STATES.has(tradeState)
  ) {
    return ACTIVE_BUCKET;
  }

  if (isBlocked) return EXCLUDED_BUCKET;

  if (
    WAITING_TRADE_STATES.has(tradeState)
    || WAITING_RECOMMENDATIONS.has(recommendation)
  ) {
    return WAITING_BUCKET;
  }

  return EXCLUDED_BUCKET;
}

export function applyShortTermSignalBuckets(payload: ScanPayload): ScanPayload {
  const counts: Record<ShortTermSignalBucket, number> = {
    active: 0,
    waiting: 0,
    excluded: 0
  };
  const rows = (Array.isArray(payload.short_term) ? payload.short_term : []).map((sourceRow) => {
    const row: ApiRecord = { ...sourceRow };
    const bucket = classifyShortTermSignal(row);
    row.signal_bucket = bucket;
    counts[bucket] += 1;
    return row;
  });

  return {
    ...payload,
    short_term: rows,
    market_stats: {
      ...(payload.market_stats ?? {}),
      actionable_now: counts.active,
      short_term_buckets: counts
    }
  };
}
