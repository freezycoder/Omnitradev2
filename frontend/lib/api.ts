import { applyScanTradeLevelPolicy } from "@/lib/tradeLevels";
import { applyShortTermSignalBuckets } from "@/lib/signalBuckets";


export type ApiRecord = Record<string, unknown>;

export type ApiCapabilities = {
  write_mode: "read_only" | "local";
  user_mutations_enabled: boolean;
  performance_log_mutations_enabled: boolean;
  watchlist_mutations_enabled: boolean;
  message: string;
};

export const READ_ONLY_API_CAPABILITIES: ApiCapabilities = {
  write_mode: "read_only",
  user_mutations_enabled: false,
  performance_log_mutations_enabled: false,
  watchlist_mutations_enabled: false,
  message: "Write access could not be verified, so mutation controls are disabled."
};

export type ScanPayload = {
  updated_at?: string;
  source?: string;
  universe_name?: string;
  universe?: string[];
  market_stats?: ApiRecord;
  long_term?: ApiRecord[];
  short_term?: ApiRecord[];
  market_rows?: ApiRecord[];
  failures?: string[];
  api_note?: string;
  data_status?: ApiRecord;
};

export type RefreshStatusPayload = {
  refresh_status?: "idle" | "running" | "complete" | "failed";
  status?: "idle" | "running" | "complete" | "failed";
  job_id?: string;
  universe?: string;
  data_mode?: string;
  started_at?: string;
  finished_at?: string;
  updated_at?: string;
  source?: string;
  message?: string;
  error?: string;
};

export type TickerPayload = ApiRecord;

export type PortfolioPayload = {
  strategy_v1_execution?: ApiRecord;
  strategy_v1_portfolio?: ApiRecord;
  strategy_v1_benchmark_portfolio?: ApiRecord;
  strategy_v1_portfolio_pnl?: ApiRecord;
  strategy_v1_benchmark_portfolio_pnl?: ApiRecord;
  strategy_v1_capture_metrics?: ApiRecord;
  strategy_v1_strategy_history?: ApiRecord;
  strategy_v1_portfolio_history?: ApiRecord;
  trigger_sensitivity?: ApiRecord;
};

export type PerformanceLabPayload = {
  overall?: ApiRecord;
  performance_assumptions?: ApiRecord;
  risk_context?: ApiRecord;
  by_strategy?: Record<string, ApiRecord>;
  score_buckets?: ApiRecord[];
  edge_filter?: ApiRecord;
  edge_discovery?: ApiRecord;
  entry_trigger_lab?: ApiRecord;
  strategy_v1_execution?: ApiRecord;
  trigger_sensitivity?: ApiRecord;
  recent_outcomes?: ApiRecord[];
};

export type PerformanceLogInput = {
  ticker: string;
  strategy_family: "short_term_day" | "short_term_swing";
  opened_on: string;
  closed_on: string;
  score: number;
  entry_price: number;
  exit_price: number;
  status: "hit_target" | "hit_stop" | "expired";
};

export type LongTermPerformancePayload = {
  overall?: ApiRecord;
  by_horizon?: ApiRecord[];
  by_score_bucket?: ApiRecord[];
  by_recommendation?: ApiRecord[];
  by_trend?: ApiRecord[];
  by_accounting_risk?: ApiRecord[];
  recent_resolved?: ApiRecord[];
  open_signals?: ApiRecord[];
  horizon_definitions?: ApiRecord[];
};

export type CalibrationPayload = {
  summary?: ApiRecord;
  active_thresholds?: ApiRecord;
  edge_weights?: ApiRecord;
  cost_model?: ApiRecord;
  score_buckets?: ApiRecord[];
  strategy_comparison?: ApiRecord[];
  regime_comparison?: ApiRecord[];
  confidence_analysis?: ApiRecord[];
  accounting_risk_analysis?: ApiRecord[];
  edge_filter?: ApiRecord;
  diagnostics?: ApiRecord;
  research_calibration?: ApiRecord;
  alternative_signal_analysis?: ApiRecord;
  relative_strength_analysis?: ApiRecord;
  earnings_intelligence_analysis?: ApiRecord;
};

export type WatchlistItem = {
  ticker: string;
  source?: string;
};

