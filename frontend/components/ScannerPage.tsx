"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartLegend } from "@/components/ChartLegend";
import { DataTable, DataTableColumn } from "@/components/DataTable";
import { LoadingState } from "@/components/LoadingState";
import { MetricCard } from "@/components/MetricCard";
import { ResearchTabs } from "@/components/ResearchTabs";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import { fetchOverview, ScanPayload } from "@/lib/api";
import { asNumber, formatCurrency, formatLargeNumber, formatPct, pickArray, pickRecord, sentenceCase } from "@/lib/format";
import {
  ACTIVE_BUCKET,
  classifyShortTermSignal,
  EXCLUDED_BUCKET,
  ShortTermSignalBucket,
  WAITING_BUCKET
} from "@/lib/signalBuckets";

type Row = Record<string, unknown>;
type ScannerKind = "overview" | "long" | "short" | "international";
type DataMode = "auto" | "live" | "demo";
type SortKey = "score" | "relative" | "earnings" | "ticker" | "market_cap" | "holding";
type RecommendationFilter = "all" | string;
type ShortBucketFilter = "all" | ShortTermSignalBucket;

const ALL_RECOMMENDATIONS: ShortBucketFilter = "all";

const marketColumns: DataTableColumn<Row>[] = [
  { key: "ticker", header: "Ticker", render: (row) => <span className="font-semibold text-white">{String(row.ticker ?? "N/A")}</span> },
  { key: "company_name", header: "Company" },
  { key: "daily_change_pct", header: "Day", align: "right", render: (row) => formatPct(row.daily_change_pct, 2) },
  { key: "long_term_score", header: "Long", align: "right" },
  { key: "short_term_score", header: "Short", align: "right" },
  { key: "relative_strength_score", header: "Rel", align: "right" },
  { key: "earnings_intelligence_score", header: "Earn", align: "right" },
  { key: "trend_direction", header: "Trend", render: (row) => <StatusBadge tone={row.trend_direction === "Bullish" ? "positive" : "neutral"}>{String(row.trend_direction ?? "N/A")}</StatusBadge> },
  { key: "trade_state", header: "State" },
  { key: "rsi", header: "RSI", align: "right" }
];

const longColumns: DataTableColumn<Row>[] = [
  { key: "ticker", header: "Ticker", render: (row) => <span className="font-semibold text-white">{String(row.ticker ?? "N/A")}</span> },
  { key: "company_name", header: "Company" },
  { key: "sector", header: "Sector" },
  { key: "long_term_score", header: "Score", align: "right" },
  { key: "relative_strength_score", header: "Rel", align: "right" },
  { key: "earnings_intelligence_score", header: "Earn", align: "right" },
  { key: "next_earnings_date", header: "Next earnings" },
  { key: "recommendation_label", header: "Recommendation", render: (row) => <StatusBadge tone={recommendationTone(row)}>{String(row.recommendation_label ?? "N/A")}</StatusBadge> },
  { key: "confidence", header: "Confidence" },
  { key: "market_cap", header: "Market Cap", align: "right", render: (row) => formatLargeNumber(row.market_cap) },
  { key: "accounting_label", header: "Accounting" }
];

const shortColumns: DataTableColumn<Row>[] = [
  { key: "ticker", header: "Ticker", render: (row) => <span className="font-semibold text-white">{String(row.ticker ?? "N/A")}</span> },
  { key: "company_name", header: "Company" },
  { key: "short_term_score", header: "Score", align: "right" },
  { key: "relative_strength_score", header: "Rel", align: "right" },
  { key: "earnings_intelligence_score", header: "Earn", align: "right" },
  { key: "days_to_earnings", header: "Earnings", align: "right", render: (row) => row.days_to_earnings === null || row.days_to_earnings === undefined ? "N/A" : `${String(row.days_to_earnings)}d` },
  {
    key: "recommendation_label",
    header: "Recommendation",
    render: (row) => {
      return (
        <StatusBadge tone={recommendationTone(row)}>
          {String(row.recommendation_label ?? "N/A")}
        </StatusBadge>
      );
    }
  },
  { key: "setup_type", header: "Setup" },
  { key: "trade_state", header: "State" },
  { key: "entry_price", header: "Entry", align: "right", render: (row) => blockedPrice(row, "entry_price") },
  { key: "target_price", header: "Target", align: "right", render: (row) => blockedPrice(row, "target_price") },
  { key: "stop_loss_price", header: "Stop", align: "right", render: (row) => blockedPrice(row, "stop_loss_price") }
];

