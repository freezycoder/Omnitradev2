"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { ChartLegend } from "@/components/ChartLegend";
import { DataTable, DataTableColumn } from "@/components/DataTable";
import { LoadingState } from "@/components/LoadingState";
import { MetricCard } from "@/components/MetricCard";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import { fetchPortfolio, PortfolioPayload } from "@/lib/api";
import { asNumber, formatCurrency, formatPct, formatWeight, pickArray, pickRecord, sentenceCase } from "@/lib/format";

type Row = Record<string, unknown>;

function usePortfolio() {
  const [data, setData] = useState<PortfolioPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetchPortfolio()
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
  }, []);

  return { data, error, loading };
}

const holdingColumns: DataTableColumn<Row>[] = [
  { key: "ticker", header: "Ticker", render: (row) => <span className="font-semibold text-white">{String(row.ticker ?? "N/A")}</span> },
  { key: "company", header: "Company" },
  { key: "strategy", header: "Strategy", render: (row) => sentenceCase(row.strategy) },
  { key: "final_weight", header: "Weight", align: "right", render: (row) => formatWeight(row.final_weight) },
  { key: "position_size", header: "Size", align: "right", render: (row) => asNumber(row.position_size)?.toFixed(2) ?? "N/A" },
  { key: "risk_penalty", header: "Risk Penalty", align: "right", render: (row) => asNumber(row.risk_penalty)?.toFixed(2) ?? "N/A" },
  { key: "historical_expectancy_pct", header: "Expectancy", align: "right", render: (row) => formatPct(row.historical_expectancy_pct, 2) },
  { key: "current_price", header: "Mark", align: "right", render: (row) => formatCurrency(row.current_price) }
];

const executionColumns: DataTableColumn<Row>[] = [
  { key: "rank", header: "Rank", align: "right" },
  { key: "ticker", header: "Ticker", render: (row) => <span className="font-semibold text-white">{String(row.ticker ?? "N/A")}</span> },
  { key: "strategy_family", header: "Strategy", render: (row) => sentenceCase(row.strategy_family) },
  { key: "edge_quality_score", header: "Edge", align: "right" },
  { key: "position_size", header: "Size", align: "right", render: (row) => asNumber(row.position_size)?.toFixed(2) ?? "N/A" },
  { key: "trigger_status", header: "Status", render: (row) => <StatusBadge tone={row.trigger_status === "triggered" ? "positive" : "warning"}>{sentenceCase(row.trigger_status)}</StatusBadge> },
  { key: "distance_to_trigger_pct", header: "Distance", align: "right", render: (row) => formatPct(row.distance_to_trigger_pct, 2) },
  { key: "historical_cohort_expectancy_pct", header: "Hist. Exp.", align: "right", render: (row) => formatPct(row.historical_cohort_expectancy_pct, 2) }
];