const API_BASE = process.env.NEXT_PUBLIC_OMNITRADE_API_URL ?? "http://127.0.0.1:8788";
const OVERVIEW_TIMEOUT_MS = 12_000;
const REFRESH_KICKOFF_TIMEOUT_MS = 12_000;
const REFRESH_POLL_INTERVAL_MS = 5_000;
const REFRESH_POLL_WINDOW_MS = 10 * 60_000;
const SCAN_MAX_AGE_HOURS = 24;
const ACTIONABLE_TRADE_STATES = new Set([
  "ENTER NOW",
  "CONFIRMED BREAKOUT — BUY",
  "CONFIRMED BREAKDOWN — SELL"
]);
const PRICE_LEVEL_FIELDS = [
  "entry_price",
  "target_price",
  "stop_loss_price",
  "breakout_level",
  "breakdown_level",
  "entry",
  "target",
  "stop_loss"
];

function asRecord(value: unknown): ApiRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as ApiRecord) : {};
}

function isActionableRow(row: ApiRecord): boolean {
  const state = String(row.trade_state ?? "").trim().toUpperCase();
  return row.is_actionable_now === true || ACTIONABLE_TRADE_STATES.has(state);
}

function blockedState(status: string): string {
  if (status === "demo") return "DEMO — NOT ACTIONABLE";
  if (status === "unavailable") return "DATA UNAVAILABLE";
  return "STALE — REFRESH REQUIRED";
}

function sanitizeTradeHorizon(value: unknown, status: string, reason: string): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const horizon: ApiRecord = { ...(value as ApiRecord) };
  const originalState = String(horizon.trade_state ?? "").trim();
  if (ACTIONABLE_TRADE_STATES.has(originalState.toUpperCase())) {
    horizon.trade_state = blockedState(status);
    horizon.trade_state_tone = "negative";
    horizon.explanation = reason;
  }
  delete horizon.original_trade_state;
  horizon.is_actionable_now = false;
  horizon.action_block_reason = reason;
  for (const field of PRICE_LEVEL_FIELDS) {
    if (field in horizon) horizon[field] = null;
  }
  return horizon;
}

function sanitizeShortRow(row: ApiRecord, status: string, reason: string): ApiRecord {
  const sanitized: ApiRecord = { ...row };
  if (isActionableRow(sanitized)) {
    sanitized.trade_state = blockedState(status);
    sanitized.trade_state_tone = "negative";
    sanitized.trade_state_explanation = reason;
  }
  delete sanitized.original_trade_state;
  delete sanitized.original_recommendation_label;
  sanitized.is_actionable_now = false;
  sanitized.action_block_reason = reason;
  for (const field of PRICE_LEVEL_FIELDS) {
    if (field in sanitized) sanitized[field] = null;
  }
  sanitized.day_trade = sanitizeTradeHorizon(sanitized.day_trade, status, reason);
  sanitized.swing_trade = sanitizeTradeHorizon(sanitized.swing_trade, status, reason);
  return sanitized;
}