const pageCopy: Record<ScannerKind, { badge: string }> = {
  overview: {
    badge: "Overview"
  },
  long: {
    badge: "Long term"
  },
  short: {
    badge: "Short term"
  },
  international: {
    badge: "International"
  }
};

function blockedPrice(row: Row, key: string) {
  return row.action_block_reason
    ? <span className="text-[var(--amber)]">Blocked</span>
    : formatCurrency(row[key]);
}

function recommendationTone(row: Row): "positive" | "negative" | "warning" | "neutral" | "info" {
  if (row.action_block_reason) return "warning";
  const tone = String(row.tone ?? "").toLowerCase();
  if (tone === "positive") return "positive";
  if (tone === "negative") return "negative";
  if (tone === "watch" || tone === "warning") return "warning";
  if (tone === "neutral") return "neutral";
  return "info";
}

function sourceLabel(value: unknown) {
  const source = String(value ?? "unavailable");
  if (source === "cached_real") return "Cached real data";
  if (source === "live") return "Live data";
  if (source === "demo") return "Demo data";
  return sentenceCase(source);
}

function formatAge(value: unknown) {
  const hours = asNumber(value);
  if (hours === null) return "Unknown age";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}m old`;
  if (hours < 48) return `${hours.toFixed(1)}h old`;
  return `${(hours / 24).toFixed(1)}d old`;
}

function hasNewerTimestamp(candidate: string | undefined, previous: string | undefined) {
  if (!candidate) return false;
  if (!previous) return true;
  const candidateTime = Date.parse(candidate);
  const previousTime = Date.parse(previous);
  if (Number.isFinite(candidateTime) && Number.isFinite(previousTime)) {
    return candidateTime > previousTime;
  }
  return candidate !== previous;
}

function sortRows(rows: Row[], sortKey: SortKey, scoreKey: "long_term_score" | "short_term_score") {
  return [...rows].sort((a, b) => {
    if (sortKey === "ticker") return String(a.ticker ?? "").localeCompare(String(b.ticker ?? ""));
    if (sortKey === "market_cap") return (asNumber(b.market_cap) ?? -1) - (asNumber(a.market_cap) ?? -1);
    if (sortKey === "holding") return String(a.expected_holding_period ?? "").localeCompare(String(b.expected_holding_period ?? ""));
    if (sortKey === "relative") return (asNumber(b.relative_strength_score) ?? -1) - (asNumber(a.relative_strength_score) ?? -1);
    if (sortKey === "earnings") return (asNumber(b.earnings_intelligence_score) ?? -1) - (asNumber(a.earnings_intelligence_score) ?? -1);
    return (asNumber(b[scoreKey]) ?? -1) - (asNumber(a[scoreKey]) ?? -1);
  });
}

export function ScannerPage({ kind }: { kind: ScannerKind }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [data, setData] = useState<ScanPayload | null>(null);
  const [dataMode, setDataMode] = useState<DataMode>(() => {
    const value = searchParams.get("mode");
    return value === "live" || value === "demo" ? value : "auto";
  });
  const [query, setQuery] = useState(() => searchParams.get("q") ?? "");
  const [sortKey, setSortKey] = useState<SortKey>(() => {
    const value = searchParams.get("sort");
    return value === "relative" || value === "earnings" || value === "ticker" || value === "market_cap" || value === "holding" ? value : "score";
  });
  const [longRecommendation, setLongRecommendation] = useState<RecommendationFilter>(() => searchParams.get("longRating") ?? "all");
  const [shortRecommendation, setShortRecommendation] = useState<RecommendationFilter>(() => searchParams.get("shortRating") ?? "all");
  const [shortBucket, setShortBucket] = useState<ShortBucketFilter>(() => {
    const value = searchParams.get("bucket");
    return value === ACTIVE_BUCKET || value === WAITING_BUCKET || value === EXCLUDED_BUCKET ? value : ALL_RECOMMENDATIONS;
  });
  const [refreshNotice, setRefreshNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const universe = kind === "international" ? "international" : "global";
  const copy = pageCopy[kind];

  function updateFilterUrl(next: {
    dataMode?: DataMode;
    query?: string;
    sortKey?: SortKey;
    longRecommendation?: RecommendationFilter;
    shortRecommendation?: RecommendationFilter;
    shortBucket?: ShortBucketFilter;
  }) {
    const nextMode = next.dataMode ?? dataMode;
    const nextQuery = next.query ?? query;
    const nextSort = next.sortKey ?? sortKey;
    const nextLongRecommendation = next.longRecommendation ?? longRecommendation;
    const nextShortRecommendation = next.shortRecommendation ?? shortRecommendation;
    const nextBucket = next.shortBucket ?? shortBucket;
    const params = new URLSearchParams();
    if (nextMode !== "auto") params.set("mode", nextMode);
    if (nextQuery.trim()) params.set("q", nextQuery.trim());
    if (nextSort !== "score") params.set("sort", nextSort);
    if (nextLongRecommendation !== "all") params.set("longRating", nextLongRecommendation);
    if (nextShortRecommendation !== "all") params.set("shortRating", nextShortRecommendation);
    if (nextBucket !== ALL_RECOMMENDATIONS) params.set("bucket", nextBucket);
    const suffix = params.toString();
    router.replace(suffix ? `${pathname}?${suffix}` : pathname, { scroll: false });
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setRefreshNotice(null);
    fetchOverview({ universe, dataMode, refresh: false })
      .then((payload) => {
        if (active) setData(payload);
      })
      .catch((err: Error) => {
        if (!active) return;
        if (dataMode !== "demo" && err.message.includes("API 504")) {
          return fetchOverview({ universe, dataMode: "demo", refresh: false })
            .then((payload) => {
              if (active) {
                setData({
                  ...payload,
                  api_note: "The live scan timed out, so this page is showing fast demo data."
                });
                setError(null);
              }
            })
            .catch((fallbackErr: Error) => {
              if (active) setError(fallbackErr.message);
            });
        }
        setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [universe, dataMode]);

  async function handleRefresh() {
    const previousUpdatedAt = data?.updated_at;
    setLoading(true);
    setError(null);
    setRefreshNotice(null);
    try {
      const payload = await fetchOverview({
        universe,
        dataMode,
        refresh: true,
        previousUpdatedAt
      });
      setData(payload);
      setRefreshNotice(
        hasNewerTimestamp(payload.updated_at, previousUpdatedAt)
          ? `Refresh complete · ${new Date(String(payload.updated_at)).toLocaleString()}`
          : String(payload.api_note ?? "No newer market snapshot was published.")
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "The market scan refresh failed.");
    } finally {
      setLoading(false);
    }
  }

  const stats = pickRecord(data?.market_stats);
  const marketRows = pickArray(data?.market_rows);
  const longRows = pickArray(data?.long_term);
  const shortRows = pickArray(data?.short_term);
  const dataStatus = pickRecord(data?.data_status);
  const status = String(dataStatus.status ?? "unavailable");
  const isActionable = dataStatus.is_actionable === true;
  const blockReason = String(dataStatus.block_reason ?? "Actionable signals are disabled until fresh real data is available.");
  const blockedCount = asNumber(dataStatus.blocked_actionable_count) ?? 0;
  const invalidLevelCount = asNumber(stats.invalid_trade_level_rows) ?? 0;
  const blockedInvalidLevelCount = asNumber(stats.blocked_invalid_level_signals) ?? 0;
  const shortBucketCounts = shortRows.reduce<Record<ShortTermSignalBucket, number>>(
    (counts, row) => {
      counts[classifyShortTermSignal(row)] += 1;
      return counts;
    },
    { active: 0, waiting: 0, excluded: 0 }
  );
  const longRecommendations = [...new Set(longRows.map((row) => String(row.recommendation_label ?? "N/A")))].sort();
  const shortRecommendations = [...new Set(shortRows.map((row) => String(row.recommendation_label ?? "N/A")))].sort();
  const scanAge = formatAge(dataStatus.age_hours);
  const headerStatus = !data
    ? "Loading"
    : status === "fresh"
      ? `${sourceLabel(data.source)} / Fresh`
      : `${sentenceCase(status)} / Read only`;

  const filteredLong = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const searchedRows = normalized
      ? longRows.filter((row) => `${row.ticker ?? ""} ${row.company_name ?? ""} ${row.sector ?? ""}`.toLowerCase().includes(normalized))
      : longRows;
    const rows = longRecommendation === "all"
      ? searchedRows
      : searchedRows.filter((row) => String(row.recommendation_label ?? "N/A") === longRecommendation);
    return sortRows(rows, sortKey, "long_term_score");
  }, [longRecommendation, longRows, query, sortKey]);

  const filteredShort = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const searchedRows = normalized
      ? shortRows.filter((row) => `${row.ticker ?? ""} ${row.company_name ?? ""} ${row.setup_type ?? ""}`.toLowerCase().includes(normalized))
      : shortRows;
    const recommendationRows = shortRecommendation === "all"
      ? searchedRows
      : searchedRows.filter((row) => String(row.recommendation_label ?? "N/A") === shortRecommendation);
    const rows = shortBucket === ALL_RECOMMENDATIONS
      ? recommendationRows
      : recommendationRows.filter((row) => classifyShortTermSignal(row) === shortBucket);
    return sortRows(rows, sortKey, "short_term_score");
  }, [shortRecommendation, shortRows, query, shortBucket, sortKey]);

  const scoreBars = marketRows.slice(0, 16).map((row) => ({
    ticker: String(row.ticker ?? "N/A"),
    long: asNumber(row.long_term_score) ?? 0,
    short: asNumber(row.short_term_score) ?? 0
  }));

  const showLong = kind === "overview" || kind === "long" || kind === "international";
  const showShort = kind === "overview" || kind === "short" || kind === "international";

  return (
    <div>
      <SectionHeader title="Scanner" badge={`${copy.badge} / ${headerStatus}`} />
      <ResearchTabs activeHref={pathname} queryString={searchParams.toString()} />

      <TerminalPanel
        title="Scanner controls"
        eyebrow={data?.universe_name ?? "Universe"}
        action={
          <button
            type="button"
            onClick={() => void handleRefresh()}
            disabled={loading}
            aria-busy={loading}
            className="button disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? (data ? "Refreshing…" : "Loading…") : "Refresh Scan"}
          </button>
        }
      >
        <div className="grid gap-3 md:grid-cols-[160px_1fr_160px]">
          <label className="grid gap-2 text-xs text-[var(--muted)]">
            Data Mode
            <select
              value={dataMode}
              onChange={(event) => {
                const value = event.target.value as DataMode;
                setDataMode(value);
                updateFilterUrl({ dataMode: value });
              }}
              disabled={loading}
              className="field disabled:cursor-not-allowed disabled:opacity-60"
            >
              <option value="auto">Auto</option>
              <option value="live">Live</option>
              <option value="demo">Demo</option>
            </select>
          </label>
          <label className="grid gap-2 text-xs text-[var(--muted)]">
            Search
            <input
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                updateFilterUrl({ query: event.target.value });
              }}
              placeholder="Ticker, company, sector..."
              className="field"
              type="search"
            />
          </label>
          <label className="grid gap-2 text-xs text-[var(--muted)]">
            Sort
            <select
              value={sortKey}
              onChange={(event) => {
                const value = event.target.value as SortKey;
                setSortKey(value);
                updateFilterUrl({ sortKey: value });
              }}
              className="field"
            >
              <option value="score">Score</option>
              <option value="relative">Relative Strength</option>
              <option value="earnings">Earnings Intelligence</option>
              <option value="ticker">Ticker</option>
              <option value="market_cap">Market Cap</option>
              <option value="holding">Holding Period</option>
            </select>
          </label>
        </div>
        {loading && data ? (
          <div role="status" aria-live="polite" className="mt-3 border-t border-[var(--line-soft)] pt-3 text-sm text-[var(--muted)]">
            Running a new market scan. The previous snapshot stays visible until the refreshed cache is published; enriched scans can take several minutes.
          </div>
        ) : refreshNotice ? (
          <div role="status" aria-live="polite" className="mt-3 border-t border-[var(--line-soft)] pt-3 text-sm text-[var(--muted)]">
            {refreshNotice}
          </div>
        ) : null}
      </TerminalPanel>

      {loading && !data ? <LoadingState title="Loading scanner" message="Loading scanner data from the OmniTrade API." /> : null}
      {error ? <TerminalPanel title="API error"><div role="alert" className="text-sm text-[var(--red)]">{error}</div></TerminalPanel> : null}

      {data ? (
        <div className="mt-5 space-y-5">
          {!isActionable ? (
            <div
              role="alert"
              aria-live="polite"
              className="border-l-4 border-[var(--amber)] bg-[var(--amber-soft)] px-4 py-3 text-sm text-[var(--text)]"
            >
              <div className="font-semibold text-[var(--amber)]">Actionable signals are disabled</div>
              <div className="mt-1 text-[var(--muted)]">
                {blockReason} {blockedCount > 0 ? `${blockedCount} previously actionable signal${blockedCount === 1 ? " is" : "s are"} now blocked.` : ""}
              </div>
              <div className="mt-2 text-xs text-[var(--dim)]">
                {sourceLabel(data.source)} · {scanAge} · Use Refresh Scan to request current market data.
              </div>
            </div>
          ) : null}

          {invalidLevelCount > 0 ? (
            <div
              role="alert"
              aria-live="polite"
              className="border-l-4 border-[var(--red)] bg-[color-mix(in_srgb,var(--red)_10%,transparent)] px-4 py-3 text-sm text-[var(--text)]"
            >
              <div className="font-semibold text-[var(--red)]">Invalid trade levels blocked</div>
              <div className="mt-1 text-[var(--muted)]">
                {invalidLevelCount} row{invalidLevelCount === 1 ? "" : "s"} contained malformed or implausible execution prices.
                {blockedInvalidLevelCount > 0 ? ` ${blockedInvalidLevelCount} actionable signal${blockedInvalidLevelCount === 1 ? " was" : "s were"} disabled.` : ""}
              </div>
            </div>
          ) : null}

          {showShort ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Active now"
                value={String(shortBucketCounts.active)}
                meta={isActionable ? "Fresh, validated execution setups" : `${blockedCount} blocked · ${scanAge}`}
                tone={shortBucketCounts.active > 0 ? "positive" : "warning"}
              />
              <MetricCard
                label="Waiting / watchlist"
                value={String(shortBucketCounts.waiting)}
                meta="Monitoring, no immediate entry"
                tone="warning"
              />
              <MetricCard
                label="Excluded"
                value={String(shortBucketCounts.excluded)}
                meta={isActionable ? "No-trade or blocked rows" : "Read-only or blocked rows"}
                tone="neutral"
              />
              <MetricCard
                label="Scanned"
                value={String(stats.scanned_count ?? 0)}
                meta={`${stats.universe_size ?? 0} names in universe`}
                tone="info"
              />
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Scanned" value={String(stats.scanned_count ?? 0)} meta={`${stats.universe_size ?? 0} names in universe`} tone="info" />
              <MetricCard
                label="Long Candidates"
                value={String(stats.long_candidates ?? longRows.length)}
                meta={isActionable ? "Long-term recommendations" : "Historical rankings · Research only"}
                tone={isActionable ? "positive" : "warning"}
              />
              <MetricCard label="Average long score" value={String(stats.avg_long_term_score ?? "N/A")} meta="Across the current scan" tone="neutral" />
              <MetricCard label="Data status" value={isActionable ? "Fresh" : "Read only"} meta={`${sourceLabel(data.source)} · ${scanAge}`} tone={isActionable ? "positive" : "warning"} />
            </div>
          )}

          {kind === "overview" || kind === "international" ? (
            <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
              <TerminalPanel title="Score distribution" eyebrow="Top scanned names">
                <ChartLegend
                  items={[
                    { label: "Long score", color: "var(--chart-positive)" },
                    { label: "Short score", color: "var(--chart-secondary)" }
                  ]}
                  summary="Compares long- and short-horizon scores for the top scanned names. Higher bars indicate stronger model scores."
                />
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                    <BarChart data={scoreBars}>
                      <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                      <XAxis dataKey="ticker" stroke="var(--dim)" fontSize={11} />
                      <YAxis stroke="var(--dim)" fontSize={11} />
                      <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                      <Bar dataKey="long" name="Long score" fill="var(--chart-positive)" />
                      <Bar dataKey="short" name="Short score" fill="var(--chart-secondary)" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </TerminalPanel>
              <TerminalPanel title="Scan context" eyebrow={sourceLabel(data.source)}>
                <div className="space-y-3 text-sm text-[var(--muted)]">
                  <div className="flex justify-between gap-4 border-b border-[var(--line-soft)] pb-2"><span>Updated</span><span className="mono break-all text-right text-white">{String(data.updated_at ?? "N/A")}</span></div>
                  <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Freshness</span><span className={isActionable ? "mono text-[var(--green)]" : "mono text-[var(--amber)]"}>{scanAge}</span></div>
                  <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Signal access</span><span className={isActionable ? "mono text-[var(--green)]" : "mono text-[var(--amber)]"}>{isActionable ? "Actionable" : "Read only"}</span></div>
                  <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Advancers</span><span className="mono text-white">{String(stats.advancers ?? 0)}</span></div>
                  <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Decliners</span><span className="mono text-white">{String(stats.decliners ?? 0)}</span></div>
                  <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Relative leaders</span><span className="mono text-[var(--green)]">{String(stats.relative_strength_leaders ?? 0)}</span></div>
                  <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Relative laggards</span><span className="mono text-[var(--red)]">{String(stats.relative_strength_laggards ?? 0)}</span></div>
                  <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Earnings within 7d</span><span className="mono text-[var(--amber)]">{String(stats.earnings_event_risk_count ?? 0)}</span></div>
                  <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Strong earnings</span><span className="mono text-[var(--green)]">{String(stats.earnings_strong_count ?? 0)}</span></div>
                  <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Earnings caution</span><span className="mono text-[var(--red)]">{String(stats.earnings_caution_count ?? 0)}</span></div>
                  <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Fallbacks</span><span className="mono text-white">{String(stats.fallback_count ?? 0)}</span></div>
                  <div>{String(data.api_note ?? "Fresh scan context is available from the Python scanner service.")}</div>
                </div>
              </TerminalPanel>
            </div>
          ) : null}

          {showLong ? (
            <TerminalPanel title="Long-term candidates" eyebrow="Recommendation engine">
              <label className="mb-4 grid max-w-xs gap-2 text-xs text-[var(--muted)]">
                Recommendation rating
                <select
                  value={longRecommendation}
                  onChange={(event) => {
                    const value = event.target.value;
                    setLongRecommendation(value);
                    updateFilterUrl({ longRecommendation: value });
                  }}
                  className="field"
                >
                  <option value="all">All ratings ({longRows.length})</option>
                  {longRecommendations.map((label) => (
                    <option key={label} value={label}>{label}</option>
                  ))}
                </select>
              </label>
              <DataTable rows={filteredLong} columns={longColumns} emptyLabel="No long-term candidates are available for this scan." />
            </TerminalPanel>
          ) : null}

          {showShort ? (
            <TerminalPanel
              title="Short-term signals"
              eyebrow={`${shortBucket === ALL_RECOMMENDATIONS ? "All recommendations" : shortBucket === ACTIVE_BUCKET ? "Active now" : shortBucket === WAITING_BUCKET ? "Waiting / watchlist" : "Caution / blocked"} · ${filteredShort.length} shown`}
            >
              <label className="mb-4 grid max-w-xs gap-2 text-xs text-[var(--muted)]">
                Recommendation rating
                <select
                  value={shortRecommendation}
                  onChange={(event) => {
                    const value = event.target.value;
                    setShortRecommendation(value);
                    updateFilterUrl({ shortRecommendation: value });
                  }}
                  className="field"
                >
                  <option value="all">All ratings ({shortRows.length})</option>
                  {shortRecommendations.map((label) => (
                    <option key={label} value={label}>{label}</option>
                  ))}
                </select>
              </label>
              <div className="mb-4 overflow-x-auto">
                <div
                  role="tablist"
                  aria-label="Short-term signal categories"
                  className="flex min-w-max border-b border-[var(--line-soft)]"
                >
                  {([
                    [ALL_RECOMMENDATIONS, "All recommendations", shortRows.length],
                    [ACTIVE_BUCKET, "Active now", shortBucketCounts.active],
                    [WAITING_BUCKET, "Waiting / watchlist", shortBucketCounts.waiting],
                    [EXCLUDED_BUCKET, "Caution / blocked", shortBucketCounts.excluded]
                  ] as const).map(([bucket, label, count]) => (
                    <button
                      key={bucket}
                      id={`short-term-tab-${bucket}`}
                      type="button"
                      role="tab"
                      aria-selected={shortBucket === bucket}
                      aria-controls="short-term-signal-panel"
                      onClick={() => {
                        setShortBucket(bucket);
                        updateFilterUrl({ shortBucket: bucket });
                      }}
                      className={`min-h-11 shrink-0 border-b-2 px-4 text-sm transition-colors ${
                        shortBucket === bucket
                          ? "border-[var(--accent)] text-[var(--text)]"
                          : "border-transparent text-[var(--muted)] hover:text-[var(--text)]"
                      }`}
                    >
                      {label} <span className="mono ml-1 text-xs text-[var(--dim)]">{count}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div
                id="short-term-signal-panel"
                role="tabpanel"
                aria-labelledby={`short-term-tab-${shortBucket}`}
              >
                <DataTable
                  rows={filteredShort}
                  columns={shortColumns}
                  emptyLabel={
                    shortBucket === ACTIVE_BUCKET
                      ? isActionable
                        ? "No setups are actionable now."
                        : "No active signals. Refresh for a current, actionable scan."
                      : shortBucket === WAITING_BUCKET
                        ? "No signals are waiting or on the watchlist."
                        : shortBucket === EXCLUDED_BUCKET
                          ? "No caution or blocked recommendations are in this scan."
                          : "No short-term recommendations match these filters."
                  }
                />
              </div>
            </TerminalPanel>
          ) : null}

          {kind === "overview" ? (
            <TerminalPanel title="Market table" eyebrow="All scanned names">
              <DataTable rows={marketRows} columns={marketColumns} emptyLabel="No market rows are available." />
            </TerminalPanel>
          ) : null}

          {filteredLong.slice(0, 3).length > 0 && kind === "long" ? (
            <div className="grid gap-5 xl:grid-cols-3">
              {filteredLong.slice(0, 3).map((row) => (
                <TerminalPanel key={String(row.ticker)} title={String(row.ticker ?? "N/A")} eyebrow={sentenceCase(row.recommendation_label)}>
                  <div className="space-y-3 text-sm text-[var(--muted)]">
                    <div className="text-base font-semibold text-white">{String(row.company_name ?? "N/A")}</div>
                    <div>{String(row.thesis ?? row.summary_reasoning ?? "No thesis available.")}</div>
                    <div className="border-t border-[var(--line-soft)] pt-3">{String(row.valuation_summary ?? "Valuation summary unavailable.")}</div>
                  </div>
                </TerminalPanel>
              ))}
            </div>
          ) : null}

          {filteredShort.slice(0, 3).length > 0 && kind === "short" ? (
            <div className="grid gap-5 xl:grid-cols-3">
              {filteredShort.slice(0, 3).map((row) => (
                <TerminalPanel key={String(row.ticker)} title={String(row.ticker ?? "N/A")} eyebrow={sentenceCase(row.setup_type)}>
                  <div className="space-y-3 text-sm text-[var(--muted)]">
                    <div className="text-base font-semibold text-white">{String(row.company_name ?? "N/A")}</div>
                    <div>{String(row.trade_state_explanation ?? row.invalidation_note ?? "No setup note available.")}</div>
                    <div className="grid grid-cols-3 gap-2 border-t border-[var(--line-soft)] pt-3 text-xs">
                      <div><div className="text-[var(--dim)]">Entry</div><div className="text-white">{blockedPrice(row, "entry_price")}</div></div>
                      <div><div className="text-[var(--dim)]">Target</div><div className="text-white">{blockedPrice(row, "target_price")}</div></div>
                      <div><div className="text-[var(--dim)]">Stop</div><div className="text-white">{blockedPrice(row, "stop_loss_price")}</div></div>
                    </div>
                  </div>
                </TerminalPanel>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
