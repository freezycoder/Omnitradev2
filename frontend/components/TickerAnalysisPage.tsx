"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartLegend } from "@/components/ChartLegend";
import { DataTable, DataTableColumn } from "@/components/DataTable";
import { ForecastPanel } from "@/components/ForecastPanel";
import { LoadingState } from "@/components/LoadingState";
import { MetricCard } from "@/components/MetricCard";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import {
  addWatchlistItem,
  ApiCapabilities,
  fetchApiCapabilities,
  fetchTicker,
  READ_ONLY_API_CAPABILITIES,
  TickerPayload
} from "@/lib/api";
import { asNumber, formatCurrency, formatLargeNumber, formatPct, formatSignedPct, pickArray, pickRecord, sentenceCase } from "@/lib/format";

type Row = Record<string, unknown>;
type DataMode = "auto" | "live" | "demo";

const newsColumns: DataTableColumn<Row>[] = [
  { key: "published_at", header: "Published" },
  { key: "headline", header: "Headline", render: (row) => <span className="text-white">{String(row.headline ?? row.title ?? "N/A")}</span> },
  { key: "event_type", header: "Event", render: (row) => sentenceCase(row.event_type) },
  { key: "source_quality", header: "Source class", render: (row) => sentenceCase(row.source_quality) },
  { key: "source", header: "Source" },
  {
    key: "url",
    header: "Link",
    sortable: false,
    render: (row) => row.url ? <a className="text-link" href={String(row.url)} target="_blank" rel="noreferrer">Open</a> : "N/A"
  }
];

const alternativeComponentColumns: DataTableColumn<Row>[] = [
  { key: "label", header: "Source", render: (row) => <span className="font-semibold text-white">{String(row.label ?? "N/A")}</span> },
  { key: "status", header: "Status", render: (row) => sentenceCase(row.status) },
  { key: "score", header: "Score", align: "right" },
  {
    key: "modeled_impact",
    header: "Shadow impact",
    align: "right",
    render: (row) => {
      const value = asNumber(row.modeled_impact);
      return value === null ? "N/A" : `${value > 0 ? "+" : ""}${value}`;
    }
  },
  { key: "coverage_score", header: "Coverage", align: "right", render: (row) => formatPct(row.coverage_score, 0) },
  { key: "summary", header: "Interpretation", render: (row) => <span className="text-[var(--muted)]">{String(row.summary ?? "N/A")}</span> }
];

const secEventColumns: DataTableColumn<Row>[] = [
  { key: "filed_at", header: "Filed" },
  { key: "form", header: "Form" },
  { key: "category", header: "Event", render: (row) => sentenceCase(row.category) },
  { key: "summary", header: "Primary-source evidence", render: (row) => <span className="text-white">{String(row.summary ?? "N/A")}</span> },
  {
    key: "url",
    header: "Filing",
    sortable: false,
    render: (row) => row.url ? <a className="text-link" href={String(row.url)} target="_blank" rel="noreferrer">Open SEC</a> : "N/A"
  }
];

const relativeStrengthPeriodColumns: DataTableColumn<Row>[] = [
  { key: "label", header: "Window", render: (row) => <span className="font-semibold text-white">{String(row.label ?? "N/A")}</span> },
  { key: "stock_return_pct", header: "Stock", align: "right", render: (row) => formatSignedPct(row.stock_return_pct, 1) },
  { key: "market_return_pct", header: "Market", align: "right", render: (row) => formatSignedPct(row.market_return_pct, 1) },
  { key: "market_excess_pct", header: "Vs market", align: "right", render: (row) => formatSignedPct(row.market_excess_pct, 1) },
  { key: "sector_return_pct", header: "Sector", align: "right", render: (row) => formatSignedPct(row.sector_return_pct, 1) },
  { key: "sector_excess_pct", header: "Vs sector", align: "right", render: (row) => formatSignedPct(row.sector_excess_pct, 1) }
];