export function applyScanFreshnessPolicy(
  payload: ScanPayload,
  sourceOverride?: string
): ScanPayload {
  payload = applyScanTradeLevelPolicy(payload);
  const existingStatus = asRecord(payload.data_status);
  const source = String(sourceOverride ?? payload.source ?? "unavailable").trim().toLowerCase();
  const capturedMs = payload.updated_at ? Date.parse(payload.updated_at) : Number.NaN;
  let ageSeconds = Number.isFinite(capturedMs) ? (Date.now() - capturedMs) / 1000 : null;
  let timestampValid = ageSeconds !== null;
  if (ageSeconds !== null && ageSeconds < -300) timestampValid = false;
  if (ageSeconds !== null && ageSeconds < 0 && timestampValid) ageSeconds = 0;

  const sourceAllowsActions = source === "live" || source === "cached_real";
  const temporallyFresh = Boolean(
    timestampValid && ageSeconds !== null && ageSeconds <= SCAN_MAX_AGE_HOURS * 3600
  );
  const backendBlocked = existingStatus.is_actionable === false;
  const isActionable = !backendBlocked && sourceAllowsActions && temporallyFresh;

  let status = "fresh";
  let defaultReason: string | null = null;
  if (source === "demo") {
    status = "demo";
    defaultReason = "Demo data is for testing only. Actionable signals and price levels are disabled.";
  } else if (source === "unavailable") {
    status = "unavailable";
    defaultReason = "Market data is unavailable. Actionable signals and price levels are disabled.";
  } else if (!timestampValid) {
    status = "stale";
    defaultReason = "The scan timestamp is missing, invalid, or in the future. Refresh before using any signal.";
  } else if (!temporallyFresh) {
    status = "stale";
    defaultReason = `Scan data is older than ${SCAN_MAX_AGE_HOURS} hours. Actionable signals and price levels are disabled until a fresh scan completes.`;
  } else if (!sourceAllowsActions || backendBlocked) {
    status = String(existingStatus.status ?? "unavailable");
    defaultReason = "This data source is not approved for actionable signals.";
  }
  const blockReason = isActionable
    ? null
    : typeof existingStatus.block_reason === "string"
      ? existingStatus.block_reason
      : defaultReason;

  const originalShortRows = Array.isArray(payload.short_term) ? payload.short_term : [];
  const detectedBlockedCount = originalShortRows.filter(isActionableRow).length;
  const previousBlockedCount =
    typeof existingStatus.blocked_actionable_count === "number"
      ? existingStatus.blocked_actionable_count
      : detectedBlockedCount;
  const shortRows: ApiRecord[] = isActionable
    ? originalShortRows.map((row): ApiRecord => ({ ...row, data_source: source }))
    : originalShortRows.map((row): ApiRecord => ({
        ...sanitizeShortRow(row, status, blockReason ?? "Actionable signals are disabled."),
        data_source: source
      }));
  const longRows = (Array.isArray(payload.long_term) ? payload.long_term : []).map((row) => ({
    ...row,
    ...(!isActionable
      ? {
          tone: "warning",
          is_actionable: false,
          action_block_reason: blockReason
        }
      : {}),
    data_source: source
  }));
  const marketRows = (Array.isArray(payload.market_rows) ? payload.market_rows : []).map((row) => {
    const result: ApiRecord = { ...row, data_source: source };
    const originalState = String(result.trade_state ?? "").trim();
    if (!isActionable && ACTIONABLE_TRADE_STATES.has(originalState.toUpperCase())) {
      result.trade_state = blockedState(status);
      result.action_block_reason = blockReason;
    }
    delete result.original_trade_state;
    return result;
  });
  const stats = { ...asRecord(payload.market_stats) };
  stats.actionable_now = isActionable ? shortRows.filter((row) => row.is_actionable_now === true).length : 0;
  stats.blocked_actionable_count = isActionable ? 0 : previousBlockedCount;

  return applyShortTermSignalBuckets({
    ...payload,
    source,
    market_stats: stats,
    long_term: longRows,
    short_term: shortRows,
    market_rows: marketRows,
    data_status: {
      source,
      captured_at: Number.isFinite(capturedMs) ? new Date(capturedMs).toISOString() : null,
      delivered_at: new Date().toISOString(),
      age_seconds: ageSeconds === null ? null : Math.round(ageSeconds * 10) / 10,
      age_hours: ageSeconds === null ? null : Math.round((ageSeconds / 3600) * 100) / 100,
      max_age_hours: SCAN_MAX_AGE_HOURS,
      status,
      is_stale: status === "stale",
      is_actionable: isActionable,
      blocked_actionable_count: isActionable ? 0 : previousBlockedCount,
      block_reason: blockReason
    }
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {})
    },
    ...init
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail ?? payload);
    } catch {
      detail = await response.text();
    }
    throw new Error(`API ${response.status}: ${detail}`);
  }

  return response.json() as Promise<T>;
}

async function fetchSavedRealScan(universe: "global" | "international"): Promise<ScanPayload | null> {
  try {
    const response = await fetch(`/api/saved-scan?universe=${universe}`, { cache: "no-store" });
    if (!response.ok) return null;
    return response.json() as Promise<ScanPayload>;
  } catch {
    return null;
  }
}

