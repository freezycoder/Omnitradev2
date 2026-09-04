"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartLegend } from "@/components/ChartLegend";
import { DataTable, DataTableColumn } from "@/components/DataTable";
import { LoadingState } from "@/components/LoadingState";
import { MetricCard } from "@/components/MetricCard";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import { fetchLongTermPerformance, LongTermPerformancePayload } from "@/lib/api";
import { asNumber, formatCurrency, formatPct, pickArray, pickRecord } from "@/lib/format";

type Row = Record<string, unknown>;

const cohortColumns: DataTableColumn<Row>[] = [
  { key: "segment", header: "Segment", render: (row) => <span className="font-semibold text-white">{String(row.segment ?? "N/A")}</span> },
  { key: "total_signals", header: "Total", align: "right" },
  { key: "resolved_signals", header: "Resolved", align: "right" },
  { key: "win_rate", header: "Win Rate", align: "right", render: (row) => formatPct(row.win_rate, 1) },
  { key: "avg_return_pct", header: "Avg Return", align: "right", render: (row) => formatPct(row.avg_return_pct, 2) },
  { key: "expectancy_pct", header: "Expectancy", align: "right", render: (row) => formatPct(row.expectancy_pct, 2) },
  { key: "risk_flag", header: "Risk", render: (row) => <StatusBadge tone={row.risk_flag === "Fragile" ? "negative" : row.risk_flag === "Watch" ? "warning" : "neutral"}>{String(row.risk_flag ?? "No data")}</StatusBadge> },
  { key: "sample_quality", header: "Sample" }
];

const resolvedColumns: DataTableColumn<Row>[] = [
  { key: "ticker", header: "Ticker", render: (row) => <span className="font-semibold text-white">{String(row.ticker ?? "N/A")}</span> },
  { key: "company", header: "Company" },
  { key: "horizon", header: "Horizon" },
  { key: "recommendation", header: "Recommendation" },
  { key: "score", header: "Score", align: "right" },
  { key: "entry_price", header: "Entry", align: "right", render: (row) => formatCurrency(row.entry_price) },
  { key: "exit_price", header: "Exit", align: "right", render: (row) => formatCurrency(row.exit_price) },
  { key: "return_pct", header: "Return", align: "right", render: (row) => formatPct(row.return_pct, 2) }
];

const openColumns: DataTableColumn<Row>[] = [
  { key: "ticker", header: "Ticker", render: (row) => <span className="font-semibold text-white">{String(row.ticker ?? "N/A")}</span> },
  { key: "company", header: "Company" },
  { key: "horizon", header: "Horizon" },
  { key: "recommendation", header: "Recommendation" },
  { key: "score", header: "Score", align: "right" },
  { key: "entry_price", header: "Entry", align: "right", render: (row) => formatCurrency(row.entry_price) },
  { key: "age_days", header: "Age", align: "right" },
  { key: "days_to_maturity", header: "Maturity", align: "right" }
];