const earningsQuarterColumns: DataTableColumn<Row>[] = [
  { key: "period", header: "Fiscal period" },
  { key: "fiscal_quarter", header: "Quarter", render: (row) => row.fiscal_quarter ? `Q${String(row.fiscal_quarter)} ${String(row.fiscal_year ?? "")}` : "N/A" },
  { key: "actual_eps", header: "Actual EPS", align: "right" },
  { key: "estimated_eps", header: "Estimate", align: "right" },
  { key: "surprise_pct", header: "Surprise", align: "right", render: (row) => formatSignedPct(row.surprise_pct, 1) },
  {
    key: "result",
    header: "Result",
    render: (row) => {
      const result = String(row.result ?? "unresolved");
      return <StatusBadge tone={result === "beat" ? "positive" : result === "miss" ? "negative" : "neutral"}>{sentenceCase(result)}</StatusBadge>;
    }
  }
];

function recommendationTone(value: unknown) {
  const text = String(value ?? "").toLowerCase();
  if (text.includes("avoid") || text.includes("sell") || text.includes("risk")) return "negative";
  if (text.includes("watch") || text.includes("hold")) return "warning";
  return "positive";
}

function relativeTone(value: unknown) {
  const score = asNumber(value);
  if (score === null) return "neutral" as const;
  if (score > 0) return "positive" as const;
  if (score < 0) return "negative" as const;
  return "neutral" as const;
}

function normalizedTicker(value: string | null) {
  const candidate = String(value ?? "").trim().toUpperCase();
  return /^[A-Z0-9.-]{1,10}$/.test(candidate) ? candidate : "AAPL";
}

function chartDateLabel(value: unknown) {
  const parsed = Date.parse(String(value ?? ""));
  if (!Number.isFinite(parsed)) return String(value ?? "");
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(parsed));
}

