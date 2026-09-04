"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { ChartLegend } from "@/components/ChartLegend";
import { DataTable, DataTableColumn } from "@/components/DataTable";
import { LoadingState } from "@/components/LoadingState";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import {
  ApiCapabilities,
  fetchApiCapabilities,
  fetchPerformanceLab,
  logPerformanceOutcome,
  PerformanceLabPayload,
  PerformanceLogInput,
  READ_ONLY_API_CAPABILITIES
} from "@/lib/api";
import { asNumber, formatCurrency, formatPct, formatWeight, pickArray, pickRecord, sentenceCase } from "@/lib/format";

type Row = Record<string, unknown>;

function usePerformanceLab() {
  const [data, setData] = useState<PerformanceLabPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [capabilities, setCapabilities] = useState<ApiCapabilities>(READ_ONLY_API_CAPABILITIES);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      fetchPerformanceLab(),
      fetchApiCapabilities().catch(() => READ_ONLY_API_CAPABILITIES)
    ])
      .then(([payload, capabilityPayload]) => {
        if (active) {
          setData(payload);
          setCapabilities(capabilityPayload);
        }
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
  }, [refreshNonce]);

  return { data, error, loading, capabilities, refresh: () => setRefreshNonce((value) => value + 1) };
}

const bucketColumns: DataTableColumn<Row>[] = [
  { key: "score_bucket", header: "Bucket", render: (row) => <span className="font-semibold text-white">{String(row.score_bucket ?? "N/A")}</span> },
  { key: "total_resolved", header: "Resolved", align: "right" },
  { key: "win_rate", header: "Win Rate", align: "right", render: (row) => formatPct(row.win_rate, 1) },
  { key: "gross_expectancy_pct", header: "Gross Exp.", align: "right", render: (row) => formatPct(row.gross_expectancy_pct ?? row.expectancy_pct, 2) },
  { key: "net_expectancy_pct", header: "Config. Net", align: "right", render: (row) => formatPct(row.net_expectancy_pct, 2) },
  { key: "max_drawdown_pct", header: "Max DD", align: "right", render: (row) => formatPct(row.max_drawdown_pct, 2) },
  { key: "risk_flag", header: "Risk", render: (row) => <StatusBadge tone={row.risk_flag === "Fragile" ? "negative" : row.risk_flag === "Watch" ? "warning" : "neutral"}>{String(row.risk_flag ?? "No data")}</StatusBadge> }
];

const outcomeColumns: DataTableColumn<Row>[] = [
  { key: "ticker", header: "Ticker", render: (row) => <span className="font-semibold text-white">{String(row.ticker ?? "N/A")}</span> },
  { key: "strategy", header: "Strategy", render: (row) => sentenceCase(row.strategy) },
  { key: "source", header: "Source", render: (row) => sentenceCase(row.source) },
  { key: "score", header: "Score", align: "right" },
  { key: "status", header: "Status", render: (row) => sentenceCase(row.status) },
  { key: "realized_return_pct", header: "Gross Return", align: "right", render: (row) => formatPct(row.realized_return_pct, 2) },
  { key: "evaluated_at", header: "Evaluated" }
];

function SummaryMetric({
  label,
  value,
  meta,
  tone = "neutral"
}: {
  label: string;
  value: React.ReactNode;
  meta: React.ReactNode;
  tone?: "positive" | "negative" | "warning" | "neutral";
}) {
  const toneClass = {
    positive: "text-[var(--green)]",
    negative: "text-[var(--red)]",
    warning: "text-[var(--amber)]",
    neutral: "text-[var(--text)]"
  }[tone];
  return (
    <div className="border-b border-r border-[var(--line-soft)] p-3">
      <div className="text-xs text-[var(--muted)]">{label}</div>
      <div className={`mono mt-1 text-xl font-semibold ${toneClass}`}>{value}</div>
      <div className="mt-1 text-xs leading-5 text-[var(--dim)]">{meta}</div>
    </div>
  );
}

function formatSnapshot(value: unknown): string {
  const parsed = Date.parse(String(value ?? ""));
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleString() : "No snapshot";
}

function todayInputValue() {
  return new Date().toISOString().slice(0, 10);
}

function initialLogEntry(): PerformanceLogInput {
  const today = todayInputValue();
  return {
    ticker: "",
    strategy_family: "short_term_swing",
    opened_on: today,
    closed_on: today,
    score: 70,
    entry_price: 0,
    exit_price: 0,
    status: "hit_target"
  };
}