async function overviewRequest(path: string, timeoutMs = OVERVIEW_TIMEOUT_MS): Promise<ScanPayload> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await request<ScanPayload>(path, { signal: controller.signal });
  } finally {
    window.clearTimeout(timeout);
  }
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function fetchRefreshStatus(universe: "global" | "international"): Promise<RefreshStatusPayload> {
  const params = new URLSearchParams({ universe });
  try {
    return await request<RefreshStatusPayload>(`/api/overview/refresh-status?${params.toString()}`);
  } catch {
    return { refresh_status: "idle", status: "idle" };
  }
}

function hasNewerSnapshot(candidate: ScanPayload, previousUpdatedAt?: string): boolean {
  if (!previousUpdatedAt) return true;
  if (!candidate.updated_at) return false;
  const candidateTime = Date.parse(candidate.updated_at);
  const previousTime = Date.parse(previousUpdatedAt);
  if (Number.isFinite(candidateTime) && Number.isFinite(previousTime)) {
    return candidateTime > previousTime;
  }
  return candidate.updated_at !== previousUpdatedAt;
}

async function savedRealScanFallback(
  universe: "global" | "international",
  reason: string
): Promise<ScanPayload | null> {
  const savedRealScan = await fetchSavedRealScan(universe);
  if (!savedRealScan) {
    return null;
  }

  const savedAt = savedRealScan.updated_at
    ? new Date(savedRealScan.updated_at).toLocaleString()
    : "an earlier scan";

  return {
    ...applyScanFreshnessPolicy(savedRealScan, "cached_real"),
    api_note: `${reason} Showing saved real scan context from ${savedAt}. Use Refresh Scan to request newer market data.`
  };
}

async function refreshOverview(
  universe: "global" | "international",
  dataMode: "auto" | "live" | "demo",
  previousUpdatedAt?: string
): Promise<ScanPayload> {
  const refreshParams = new URLSearchParams({
    universe,
    data_mode: dataMode,
    refresh: "true"
  });
  const cachedParams = new URLSearchParams({
    universe,
    data_mode: dataMode,
    refresh: "false"
  });
  let latestPayload: ScanPayload | null = null;

  try {
    const response = await overviewRequest(
      `/api/overview?${refreshParams.toString()}`,
      REFRESH_KICKOFF_TIMEOUT_MS
    );
    latestPayload = applyScanFreshnessPolicy(response);
    if (hasNewerSnapshot(latestPayload, previousUpdatedAt)) {
      return {
        ...latestPayload,
        api_note: latestPayload.api_note ?? "Refresh completed with a newer market snapshot."
      };
    }
  } catch {
    // The API scan continues in its worker thread after the browser timeout.
    // Poll the cached overview until that worker publishes its new snapshot.
  }

  const deadline = Date.now() + REFRESH_POLL_WINDOW_MS;
  while (Date.now() < deadline) {
    const status = await fetchRefreshStatus(universe);
    if (status.refresh_status === "failed" || status.status === "failed") {
      throw new Error(status.error || status.message || "The background refresh failed.");
    }

    try {
      const response = await overviewRequest(`/api/overview?${cachedParams.toString()}`);
      latestPayload = applyScanFreshnessPolicy(response);
      if (hasNewerSnapshot(latestPayload, previousUpdatedAt)) {
        return {
          ...latestPayload,
          api_note: "Refresh completed and the newer market snapshot is now displayed."
        };
      }

      if (status.refresh_status === "complete" || status.status === "complete") {
        return {
          ...latestPayload,
          api_note:
            "The refresh completed, but the API did not publish a newer timestamp. The previous scan remains displayed."
        };
      }
    } catch {
      // A cold or busy API can briefly reject polling while the scan is active.
    }
    await wait(REFRESH_POLL_INTERVAL_MS);
  }

  if (latestPayload) {
    return {
      ...latestPayload,
      api_note: "The refresh did not publish a newer snapshot within ten minutes. The previous scan remains displayed."
    };
  }

  const fallback = await savedRealScanFallback(
    universe,
    "The refresh did not publish a newer snapshot within ten minutes."
  );
  if (fallback) return fallback;
  throw new Error("The refresh did not publish a newer market snapshot.");
}