export function TickerAnalysisPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const initialTicker = normalizedTicker(searchParams.get("ticker"));
  const [tickerInput, setTickerInput] = useState(initialTicker);
  const [ticker, setTicker] = useState(initialTicker);
  const [dataMode, setDataMode] = useState<DataMode>(() => {
    const value = searchParams.get("mode");
    return value === "live" || value === "demo" ? value : "auto";
  });
  const [data, setData] = useState<TickerPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [watchlistStatus, setWatchlistStatus] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<ApiCapabilities | null>(null);

  useEffect(() => {
    let active = true;
    fetchApiCapabilities()
      .catch(() => READ_ONLY_API_CAPABILITIES)
      .then((payload) => {
        if (active) setCapabilities(payload);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setWatchlistStatus(null);
    fetchTicker(ticker, dataMode)
      .then((payload) => {
        if (active) setData(payload);
      })
      .catch((err: Error) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [ticker, dataMode]);

  const snapshot = pickRecord(data?.snapshot);
  const fundamentals = pickRecord(data?.fundamentals);
  const longView = pickRecord(data?.long_term_view);
  const shortView = pickRecord(data?.short_term_view);
  const dayTrade = pickRecord(shortView.day_trade);
  const swingTrade = pickRecord(shortView.swing_trade);
  const primarySetup = shortView.primary_horizon_label === dayTrade.horizon_label ? dayTrade : swingTrade;
  const forecastLevels = useMemo(() => {
    const entryPrice = asNumber(primarySetup.entry_price);
    const stopLossPrice = asNumber(primarySetup.stop_loss_price);
    const targetPrice = asNumber(primarySetup.target_price);
    return entryPrice && stopLossPrice && targetPrice
      ? { entryPrice, stopLossPrice, targetPrice }
      : undefined;
  }, [primarySetup.entry_price, primarySetup.stop_loss_price, primarySetup.target_price]);
  const longRec = pickRecord(data?.long_term_recommendation);
  const shortRec = pickRecord(data?.short_term_recommendation);
  const accounting = pickRecord(data?.accounting_quality_view);
  const alternativeSignal = pickRecord(data?.alternative_signal_view);
  const relativeStrength = pickRecord(data?.relative_strength_view);
  const relativeStrengthPeriods = pickArray(relativeStrength.periods);
  const relativeStrengthWarnings = Array.isArray(relativeStrength.warnings)
    ? relativeStrength.warnings.map((item) => String(item))
    : [];
  const earningsIntelligence = pickRecord(data?.earnings_intelligence_view);
  const earningsQuarters = pickArray(earningsIntelligence.quarters);
  const earningsEvidence = Array.isArray(earningsIntelligence.evidence)
    ? earningsIntelligence.evidence.map((item) => String(item))
    : [];
  const earningsWarnings = Array.isArray(earningsIntelligence.warnings)
    ? earningsIntelligence.warnings.map((item) => String(item))
    : [];
  const alternativeComponents = pickArray(alternativeSignal.components);
  const secEvents = pickArray(pickRecord(data?.sec_event_bundle).events);
  const alternativeEvidence = Array.isArray(alternativeSignal.evidence)
    ? alternativeSignal.evidence.map((item) => String(item))
    : [];
  const news = pickArray(data?.recent_news);
  const enrichedHistory = pickArray(data?.enriched_history);

  const chartRows = useMemo(
    () =>
      enrichedHistory.slice(-120).map((row) => ({
        date: String(row.Date ?? row.date ?? ""),
        close: asNumber(row.Close ?? row.close) ?? 0,
        sma50: asNumber(row.MA50 ?? row.sma_50) ?? null,
        sma200: asNumber(row.MA200 ?? row.sma_200) ?? null
      })),
    [enrichedHistory]
  );
  const chartSummary = useMemo(() => {
    const latest = chartRows.at(-1);
    if (!latest) return `No price history is available for ${ticker}.`;
    const comparisons = [
      latest.sma50 === null ? null : `${latest.close >= latest.sma50 ? "above" : "below"} SMA50`,
      latest.sma200 === null ? null : `${latest.close >= latest.sma200 ? "above" : "below"} SMA200`
    ].filter(Boolean);
    return `${ticker} last closed at ${formatCurrency(latest.close)}${comparisons.length ? `, ${comparisons.join(" and ")}` : ""}.`;
  }, [chartRows, ticker]);

  function updateUrl(nextTicker: string, nextMode: DataMode) {
    const params = new URLSearchParams();
    params.set("ticker", nextTicker);
    if (nextMode !== "auto") params.set("mode", nextMode);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  function submitTicker(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextTicker = normalizedTicker(tickerInput);
    setTickerInput(nextTicker);
    setTicker(nextTicker);
    updateUrl(nextTicker, dataMode);
  }

  function saveWatchlist() {
    if (capabilities?.watchlist_mutations_enabled !== true) return;
    addWatchlistItem(ticker, "ticker_page")
      .then(() => setWatchlistStatus(`${ticker} saved to watchlist.`))
      .catch((err: Error) => setWatchlistStatus(err.message));
  }

  return (
    <div>
      <SectionHeader
        title="Ticker Analysis"
        badge={String(data?.data_source ?? dataMode)}
      />

      <TerminalPanel title="Ticker controls" eyebrow="Lookup">
        <form onSubmit={submitTicker} className="grid gap-3 md:grid-cols-[1fr_160px_120px_150px]">
          <label htmlFor="ticker-symbol" className="grid gap-2 text-xs text-[var(--muted)]">
            Ticker
            <input
              id="ticker-symbol"
              value={tickerInput}
              onChange={(event) => setTickerInput(event.target.value)}
              className="field"
              placeholder="AAPL, NVDA, ASML..."
              autoCapitalize="characters"
              autoComplete="off"
            />
          </label>
          <label htmlFor="ticker-data-mode" className="grid gap-2 text-xs text-[var(--muted)]">
            Data mode
            <select
              id="ticker-data-mode"
              value={dataMode}
              onChange={(event) => {
                const value = event.target.value as DataMode;
                setDataMode(value);
                updateUrl(ticker, value);
              }}
              className="field"
            >
              <option value="auto">Auto</option>
              <option value="live">Live</option>
              <option value="demo">Demo</option>
            </select>
          </label>
          <button type="submit" disabled={loading} className="button self-end disabled:cursor-not-allowed disabled:opacity-60">
            {loading ? "Analyzing…" : "Analyze"}
          </button>
          <button
            type="button"
            onClick={saveWatchlist}
            disabled={capabilities?.watchlist_mutations_enabled !== true}
            className="button button-primary self-end disabled:cursor-not-allowed disabled:opacity-60"
          >
            {capabilities === null
              ? "Checking Access..."
              : capabilities.watchlist_mutations_enabled
                ? "Save Watchlist"
                : "Watchlist Read Only"}
          </button>
        </form>
        {capabilities && !capabilities.watchlist_mutations_enabled ? (
          <div role="status" className="mt-3 border-t border-[var(--line-soft)] pt-3 text-xs text-[var(--amber)]">
            {capabilities.message}
          </div>
        ) : null}
        {watchlistStatus ? <div role="status" aria-live="polite" className="mt-3 text-xs text-[var(--muted)]">{watchlistStatus}</div> : null}
      </TerminalPanel>

      {loading && !data ? <LoadingState title="Loading ticker" message={`Loading analysis for ${ticker}.`} /> : null}
      {error ? <TerminalPanel title="API error"><div role="alert" className="text-sm text-[var(--red)]">{error}</div></TerminalPanel> : null}

      {data ? (
        <div className="mt-5 space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-7">
            <MetricCard label="Price" value={formatCurrency(snapshot.current_price)} meta={`${formatPct(snapshot.daily_change_pct, 2)} today`} tone={(asNumber(snapshot.daily_change_pct) ?? 0) >= 0 ? "positive" : "negative"} />
            <MetricCard label="Long Score" value={String(longView.score ?? "N/A")} meta={String(longRec.label ?? "Long-term view")} tone={recommendationTone(longRec.label)} />
            <MetricCard label="Short Score" value={String(shortView.score ?? "N/A")} meta={String(shortRec.setup_type ?? shortRec.label ?? "Short-term setup")} tone={recommendationTone(shortRec.label)} />
            <MetricCard
              label="Shadow Event Score"
              value={String(alternativeSignal.score ?? "N/A")}
              meta={`${String(alternativeSignal.mode ?? "shadow").toUpperCase()} · ${formatPct(alternativeSignal.coverage_score, 0)} coverage`}
              tone={(asNumber(alternativeSignal.modeled_impact) ?? 0) > 0 ? "positive" : (asNumber(alternativeSignal.modeled_impact) ?? 0) < 0 ? "negative" : "neutral"}
            />
            <MetricCard
              label="Relative Strength"
              value={String(relativeStrength.score ?? "N/A")}
              meta={`${sentenceCase(relativeStrength.status)} · ${formatPct(relativeStrength.coverage_score, 0)} coverage`}
              tone={(asNumber(relativeStrength.score) ?? 50) >= 58 ? "positive" : (asNumber(relativeStrength.score) ?? 50) <= 42 ? "negative" : "neutral"}
            />
            <MetricCard
              label="Earnings Intel"
              value={String(earningsIntelligence.score ?? "N/A")}
              meta={`${sentenceCase(earningsIntelligence.status)} · ${formatPct(earningsIntelligence.coverage_score, 0)} coverage`}
              tone={(asNumber(earningsIntelligence.score) ?? 50) >= 58 ? "positive" : (asNumber(earningsIntelligence.score) ?? 50) <= 42 ? "negative" : "neutral"}
            />
            <MetricCard label="Market Cap" value={formatLargeNumber(fundamentals.marketCap)} meta={String(data?.sector ?? fundamentals.sector ?? "N/A")} tone="info" />
          </div>

          <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
            <TerminalPanel title={`${ticker} price history`} eyebrow={String(data?.company_name ?? ticker)}>
              <ChartLegend
                items={[
                  { label: "Close", color: "var(--chart-accent)" },
                  { label: "SMA50", color: "var(--chart-positive)" },
                  { label: "SMA200", color: "var(--chart-warning)", dashed: true }
                ]}
                summary={chartSummary}
              />
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                  <ComposedChart data={chartRows}>
                    <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                    <XAxis
                      dataKey="date"
                      stroke="var(--dim)"
                      fontSize={11}
                      minTickGap={28}
                      tickFormatter={chartDateLabel}
                    />
                    <YAxis stroke="var(--dim)" fontSize={11} domain={["dataMin", "dataMax"]} />
                    <Tooltip
                      labelFormatter={chartDateLabel}
                      contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }}
                    />
                    <Area type="monotone" dataKey="close" name="Close" stroke="var(--chart-accent)" fill="var(--chart-accent)" fillOpacity={0.1} />
                    <Line type="monotone" dataKey="sma50" name="SMA50" stroke="var(--chart-positive)" strokeWidth={1.75} dot={false} connectNulls />
                    <Line type="monotone" dataKey="sma200" name="SMA200" stroke="var(--chart-warning)" strokeWidth={1.5} strokeDasharray="5 4" dot={false} connectNulls />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </TerminalPanel>

            <TerminalPanel title="Accounting quality" eyebrow={String(accounting.label ?? "Risk overlay")}>
              <div className="space-y-3 text-sm text-[var(--muted)]">
                <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Quality score</span><span className="mono text-white">{String(accounting.accounting_quality_score ?? "N/A")}</span></div>
                <div className="flex justify-between border-b border-[var(--line-soft)] pb-2">
                  <span>Piotroski F-score</span>
                  <span className="mono text-white">
                    {accounting.piotroski_score === null || accounting.piotroski_score === undefined
                      ? "N/A"
                      : `${String(accounting.piotroski_score)} / ${String(accounting.piotroski_available_checks ?? 9)}`}
                  </span>
                </div>
                <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Shenanigan risk</span><span className="mono text-white">{String(accounting.shenanigan_risk_score ?? "N/A")}</span></div>
                <div className="flex justify-between border-b border-[var(--line-soft)] pb-2"><span>Completeness</span><span className="mono text-white">{String(accounting.accounting_data_completeness_score ?? "N/A")}</span></div>
                <div>{String(accounting.explanation ?? "No accounting explanation available.")}</div>
              </div>
            </TerminalPanel>
          </div>

          <ForecastPanel ticker={ticker} levels={forecastLevels} />

          <div className="grid gap-5 xl:grid-cols-2">
            <TerminalPanel title="Long-term thesis" eyebrow={sentenceCase(longRec.confidence)}>
              <div className="space-y-3 text-sm text-[var(--muted)]">
                <StatusBadge tone={recommendationTone(longRec.label)}>{String(longRec.label ?? "N/A")}</StatusBadge>
                <div className="text-base leading-7 text-white">{String(longRec.thesis ?? longView.summary ?? "No thesis available.")}</div>
                <div>{String(data?.valuation_summary ?? "Valuation summary unavailable.")}</div>
              </div>
            </TerminalPanel>
            <TerminalPanel title="Short-term setup" eyebrow={String(shortView.trade_state_label ?? "Trade state")}>
              <div className="space-y-3 text-sm text-[var(--muted)]">
                <StatusBadge tone={shortView.is_actionable_now ? "positive" : "warning"}>{String(shortRec.label ?? "N/A")}</StatusBadge>
                <div className="text-base leading-7 text-white">{String(shortRec.entry_idea ?? shortView.trade_state_explanation ?? "No setup available.")}</div>
                <div className="grid grid-cols-3 gap-2 border-t border-[var(--line-soft)] pt-3 text-xs">
                  <div><div className="text-[var(--dim)]">Entry</div><div className="text-white">{String(shortRec.entry_idea ?? "N/A")}</div></div>
                  <div><div className="text-[var(--dim)]">Target</div><div className="text-white">{String(shortRec.target_idea ?? "N/A")}</div></div>
                  <div><div className="text-[var(--dim)]">Stop</div><div className="text-white">{String(shortRec.stop_loss_idea ?? "N/A")}</div></div>
                </div>
                <div className="mono text-[10px] uppercase tracking-[0.14em] text-[var(--dim)]">
                  {String(primarySetup.data_quality ?? "complete")} evidence · ATR risk unit {formatCurrency(primarySetup.risk_unit)}
                </div>
              </div>
            </TerminalPanel>
          </div>

          <TerminalPanel title="Earnings intelligence" eyebrow="Execution + consensus + revisions · shadow only">
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
                <MetricCard
                  label="Earnings Score"
                  value={String(earningsIntelligence.score ?? "N/A")}
                  meta="Zero live score impact"
                  tone={(asNumber(earningsIntelligence.score) ?? 50) >= 58 ? "positive" : (asNumber(earningsIntelligence.score) ?? 50) <= 42 ? "negative" : "neutral"}
                />
                <MetricCard
                  label="Next Report"
                  value={String(earningsIntelligence.next_earnings_date ?? "N/A")}
                  meta={earningsIntelligence.days_to_earnings === null || earningsIntelligence.days_to_earnings === undefined ? sentenceCase(earningsIntelligence.event_risk) : `${String(earningsIntelligence.days_to_earnings)} days · ${sentenceCase(earningsIntelligence.event_risk)} risk`}
                  tone={earningsIntelligence.event_risk === "high" ? "negative" : earningsIntelligence.event_risk === "elevated" || earningsIntelligence.event_risk === "watch" ? "warning" : "info"}
                />
                <MetricCard label="Latest Surprise" value={formatSignedPct(earningsIntelligence.latest_surprise_pct, 1)} meta={`${String(earningsIntelligence.consecutive_beats ?? 0)} consecutive beats`} tone={relativeTone(earningsIntelligence.latest_surprise_pct)} />
                <MetricCard label="Beat Rate" value={formatPct(earningsIntelligence.beat_rate_pct, 0)} meta={`Trend: ${sentenceCase(earningsIntelligence.surprise_trend)}`} tone={(asNumber(earningsIntelligence.beat_rate_pct) ?? 50) >= 75 ? "positive" : (asNumber(earningsIntelligence.beat_rate_pct) ?? 50) < 50 ? "negative" : "neutral"} />
                <MetricCard label="30d Revisions" value={(asNumber(earningsIntelligence.net_revisions_30d) ?? 0) > 0 ? `+${String(earningsIntelligence.net_revisions_30d)}` : String(earningsIntelligence.net_revisions_30d ?? "N/A")} meta={`${String(earningsIntelligence.revisions_up_30d ?? "N/A")} up / ${String(earningsIntelligence.revisions_down_30d ?? "N/A")} down`} tone={relativeTone(earningsIntelligence.net_revisions_30d)} />
                <MetricCard label="Consensus Growth" value={formatSignedPct(earningsIntelligence.current_quarter_growth_pct, 1)} meta={`${String(earningsIntelligence.current_quarter_analysts ?? "N/A")} analysts`} tone={relativeTone(earningsIntelligence.current_quarter_growth_pct)} />
              </div>
              <div className="border-l-2 border-[var(--accent)] pl-4 text-sm leading-6 text-[var(--muted)]">
                {String(earningsIntelligence.summary ?? "Earnings intelligence is unavailable.")}
              </div>
              <DataTable rows={earningsQuarters} columns={earningsQuarterColumns} emptyLabel="No resolved earnings quarters are available." />
              {earningsEvidence.length ? (
                <ul className="grid gap-2 text-sm text-[var(--muted)] md:grid-cols-2">
                  {earningsEvidence.map((item) => <li key={item} className="border-l border-[var(--line-strong)] pl-3">{item}</li>)}
                </ul>
              ) : null}
              {earningsWarnings.length ? (
                <ul className="grid gap-2 text-xs text-[var(--amber)]">
                  {earningsWarnings.map((item) => <li key={item}>{item}</li>)}
                </ul>
              ) : null}
            </div>
          </TerminalPanel>

          <TerminalPanel title="Relative strength" eyebrow="Market + sector leadership · shadow only">
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
                <MetricCard
                  label="Leadership Score"
                  value={String(relativeStrength.score ?? "N/A")}
                  meta="Zero live score impact"
                  tone={(asNumber(relativeStrength.score) ?? 50) >= 58 ? "positive" : (asNumber(relativeStrength.score) ?? 50) <= 42 ? "negative" : "neutral"}
                />
                <MetricCard label={`Vs ${String(relativeStrength.market_benchmark_symbol ?? "market")}`} value={formatSignedPct(relativeStrength.market_relative_pct, 1)} meta="Weighted 1/3/6/12m excess" tone={relativeTone(relativeStrength.market_relative_pct)} />
                <MetricCard label={`Vs ${String(relativeStrength.sector_benchmark_symbol ?? "sector")}`} value={formatSignedPct(relativeStrength.sector_relative_pct, 1)} meta="Weighted sector excess" tone={relativeTone(relativeStrength.sector_relative_pct)} />
                <MetricCard label="Universe Percentile" value={relativeStrength.universe_percentile === null || relativeStrength.universe_percentile === undefined ? "N/A" : `${String(relativeStrength.universe_percentile)}th`} meta="Assigned during full scan" tone="info" />
                <MetricCard label="Sector Percentile" value={relativeStrength.sector_percentile === null || relativeStrength.sector_percentile === undefined ? "N/A" : `${String(relativeStrength.sector_percentile)}th`} meta={String(relativeStrength.sector ?? data?.sector ?? "Sector peers")} tone="info" />
                <MetricCard label="Coverage" value={formatPct(relativeStrength.coverage_score, 0)} meta={`As of ${String(relativeStrength.as_of_date ?? "N/A")}`} tone={(asNumber(relativeStrength.coverage_score) ?? 0) >= 70 ? "positive" : "warning"} />
              </div>
              <div className="border-l-2 border-[var(--accent)] pl-4 text-sm leading-6 text-[var(--muted)]">
                {String(relativeStrength.summary ?? "Relative-strength research is unavailable.")}
              </div>
              <DataTable rows={relativeStrengthPeriods} columns={relativeStrengthPeriodColumns} emptyLabel="No relative-strength periods are available." />
              {relativeStrengthWarnings.length ? (
                <ul className="grid gap-2 text-xs text-[var(--amber)]">
                  {relativeStrengthWarnings.map((item) => <li key={item}>{item}</li>)}
                </ul>
              ) : null}
            </div>
          </TerminalPanel>

          <TerminalPanel title="Alternative signals" eyebrow="Shadow research · zero live score impact">
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Modeled Impact" value={`${(asNumber(alternativeSignal.modeled_impact) ?? 0) > 0 ? "+" : ""}${String(alternativeSignal.modeled_impact ?? 0)}`} meta={`Capped at ±${String(alternativeSignal.max_abs_impact ?? 10)}`} tone={(asNumber(alternativeSignal.modeled_impact) ?? 0) > 0 ? "positive" : (asNumber(alternativeSignal.modeled_impact) ?? 0) < 0 ? "negative" : "neutral"} />
                <MetricCard label="Applied Impact" value={String(alternativeSignal.applied_impact ?? 0)} meta="Recommendations unchanged" tone="neutral" />
                <MetricCard label="Coverage" value={formatPct(alternativeSignal.coverage_score, 0)} meta="Missing sources are not neutral" tone={(asNumber(alternativeSignal.coverage_score) ?? 0) >= 70 ? "info" : "warning"} />
                <MetricCard label="State" value={sentenceCase(alternativeSignal.status)} meta="Activation requires calibration" tone="warning" />
              </div>
              <div className="border-l-2 border-[var(--accent)] pl-4 text-sm leading-6 text-[var(--muted)]">
                {String(alternativeSignal.summary ?? "Alternative-signal research is unavailable.")}
              </div>
              <div className="text-xs leading-5 text-[var(--dim)]">
                This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.
              </div>
              <DataTable rows={alternativeComponents} columns={alternativeComponentColumns} emptyLabel="No alternative-signal components are available." />
              {alternativeEvidence.length ? (
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-[var(--dim)]">Highest-weight evidence</div>
                  <ul className="grid gap-2 text-sm text-[var(--muted)] md:grid-cols-2">
                    {alternativeEvidence.map((item) => <li key={item} className="border-l border-[var(--line-strong)] pl-3">{item}</li>)}
                  </ul>
                </div>
              ) : null}
              <details className="border-t border-[var(--line-soft)] pt-3">
                <summary className="cursor-pointer text-sm font-semibold text-white">Inspect SEC filing events ({secEvents.length})</summary>
                <div className="mt-3">
                  <DataTable rows={secEvents} columns={secEventColumns} emptyLabel="No SEC filing events are available for this ticker and lookback window." />
                </div>
              </details>
            </div>
          </TerminalPanel>

          <TerminalPanel title="Recent news" eyebrow="Context">
            <DataTable rows={news} columns={newsColumns} emptyLabel="No recent news is available for this ticker." />
          </TerminalPanel>
        </div>
      ) : null}
    </div>
  );
}