export default function PortfolioPage() {
  const { data, error, loading } = usePortfolio();

  const execution = pickRecord(data?.strategy_v1_execution);
  const counts = pickRecord(execution.counts);
  const portfolio = pickRecord(data?.strategy_v1_portfolio);
  const portfolioSummary = pickRecord(portfolio.summary);
  const pnl = pickRecord(data?.strategy_v1_portfolio_pnl);
  const pnlSummary = pickRecord(pnl.summary);
  const benchmarkPnl = pickRecord(data?.strategy_v1_benchmark_portfolio_pnl);
  const benchmarkSummary = pickRecord(benchmarkPnl.summary);
  const history = pickRecord(data?.strategy_v1_portfolio_history);
  const equityCurve = pickArray(history.equity_curve);
  const holdings = pickArray(portfolio.holdings);
  const triggered = pickArray(execution.top_triggered_signals);
  const activeDeploymentPct = (asNumber(pnlSummary.deployed_capital_weight) ?? 0) * 100;
  const benchmarkDeploymentPct = (asNumber(benchmarkSummary.deployed_capital_weight) ?? 0) * 100;
  const hasDeployment = activeDeploymentPct > 0 || benchmarkDeploymentPct > 0;

  const comparisonBars = [
    { name: "Active", returnPct: asNumber(pnlSummary.total_portfolio_pnl_pct) ?? 0, deployedPct: activeDeploymentPct },
    { name: "Benchmark", returnPct: asNumber(benchmarkSummary.total_portfolio_pnl_pct) ?? 0, deployedPct: benchmarkDeploymentPct }
  ];
  const barColors = ["var(--chart-positive)", "var(--chart-secondary)"];

  return (
    <div>
      <SectionHeader title="Portfolio" badge="Strategy v1" />

      {loading ? <LoadingState title="Loading portfolio" message="Loading portfolio positions, allocation, and history." /> : null}
      {error ? <TerminalPanel title="API error"><div role="alert" className="text-sm text-[var(--red)]">{error}</div></TerminalPanel> : null}

      {data ? (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Triggered" value={String(counts.execution_deduplicated_triggered_signals ?? 0)} meta="One signal per ticker" tone="positive" />
            <MetricCard label="Waiting" value={String(counts.waiting_signals ?? 0)} meta="Eligible but not below trigger" tone="warning" />
            <MetricCard label="Deployed" value={formatWeight(pnlSummary.deployed_capital_weight)} meta={`Cash ${formatWeight(pnlSummary.cash_reserve_weight)}`} tone="info" />
            <MetricCard label="Total PnL" value={formatPct(pnlSummary.total_portfolio_pnl_pct, 2)} meta="Weighted active portfolio" tone={(asNumber(pnlSummary.total_portfolio_pnl_pct) ?? 0) >= 0 ? "positive" : "negative"} />
          </div>

          <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
            <TerminalPanel title="Active vs Benchmark" eyebrow="Separate return and allocation scales">
              {hasDeployment ? (
                <>
                  <ChartLegend
                    items={[
                      { label: "Active", color: barColors[0] },
                      { label: "Benchmark", color: barColors[1] }
                    ]}
                    summary="Portfolio return and capital deployed are shown on separate axes so allocation cannot be mistaken for performance."
                  />
                  <div className="grid gap-5 sm:grid-cols-2">
                    <div>
                      <h3 className="mb-2 text-xs font-medium text-[var(--muted)]">Portfolio return (%)</h3>
                      <div className="h-60">
                        <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                          <BarChart data={comparisonBars}>
                            <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                            <XAxis dataKey="name" stroke="var(--dim)" fontSize={11} />
                            <YAxis stroke="var(--dim)" fontSize={11} unit="%" />
                            <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                            <Bar dataKey="returnPct" name="Portfolio return %" radius={[3, 3, 0, 0]}>
                              {comparisonBars.map((row, index) => <Cell key={row.name} fill={barColors[index]} />)}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                    <div>
                      <h3 className="mb-2 text-xs font-medium text-[var(--muted)]">Capital deployed (%)</h3>
                      <div className="h-60">
                        <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                          <BarChart data={comparisonBars}>
                            <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                            <XAxis dataKey="name" stroke="var(--dim)" fontSize={11} />
                            <YAxis stroke="var(--dim)" fontSize={11} domain={[0, 100]} unit="%" />
                            <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                            <Bar dataKey="deployedPct" name="Capital deployed %" radius={[3, 3, 0, 0]}>
                              {comparisonBars.map((row, index) => <Cell key={row.name} fill={barColors[index]} />)}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="border border-dashed border-[var(--line-soft)] p-5">
                  <div className="font-medium text-[var(--text)]">No capital is deployed</div>
                  <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted)]">
                    Return and allocation charts will appear after at least one eligible signal receives portfolio weight. The current strategy remains fully in cash.
                  </p>
                </div>
              )}
            </TerminalPanel>

            <TerminalPanel title="Allocation summary" eyebrow="Risk-adjusted weights">
              <div className="space-y-3 text-sm text-[var(--muted)]">
                <div className="flex justify-between border-b border-[var(--line-soft)] pb-2">
                  <span>Holdings</span>
                  <span className="mono text-white">{String(portfolioSummary.holdings_count ?? 0)}</span>
                </div>
                <div className="flex justify-between border-b border-[var(--line-soft)] pb-2">
                  <span>Weighted expectancy</span>
                  <span className="mono text-white">{formatPct(portfolioSummary.weighted_average_expectancy_pct, 2)}</span>
                </div>
                <div className="flex justify-between border-b border-[var(--line-soft)] pb-2">
                  <span>Risk penalty</span>
                  <span className="mono text-white">{asNumber(portfolioSummary.weighted_average_risk_penalty)?.toFixed(2) ?? "N/A"}</span>
                </div>
                <div className="leading-6 text-[var(--muted)]">{String(portfolioSummary.cash_reserve_reason ?? "Cash reserve reason unavailable.")}</div>
              </div>
            </TerminalPanel>
          </div>

          <TerminalPanel title="Portfolio history" eyebrow="Weighted equity curve">
            {hasDeployment && equityCurve.length > 0 ? (
              <>
                <ChartLegend
                  items={[{ label: "Weighted strategy return", color: "var(--chart-positive)" }]}
                  summary="Historical weighted portfolio return for periods when the strategy had deployed capital."
                />
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                    <AreaChart data={equityCurve}>
                      <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                      <XAxis dataKey="timestamp" stroke="var(--dim)" fontSize={11} minTickGap={28} />
                      <YAxis stroke="var(--dim)" fontSize={11} unit="%" />
                      <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                      <Area type="monotone" dataKey="strategy_weighted_pnl_pct" name="Strategy PnL %" stroke="var(--chart-positive)" fill="var(--chart-positive)" fillOpacity={0.1} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </>
            ) : (
              <div className="border border-dashed border-[var(--line-soft)] p-5">
                <div className="font-medium text-[var(--text)]">No deployed portfolio history</div>
                <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
                  The equity curve starts once capital is assigned to eligible holdings. Until then, the portfolio is represented by its cash reserve.
                </p>
              </div>
            )}
          </TerminalPanel>

          <TerminalPanel title="Current holdings" eyebrow="Portfolio Engine">
            <DataTable rows={holdings} columns={holdingColumns} emptyLabel="No active holdings passed eligibility and risk filters." />
          </TerminalPanel>

          <TerminalPanel title="Top triggered signals" eyebrow="Execution layer">
            <DataTable rows={triggered} columns={executionColumns} emptyLabel="No triggered execution signals are available right now." />
          </TerminalPanel>
        </div>
      ) : null}
    </div>
  );
}