export async function fetchOverview({
  universe = "global",
  dataMode = "auto",
  refresh = false,
  previousUpdatedAt
}: {
  universe?: "global" | "international";
  dataMode?: "auto" | "live" | "demo";
  refresh?: boolean;
  previousUpdatedAt?: string;
} = {}): Promise<ScanPayload> {
  if (refresh && dataMode !== "demo") {
    return refreshOverview(universe, dataMode, previousUpdatedAt);
  }

  const params = new URLSearchParams({
    universe,
    data_mode: dataMode,
    refresh: String(refresh)
  });
  let payload: ScanPayload;
  try {
    payload = await overviewRequest(`/api/overview?${params.toString()}`);
  } catch (error) {
    if (dataMode !== "demo") {
      const fallback = await savedRealScanFallback(universe, "Render did not answer quickly.");
      if (fallback) {
        return fallback;
      }
    }
    throw error;
  }

  const protectedPayload = applyScanFreshnessPolicy(payload);
  if (dataMode === "demo" || protectedPayload.source !== "demo") {
    return protectedPayload;
  }

  return (
    await savedRealScanFallback(universe, "Render returned demo data.")
  ) ?? protectedPayload;
}

export function fetchTicker(ticker: string, dataMode = "auto"): Promise<TickerPayload> {
  const params = new URLSearchParams({ data_mode: dataMode });
  return request<TickerPayload>(`/api/ticker/${encodeURIComponent(ticker)}?${params.toString()}`);
}

export function fetchPortfolio(): Promise<PortfolioPayload> {
  return request<PortfolioPayload>("/api/portfolio");
}

export function fetchPerformanceLab(): Promise<PerformanceLabPayload> {
  return request<PerformanceLabPayload>("/api/performance-lab");
}

export function fetchApiCapabilities(): Promise<ApiCapabilities> {
  return request<ApiCapabilities>("/api/capabilities");
}

export function logPerformanceOutcome(payload: PerformanceLogInput): Promise<{ status: string; entry: ApiRecord }> {
  return request<{ status: string; entry: ApiRecord }>("/api/performance-log", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function fetchLongTermPerformance(): Promise<LongTermPerformancePayload> {
  return request<LongTermPerformancePayload>("/api/long-term-performance");
}

export function fetchCalibration(): Promise<CalibrationPayload> {
  return request<CalibrationPayload>("/api/calibration");
}

export function fetchWatchlist(): Promise<WatchlistItem[]> {
  return request<WatchlistItem[]>("/api/watchlist");
}

export function addWatchlistItem(ticker: string, source = "frontend"): Promise<{ status: string; watchlist: WatchlistItem[] }> {
  return request<{ status: string; watchlist: WatchlistItem[] }>("/api/watchlist", {
    method: "POST",
    body: JSON.stringify({ ticker, source })
  });
}

export function removeWatchlistItem(ticker: string): Promise<{ status: string; watchlist: WatchlistItem[] }> {
  return request<{ status: string; watchlist: WatchlistItem[] }>(`/api/watchlist/${encodeURIComponent(ticker)}`, {
    method: "DELETE"
  });
}

export type ForecastPoint = {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
};

export type ForecastPayload = {
  ticker: string;
  model: string;
  generated_at: string;
  last_bar: string;
  last_close: number;
  horizon: number;
  lookback: number;
  points: ForecastPoint[];
  bands?: { p10: number[]; p50: number[]; p90: number[] } | null;
  expected_close?: number | null;
  expected_return_pct?: number | null;
  trade_level_diagnostics?: {
    status: "aligned" | "conflict" | "unavailable";
    stop_breach_in_p10?: boolean;
    target_reached_by_p90?: boolean;
    median_horizon_return_pct?: number;
    summary: string;
  } | null;
  disclaimer?: string;
  cached?: boolean;
};

export function fetchForecast(
  ticker: string,
  horizon = 30,
  levels?: { entryPrice: number; stopLossPrice: number; targetPrice: number }
): Promise<ForecastPayload> {
  const params = new URLSearchParams({ horizon: String(horizon) });
  if (levels) {
    params.set("entry_price", String(levels.entryPrice));
    params.set("stop_loss_price", String(levels.stopLossPrice));
    params.set("target_price", String(levels.targetPrice));
  }
  return request<ForecastPayload>(`/api/forecast/${encodeURIComponent(ticker)}?${params.toString()}`);
}