export default function PerformancePage() {
  const { data, error, loading, capabilities, refresh } = usePerformanceLab();
  const [logEntry, setLogEntry] = useState<PerformanceLogInput>(initialLogEntry);
  const [logStatus, setLogStatus] = useState<string | null>(null);
  const [logError, setLogError] = useState<string | null>(null);
  const [logging, setLogging] = useState(false);

  function updateLogEntry<Key extends keyof PerformanceLogInput>(key: Key, value: PerformanceLogInput[Key]) {
    setLogEntry((current) => ({ ...current, [key]: value }));
  }

  function submitLogEntry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!capabilities.performance_log_mutations_enabled) return;
    setLogging(true);
    setLogStatus(null);
    setLogError(null);
    logPerformanceOutcome(logEntry)
      .then((payload) => {
        const result = pickRecord(payload.entry);
        setLogStatus(`${String(result.ticker ?? logEntry.ticker).toUpperCase()} logged at ${formatPct(result.realized_return_pct, 2)}.`);
        setLogEntry(initialLogEntry());
        refresh();
      })
      .catch((err: Error) => setLogError(err.message))
      .finally(() => setLogging(false));
  }

  const overall = pickRecord(data?.overall);
  const assumptions = pickRecord(data?.performance_assumptions);
  const riskContext = pickRecord(data?.risk_context);
  const scoreBuckets = pickArray(data?.score_buckets);
  const recentOutcomes = pickArray(data?.recent_outcomes);
  const triggerSensitivity = pickRecord(data?.trigger_sensitivity);
  const triggerMethods = pickArray(triggerSensitivity.methods);
  const entryLab = pickRecord(data?.entry_trigger_lab);
  const dayLab = pickRecord(entryLab.short_term_day);
  const entryMethods = pickArray(dayLab.methods);
  const byStrategy = data?.by_strategy ?? {};
  const transactionCostsConfigured = assumptions.transaction_costs_configured === true;
  const configuredCostPct = asNumber(assumptions.estimated_round_trip_cost_pct) ?? 0;
  const grossExpectancy = asNumber(overall.gross_expectancy_pct ?? overall.expectancy_pct);
  const netExpectancy = asNumber(overall.net_expectancy_pct);
  const resolvedSignals = asNumber(riskContext.resolved_signals ?? overall.resolved_signals) ?? 0;
  const totalSignals = asNumber(riskContext.total_signals ?? overall.total_signals) ?? 0;
  const openSignals = asNumber(riskContext.open_signals ?? overall.open_signals) ?? 0;
  const signalsPerWeek = asNumber(riskContext.signals_per_week);
  const annualizedSignals = asNumber(riskContext.annualized_signals);
  const turnoverSignalCount = asNumber(riskContext.turnover_signal_count) ?? 0;
  const turnoverLookbackDays = asNumber(riskContext.turnover_lookback_days) ?? 0;
  const deployedCapital = asNumber(riskContext.deployed_capital_weight);
  const holdingsCount = asNumber(riskContext.holdings_count);
  const exposureIsStale = riskContext.exposure_is_stale === true;
  const performanceWritesEnabled = capabilities.performance_log_mutations_enabled;

  const strategyRows = Object.entries(byStrategy).map(([key, value]) => ({
    name: key === "short_term_day" ? "1-2 Day" : "5-15 Day",
    grossExpectancy: asNumber(value.gross_expectancy_pct ?? value.expectancy_pct) ?? 0,
    winRate: asNumber(value.win_rate) ?? 0,
    resolved: asNumber(value.resolved_signals) ?? 0
  }));

  const bucketChartRows = scoreBuckets.map((row) => ({
    bucket: String(row.score_bucket ?? "N/A"),
    grossExpectancy: asNumber(row.gross_expectancy_pct ?? row.expectancy_pct) ?? 0,
    resolved: asNumber(row.total_resolved) ?? 0
  }));

  const triggerChartRows = triggerMethods.map((row) => ({
    method: String(row.method_label ?? "N/A"),
    expectancy: asNumber(row.expectancy_pct) ?? 0,
    triggerRate: (asNumber(row.trigger_rate) ?? 0) * 100
  }));

  let compoundedValue = 1;
  const recentCurve = recentOutcomes
    .slice()
    .reverse()
    .map((row, index) => {
      compoundedValue *= 1 + (asNumber(row.realized_return_pct) ?? 0) / 100;
      return {
        index: index + 1,
        ticker: row.ticker,
        cumulative: (compoundedValue - 1) * 100
      };
    });

  return (
    <div>
      <SectionHeader title="Performance" />

      {loading && !data ? <LoadingState title="Loading performance" message="Loading performance cohorts, risk context, and recent outcomes." /> : null}
      {error ? <TerminalPanel title="API error"><div role="alert" className="text-sm text-[var(--red)]">{error}</div></TerminalPanel> : null}

      {data ? (
        <div className="space-y-5">
          <TerminalPanel title="Performance and risk" eyebrow={String(assumptions.result_label ?? "Reporting assumptions unavailable")}>
            {!transactionCostsConfigured ? (
              <div role="note" className="mb-4 border-l-4 border-[var(--amber)] bg-[var(--amber-soft)] px-4 py-3 text-sm">
                <div className="font-semibold text-[var(--amber)]">Gross, before costs</div>
                <div className="mt-1 text-[var(--muted)]">
                  {String(assumptions.warning ?? "Commission and slippage are not modeled.")}
                </div>
              </div>
            ) : null}

            <div className="grid border-l border-t border-[var(--line-soft)] sm:grid-cols-2 xl:grid-cols-3">
              <SummaryMetric
                label="Gross expectancy"
                value={formatPct(grossExpectancy, 2)}
                meta="Per resolved signal before transaction costs"
                tone={(grossExpectancy ?? 0) >= 0 ? "positive" : "negative"}
              />
              <SummaryMetric
                label="Configured net expectancy"
                value={formatPct(netExpectancy, 2)}
                meta={
                  transactionCostsConfigured
                    ? `After ${formatPct(configuredCostPct, 4)} modeled round-trip cost`
                    : "Equals gross because configured transaction cost is zero; not a realistic net estimate"
                }
                tone={transactionCostsConfigured ? ((netExpectancy ?? 0) >= 0 ? "positive" : "negative") : "warning"}
              />
              <SummaryMetric
                label="Resolved sample"
                value={resolvedSignals.toLocaleString()}
                meta={`${totalSignals.toLocaleString()} logged · ${openSignals.toLocaleString()} open · ${formatPct(overall.win_rate, 1)} win rate`}
              />
              <SummaryMetric
                label="Max drawdown"
                value={formatPct(riskContext.max_drawdown_pct ?? overall.max_drawdown_pct, 2)}
                meta={`${String(riskContext.max_drawdown_basis ?? "Resolved signal-return curve")} Risk: ${String(riskContext.risk_flag ?? overall.risk_flag ?? "No data")}`}
                tone="negative"
              />
              <SummaryMetric
                label="Signal turnover"
                value={signalsPerWeek === null ? "N/A" : `${signalsPerWeek.toFixed(1)}/wk`}
                meta={`${turnoverSignalCount.toLocaleString()} logged in ${turnoverLookbackDays}d · ${annualizedSignals === null ? "N/A" : annualizedSignals.toFixed(0)} annualized`}
              />
              <SummaryMetric
                label="Deployed exposure"
                value={formatWeight(deployedCapital)}
                meta={`${holdingsCount === null ? "No" : holdingsCount.toLocaleString()} holdings · ${formatSnapshot(riskContext.exposure_snapshot_at)}${exposureIsStale ? " · stale snapshot" : ""}`}
                tone={exposureIsStale ? "warning" : "neutral"}
              />
            </div>

            <dl className="mt-4 grid gap-x-6 gap-y-3 border-t border-[var(--line-soft)] pt-4 text-sm sm:grid-cols-2 xl:grid-cols-3">
              <div>
                <dt className="text-[var(--dim)]">Commission</dt>
                <dd className="mono mt-1 text-[var(--text)]">{formatCurrency(assumptions.commission_per_side)} per side</dd>
              </div>
              <div>
                <dt className="text-[var(--dim)]">Slippage</dt>
                <dd className="mono mt-1 text-[var(--text)]">{String(assumptions.slippage_bps_per_side ?? 0)} bps per side</dd>
              </div>
              <div>
                <dt className="text-[var(--dim)]">Cost filter</dt>
                <dd className="mono mt-1 text-[var(--text)]">{assumptions.cost_filter_enabled ? "On" : "Off"}</dd>
              </div>
              <div>
                <dt className="text-[var(--dim)]">Reward/risk filter</dt>
                <dd className="mono mt-1 text-[var(--text)]">
                  {assumptions.reward_risk_filter_enabled ? `On · ${String(assumptions.min_reward_risk ?? "N/A")}:1 minimum` : "Off"}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--dim)]">Time stop</dt>
                <dd className="mono mt-1 text-[var(--text)]">
                  {assumptions.time_stop_enabled ? `On · ${String(assumptions.time_stop_max_holding_days ?? "N/A")}d` : "Off"}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--dim)]">Default notional</dt>
                <dd className="mono mt-1 text-[var(--text)]">{formatCurrency(assumptions.default_trade_notional)}</dd>
              </div>
            </dl>
          </TerminalPanel>

          <TerminalPanel title="Log completed trade" eyebrow="Manual outcome">
            {!performanceWritesEnabled ? (
              <div role="status" className="mb-4 border-b border-[var(--line-soft)] pb-4 text-sm text-[var(--amber)]">
                {capabilities.message}
              </div>
            ) : null}
            <form onSubmit={submitLogEntry} className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <fieldset disabled={!performanceWritesEnabled || logging} className="contents">
              <label className="grid gap-2 text-xs text-[var(--muted)]">
                Ticker
                <input
                  required
                  value={logEntry.ticker}
                  onChange={(event) => updateLogEntry("ticker", event.target.value.toUpperCase())}
                  className="field"
                  placeholder="AAPL"
                />
              </label>
              <label className="grid gap-2 text-xs text-[var(--muted)]">
                Strategy
                <select
                  value={logEntry.strategy_family}
                  onChange={(event) => updateLogEntry("strategy_family", event.target.value as PerformanceLogInput["strategy_family"])}
                  className="field"
                >
                  <option value="short_term_day">1-2 Day</option>
                  <option value="short_term_swing">5-15 Day</option>
                </select>
              </label>
              <label className="grid gap-2 text-xs text-[var(--muted)]">
                Opened
                <input
                  required
                  type="date"
                  value={logEntry.opened_on}
                  onChange={(event) => updateLogEntry("opened_on", event.target.value)}
                  className="field"
                />
              </label>
              <label className="grid gap-2 text-xs text-[var(--muted)]">
                Closed
                <input
                  required
                  type="date"
                  min={logEntry.opened_on}
                  value={logEntry.closed_on}
                  onChange={(event) => updateLogEntry("closed_on", event.target.value)}
                  className="field"
                />
              </label>
              <label className="grid gap-2 text-xs text-[var(--muted)]">
                Score
                <input
                  required
                  type="number"
                  min="0"
                  max="100"
                  step="1"
                  value={logEntry.score}
                  onChange={(event) => updateLogEntry("score", Number(event.target.value))}
                  className="field"
                />
              </label>
              <label className="grid gap-2 text-xs text-[var(--muted)]">
                Entry price
                <input
                  required
                  type="number"
                  min="0.0001"
                  step="0.0001"
                  value={logEntry.entry_price || ""}
                  onChange={(event) => updateLogEntry("entry_price", Number(event.target.value))}
                  className="field"
                />
              </label>
              <label className="grid gap-2 text-xs text-[var(--muted)]">
                Exit price
                <input
                  required
                  type="number"
                  min="0.0001"
                  step="0.0001"
                  value={logEntry.exit_price || ""}
                  onChange={(event) => updateLogEntry("exit_price", Number(event.target.value))}
                  className="field"
                />
              </label>
              <label className="grid gap-2 text-xs text-[var(--muted)]">
                Outcome
                <select
                  value={logEntry.status}
                  onChange={(event) => updateLogEntry("status", event.target.value as PerformanceLogInput["status"])}
                  className="field"
                >
                  <option value="hit_target">Target hit</option>
                  <option value="hit_stop">Stop hit</option>
                  <option value="expired">Time exit</option>
                </select>
              </label>
              <div className="flex items-end md:col-span-2 xl:col-span-4">
                <button type="submit" className="button button-primary disabled:cursor-not-allowed disabled:opacity-60">
                  {logging ? "Logging..." : "Log trade"}
                </button>
              </div>
              </fieldset>
            </form>
            {logStatus ? <div role="status" aria-live="polite" className="mt-3 text-sm text-[var(--green)]">{logStatus}</div> : null}
            {logError ? <div role="alert" className="mt-3 text-sm text-[var(--red)]">{logError}</div> : null}
          </TerminalPanel>

          <div className="grid gap-5 xl:grid-cols-2">
            <TerminalPanel title="Expectancy by strategy" eyebrow="Strategy separation">
              <ChartLegend
                items={[
                  { label: "Gross expectancy", color: "var(--chart-positive)" },
                  { label: "Win rate", color: "var(--chart-secondary)" }
                ]}
                summary="Compares gross expectancy and win rate across the two short-term strategy horizons."
              />
              <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                  <BarChart data={strategyRows}>
                    <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                    <XAxis dataKey="name" stroke="var(--dim)" fontSize={11} />
                    <YAxis stroke="var(--dim)" fontSize={11} />
                    <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                    <Bar dataKey="grossExpectancy" name="Gross expectancy %" fill="var(--chart-positive)" />
                    <Bar dataKey="winRate" name="Win rate %" fill="var(--chart-secondary)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </TerminalPanel>

            <TerminalPanel title="Score bucket edge" eyebrow="Calibration view">
              <ChartLegend
                items={[{ label: "Gross expectancy", color: "var(--chart-warning)" }]}
                summary="Gross expectancy by model score bucket; use the resolved sample table below to judge reliability."
              />
              <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                  <BarChart data={bucketChartRows}>
                    <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                    <XAxis dataKey="bucket" stroke="var(--dim)" fontSize={11} />
                    <YAxis stroke="var(--dim)" fontSize={11} />
                    <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                    <Bar dataKey="grossExpectancy" name="Gross expectancy %" fill="var(--chart-warning)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </TerminalPanel>
          </div>

          <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
            <TerminalPanel title="Trigger sensitivity" eyebrow="Capture vs quality">
              <ChartLegend
                items={[
                  { label: "Gross expectancy", color: "var(--chart-positive)" },
                  { label: "Trigger rate", color: "var(--chart-secondary)" }
                ]}
                summary="Shows the trade-off between how often an entry method triggers and the expectancy of its resolved signals."
              />
              <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                  <BarChart data={triggerChartRows}>
                    <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                    <XAxis dataKey="method" stroke="var(--dim)" fontSize={10} interval={0} />
                    <YAxis stroke="var(--dim)" fontSize={11} />
                    <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                    <Bar dataKey="expectancy" name="Gross expectancy %" fill="var(--chart-positive)" />
                    <Bar dataKey="triggerRate" name="Trigger rate %" fill="var(--chart-secondary)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </TerminalPanel>

            <TerminalPanel title="Resolved return curve" eyebrow="Recent outcomes">
              <ChartLegend
                items={[{ label: "Compounded gross return", color: "var(--chart-positive)" }]}
                summary="Sequential signal returns are compounded in evaluation order; this is not a portfolio equity curve."
              />
              <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                  <LineChart data={recentCurve}>
                    <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                    <XAxis dataKey="index" stroke="var(--dim)" fontSize={11} />
                    <YAxis stroke="var(--dim)" fontSize={11} />
                    <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                    <Line type="monotone" dataKey="cumulative" name="Compounded gross return %" stroke="var(--chart-positive)" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </TerminalPanel>
          </div>

          <TerminalPanel title="Entry trigger lab" eyebrow="1-2 day method comparison">
            <DataTable
              rows={entryMethods}
              columns={[
                { key: "method_label", header: "Method", render: (row) => <span className="font-semibold text-white">{String(row.method_label ?? "N/A")}</span> },
                { key: "resolved_signals", header: "Resolved", align: "right" },
                { key: "win_rate", header: "Win Rate", align: "right", render: (row) => formatPct(row.win_rate, 1) },
                { key: "expectancy_pct", header: "Gross Exp.", align: "right", render: (row) => formatPct(row.expectancy_pct, 2) },
                { key: "risk_flag", header: "Risk", render: (row) => <StatusBadge tone={row.risk_flag === "Fragile" ? "negative" : "neutral"}>{String(row.risk_flag ?? "No data")}</StatusBadge> },
                { key: "sample_quality", header: "Sample" }
              ]}
              emptyLabel="No entry trigger data available."
            />
          </TerminalPanel>

          <TerminalPanel title="Score buckets" eyebrow="Resolved cohorts">
            <DataTable rows={scoreBuckets} columns={bucketColumns} emptyLabel="No score bucket data available." />
          </TerminalPanel>

          <TerminalPanel title="Recent resolved signals" eyebrow="Outcome log">
            <DataTable rows={recentOutcomes} columns={outcomeColumns} emptyLabel="No resolved outcomes available." />
          </TerminalPanel>
        </div>
      ) : null}
    </div>
  );
}