export function LongTermPerformancePage() {
  const [data, setData] = useState<LongTermPerformancePayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetchLongTermPerformance()
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

  const overall = pickRecord(data?.overall);
  const byHorizon = pickArray(data?.by_horizon);
  const byScore = pickArray(data?.by_score_bucket);
  const byRecommendation = pickArray(data?.by_recommendation);
  const byTrend = pickArray(data?.by_trend);
  const byAccountingRisk = pickArray(data?.by_accounting_risk);
  const recentResolved = pickArray(data?.recent_resolved);
  const openSignals = pickArray(data?.open_signals);

  const horizonRows = byHorizon.map((row) => ({
    horizon: String(row.segment ?? "N/A"),
    expectancy: asNumber(row.expectancy_pct) ?? 0,
    winRate: asNumber(row.win_rate) ?? 0,
    resolved: asNumber(row.resolved_signals) ?? 0
  }));

  const scoreRows = byScore.map((row) => ({
    bucket: String(row.segment ?? "N/A"),
    expectancy: asNumber(row.expectancy_pct) ?? 0,
    resolved: asNumber(row.resolved_signals) ?? 0
  }));

  return (
    <div>
      <SectionHeader title="Long-Term Performance" badge="3M / 6M / 12M" />

      {loading ? <LoadingState title="Loading long-term performance" message="Loading long-term cohorts, outcomes, and open signals." /> : null}
      {error ? <TerminalPanel title="API error"><div role="alert" className="text-sm text-[var(--red)]">{error}</div></TerminalPanel> : null}

      {data ? (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Tracked" value={String(overall.total_signals ?? 0)} meta={`${overall.open_signals ?? 0} open`} tone="info" />
            <MetricCard label="Resolved" value={String(overall.resolved_signals ?? 0)} meta={String(overall.sample_quality ?? "Sample pending")} tone="neutral" />
            <MetricCard label="Win Rate" value={formatPct(overall.win_rate, 1)} meta="Resolved long-term signals" tone="positive" />
            <MetricCard label="Expectancy" value={formatPct(overall.expectancy_pct, 2)} meta={`Risk: ${overall.risk_flag ?? "No data"}`} tone={(asNumber(overall.expectancy_pct) ?? 0) >= 0 ? "positive" : "negative"} />
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <TerminalPanel title="By horizon" eyebrow="Cohort expectancy">
              <ChartLegend
                items={[
                  { label: "Expectancy", color: "var(--chart-positive)" },
                  { label: "Win rate", color: "var(--chart-secondary)" }
                ]}
                summary="Compares historical expectancy and win rate across the 3, 6, and 12 month horizons."
              />
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                  <BarChart data={horizonRows}>
                    <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                    <XAxis dataKey="horizon" stroke="var(--dim)" fontSize={11} />
                    <YAxis stroke="var(--dim)" fontSize={11} />
                    <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                    <Bar dataKey="expectancy" name="Expectancy %" fill="var(--chart-positive)" />
                    <Bar dataKey="winRate" name="Win rate %" fill="var(--chart-secondary)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </TerminalPanel>

            <TerminalPanel title="By score bucket" eyebrow="Signal quality">
              <ChartLegend
                items={[
                  { label: "Expectancy", color: "var(--chart-warning)" },
                  { label: "Resolved sample", color: "var(--chart-secondary)" }
                ]}
                summary="Shows return expectancy beside the resolved sample size for each score bucket."
              />
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                  <BarChart data={scoreRows}>
                    <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                    <XAxis dataKey="bucket" stroke="var(--dim)" fontSize={11} />
                    <YAxis stroke="var(--dim)" fontSize={11} />
                    <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                    <Bar dataKey="expectancy" name="Expectancy %" fill="var(--chart-warning)" />
                    <Bar dataKey="resolved" name="Resolved" fill="var(--chart-secondary)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </TerminalPanel>
          </div>

          <TerminalPanel title="Horizon cohorts" eyebrow="Performance service">
            <DataTable rows={byHorizon} columns={cohortColumns} emptyLabel="No horizon cohorts are available yet." />
          </TerminalPanel>

          <div className="grid gap-5 xl:grid-cols-2">
            <TerminalPanel title="Recommendation cohorts" eyebrow="Labels">
              <DataTable rows={byRecommendation} columns={cohortColumns} emptyLabel="No recommendation cohorts are available yet." />
            </TerminalPanel>
            <TerminalPanel title="Trend cohorts" eyebrow="Trend context">
              <DataTable rows={byTrend} columns={cohortColumns} emptyLabel="No trend cohorts are available yet." />
            </TerminalPanel>
          </div>

          <TerminalPanel title="Accounting risk cohorts" eyebrow="Quality overlay">
            <DataTable rows={byAccountingRisk} columns={cohortColumns} emptyLabel="No accounting-risk cohorts are available yet." />
          </TerminalPanel>

          <TerminalPanel title="Recent resolved signals" eyebrow="Outcome log">
            <DataTable rows={recentResolved} columns={resolvedColumns} emptyLabel="No resolved long-term signals are available yet." />
          </TerminalPanel>

          <TerminalPanel title="Open signals" eyebrow="Maturity queue">
            <DataTable rows={openSignals} columns={openColumns} emptyLabel="No open long-term signals are available." />
          </TerminalPanel>
        </div>
      ) : null}
    </div>
  );
}
