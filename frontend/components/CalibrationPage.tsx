"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CalibrationResearchWorkbench } from "@/components/CalibrationResearchWorkbench";
import { ChartLegend } from "@/components/ChartLegend";
import { DataTable, DataTableColumn } from "@/components/DataTable";
import { LoadingState } from "@/components/LoadingState";
import { MetricCard } from "@/components/MetricCard";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import { CalibrationPayload, fetchCalibration } from "@/lib/api";
import { asNumber, formatPct, pickArray, pickRecord, sentenceCase } from "@/lib/format";

type Row = Record<string, unknown>;

const calibrationColumns = (labelKey: string): DataTableColumn<Row>[] => [
  { key: labelKey, header: "Bucket", render: (row) => <span className="font-semibold text-white">{String(row[labelKey] ?? "N/A")}</span> },
  { key: "resolved_signals", header: "Resolved", align: "right" },
  { key: "wins", header: "Wins", align: "right" },
  { key: "losses", header: "Losses", align: "right" },
  { key: "win_rate", header: "Win Rate", align: "right", render: (row) => formatPct(row.win_rate, 1) },
  { key: "avg_return_pct", header: "Avg Return", align: "right", render: (row) => formatPct(row.avg_return_pct, 2) },
  { key: "expectancy_pct", header: "Gross Exp.", align: "right", render: (row) => formatPct(row.expectancy_pct, 2) },
  { key: "net_expectancy_pct", header: "Net Exp.", align: "right", render: (row) => formatPct(row.net_expectancy_pct, 2) }
];

const strategyColumns: DataTableColumn<Row>[] = [
  { key: "label", header: "Strategy", render: (row) => <span className="font-semibold text-white">{String(row.label ?? sentenceCase(row.strategy_family))}</span> },
  { key: "total_signals", header: "Total", align: "right" },
  { key: "resolved_signals", header: "Resolved", align: "right" },
  { key: "open_signals", header: "Open", align: "right" },
  { key: "win_rate", header: "Win Rate", align: "right", render: (row) => formatPct(row.win_rate, 1) },
  { key: "expectancy_pct", header: "Gross Exp.", align: "right", render: (row) => formatPct(row.expectancy_pct, 2) },
  { key: "net_expectancy_pct", header: "Net Exp.", align: "right", render: (row) => formatPct(row.net_expectancy_pct, 2) },
  { key: "avg_score", header: "Avg Score", align: "right" }
];

const regimeColumns: DataTableColumn<Row>[] = [
  { key: "label", header: "Regime", render: (row) => <span className="font-semibold text-white">{String(row.label ?? sentenceCase(row.regime))}</span> },
  { key: "total_signals", header: "Total", align: "right" },
  { key: "resolved_signals", header: "Resolved", align: "right" },
  { key: "open_signals", header: "Open", align: "right" },
  { key: "win_rate", header: "Win Rate", align: "right", render: (row) => formatPct(row.win_rate, 1) },
  { key: "expectancy_pct", header: "Gross Exp.", align: "right", render: (row) => formatPct(row.expectancy_pct, 2) },
  { key: "net_expectancy_pct", header: "Net Exp.", align: "right", render: (row) => formatPct(row.net_expectancy_pct, 2) },
  { key: "avg_score", header: "Avg Score", align: "right" },
  { key: "risk_flag", header: "Risk", render: (row) => String(row.risk_flag ?? "N/A") }
];

function DiagnosticCard({ diagnostic }: { diagnostic: Row }) {
  const status = String(diagnostic.status ?? "N/A");
  const tone = status === "Aligned" ? "positive" : status === "Not aligned" ? "negative" : "warning";
  return (
    <TerminalPanel title={String(diagnostic.title ?? "Diagnostic")} eyebrow="Calibration diagnostic">
      <div className="space-y-3 text-sm text-[var(--muted)]">
        <StatusBadge tone={tone}>{status}</StatusBadge>
        <div className="text-base leading-7 text-white">{String(diagnostic.summary ?? "No diagnostic summary available.")}</div>
        <div className="border-t border-[var(--line-soft)] pt-3">{String(diagnostic.expectation ?? "")}</div>
      </div>
    </TerminalPanel>
  );
}

export function CalibrationPage() {
  const [data, setData] = useState<CalibrationPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    fetchCalibration()
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

  const summary = pickRecord(data?.summary);
  const activeThresholds = pickRecord(data?.active_thresholds);
  const edgeWeights = pickRecord(data?.edge_weights);
  const costModel = pickRecord(data?.cost_model);
  const scoreBuckets = pickArray(data?.score_buckets);
  const strategyComparison = pickArray(data?.strategy_comparison);
  const regimeComparison = pickArray(data?.regime_comparison);
  const confidenceAnalysis = pickArray(data?.confidence_analysis);
  const accountingRiskAnalysis = pickArray(data?.accounting_risk_analysis);
  const diagnostics = pickRecord(data?.diagnostics);
  const researchCalibration = pickRecord(data?.research_calibration);
  const alternativeSignalAnalysis = pickRecord(data?.alternative_signal_analysis);
  const alternativeCohorts = pickArray(alternativeSignalAnalysis.cohorts);
  const alternativeRequirements = Object.entries(pickRecord(alternativeSignalAnalysis.requirements)).map(([key, value]) => {
    const requirement = pickRecord(value);
    return {
      requirement: sentenceCase(key),
      required: requirement.required,
      current: requirement.current,
      status: requirement.passed ? "Passed" : "Pending"
    };
  });
  const positiveValidationFolds = pickArray(alternativeSignalAnalysis.validation_folds).filter((row) => row.positive === true).length;
  const relativeStrengthAnalysis = pickRecord(data?.relative_strength_analysis);
  const relativeStrengthCohorts = pickArray(relativeStrengthAnalysis.cohorts);
  const relativeStrengthRequirements = Object.entries(pickRecord(relativeStrengthAnalysis.requirements)).map(([key, value]) => {
    const requirement = pickRecord(value);
    return {
      requirement: sentenceCase(key),
      required: requirement.required,
      current: requirement.current,
      status: requirement.passed ? "Passed" : "Pending"
    };
  });
  const positiveRelativeStrengthFolds = pickArray(relativeStrengthAnalysis.validation_folds).filter((row) => row.positive === true).length;
  const earningsIntelligenceAnalysis = pickRecord(data?.earnings_intelligence_analysis);
  const earningsIntelligenceCohorts = pickArray(earningsIntelligenceAnalysis.cohorts);
  const earningsIntelligenceRequirements = Object.entries(pickRecord(earningsIntelligenceAnalysis.requirements)).map(([key, value]) => {
    const requirement = pickRecord(value);
    return {
      requirement: sentenceCase(key),
      required: requirement.required,
      current: requirement.current,
      status: requirement.passed ? "Passed" : "Pending"
    };
  });
  const positiveEarningsFolds = pickArray(earningsIntelligenceAnalysis.validation_folds).filter((row) => row.positive === true).length;

  const scoreChartRows = scoreBuckets.map((row) => ({
    bucket: String(row.score_bucket ?? "N/A"),
    expectancy: asNumber(row.net_expectancy_pct) ?? 0,
    winRate: asNumber(row.win_rate) ?? 0
  }));

  const strategyChartRows = strategyComparison.map((row) => ({
    strategy: String(row.label ?? row.strategy_family ?? "N/A"),
    expectancy: asNumber(row.net_expectancy_pct) ?? 0,
    winRate: asNumber(row.win_rate) ?? 0
  }));

  const regimeChartRows = regimeComparison.map((row) => ({
    regime: String(row.label ?? row.regime ?? "N/A"),
    expectancy: asNumber(row.net_expectancy_pct) ?? 0,
    winRate: asNumber(row.win_rate) ?? 0
  }));

  const thresholdRows = [
    { setting: "Short scan floor", value: activeThresholds.min_short_term_scan_score },
    { setting: "Long scan floor", value: activeThresholds.min_long_term_scan_score },
    { setting: "Execution score", value: activeThresholds.min_execution_score },
    { setting: "Pullback", value: formatPct(activeThresholds.strategy_v1_pullback_pct, 2) },
    { setting: "RR filter", value: activeThresholds.reward_risk_filter_enabled ? `On · ${activeThresholds.min_reward_risk}` : "Off" },
    { setting: "Time stop", value: activeThresholds.time_stop_enabled ? `On · ${activeThresholds.time_stop_max_holding_days}d` : "Off" }
  ];

  const edgeWeightRows = Object.entries(edgeWeights).map(([key, value]) => ({
    setting: sentenceCase(key),
    value
  }));

  return (
    <div>
      <SectionHeader title="Calibration" />

      {loading ? <LoadingState title="Loading calibration" message="Loading calibration cohorts, thresholds, and diagnostics." /> : null}
      {error ? <TerminalPanel title="API error"><div role="alert" className="text-sm text-[var(--red)]">{error}</div></TerminalPanel> : null}

      {data ? (
        <div className="space-y-5">
          <CalibrationResearchWorkbench research={researchCalibration} />

          <TerminalPanel title="Alternative-signal activation gate" eyebrow="SEC + classified news + FRED · shadow only">
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Directional Sample" value={String(alternativeSignalAnalysis.directional_resolved_signals ?? 0)} meta="Resolved non-neutral shadow signals" tone="info" />
                <MetricCard label="Directional Net Exp." value={formatPct(alternativeSignalAnalysis.directional_net_expectancy_pct, 2)} meta="Impact-aligned after modeled costs" tone={(asNumber(alternativeSignalAnalysis.directional_net_expectancy_pct) ?? 0) > 0 ? "positive" : "warning"} />
                <MetricCard label="Positive Folds" value={String(positiveValidationFolds)} meta="Chronological validation blocks" tone={positiveValidationFolds >= 2 ? "positive" : "warning"} />
                <MetricCard label="Activation" value={alternativeSignalAnalysis.activation_ready ? "Review Ready" : "Locked"} meta="Never activates automatically" tone={alternativeSignalAnalysis.activation_ready ? "positive" : "warning"} />
              </div>
              <DiagnosticCard diagnostic={pickRecord(alternativeSignalAnalysis.diagnostic)} />
              <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
                <DataTable
                  rows={alternativeRequirements}
                  columns={[
                    { key: "requirement", header: "Evidence gate", render: (row) => <span className="font-semibold text-white">{String(row.requirement)}</span> },
                    { key: "required", header: "Required", align: "right" },
                    { key: "current", header: "Current", align: "right" },
                    { key: "status", header: "Status", render: (row) => <StatusBadge tone={row.status === "Passed" ? "positive" : "warning"}>{String(row.status)}</StatusBadge> }
                  ]}
                  emptyLabel="No activation requirements are available."
                />
                <DataTable
                  rows={alternativeCohorts}
                  columns={calibrationColumns("shadow_band")}
                  emptyLabel="New shadow observations will appear after signals resolve."
                />
              </div>
            </div>
          </TerminalPanel>

          <TerminalPanel title="Relative-strength activation gate" eyebrow="SPY + sector ETF leadership · shadow only">
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Directional Sample" value={String(relativeStrengthAnalysis.directional_resolved_signals ?? 0)} meta="Resolved non-neutral leadership signals" tone="info" />
                <MetricCard label="Directional Net Exp." value={formatPct(relativeStrengthAnalysis.directional_net_expectancy_pct, 2)} meta="Leadership-aligned after modeled costs" tone={(asNumber(relativeStrengthAnalysis.directional_net_expectancy_pct) ?? 0) > 0 ? "positive" : "warning"} />
                <MetricCard label="Positive Folds" value={String(positiveRelativeStrengthFolds)} meta="Chronological validation blocks" tone={positiveRelativeStrengthFolds >= 2 ? "positive" : "warning"} />
                <MetricCard label="Activation" value={relativeStrengthAnalysis.activation_ready ? "Review Ready" : "Locked"} meta="Never activates automatically" tone={relativeStrengthAnalysis.activation_ready ? "positive" : "warning"} />
              </div>
              <DiagnosticCard diagnostic={pickRecord(relativeStrengthAnalysis.diagnostic)} />
              <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
                <DataTable
                  rows={relativeStrengthRequirements}
                  columns={[
                    { key: "requirement", header: "Evidence gate", render: (row) => <span className="font-semibold text-white">{String(row.requirement)}</span> },
                    { key: "required", header: "Required", align: "right" },
                    { key: "current", header: "Current", align: "right" },
                    { key: "status", header: "Status", render: (row) => <StatusBadge tone={row.status === "Passed" ? "positive" : "warning"}>{String(row.status)}</StatusBadge> }
                  ]}
                  emptyLabel="No relative-strength activation requirements are available."
                />
                <DataTable
                  rows={relativeStrengthCohorts}
                  columns={calibrationColumns("relative_strength_band")}
                  emptyLabel="Relative-strength cohorts will appear after the new signals resolve."
                />
              </div>
            </div>
          </TerminalPanel>

          <TerminalPanel title="Earnings-intelligence activation gate" eyebrow="Surprises + estimates + revisions · shadow only">
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="Directional Sample" value={String(earningsIntelligenceAnalysis.directional_resolved_signals ?? 0)} meta="Resolved non-neutral earnings signals" tone="info" />
                <MetricCard label="Directional Net Exp." value={formatPct(earningsIntelligenceAnalysis.directional_net_expectancy_pct, 2)} meta="Earnings-aligned after modeled costs" tone={(asNumber(earningsIntelligenceAnalysis.directional_net_expectancy_pct) ?? 0) > 0 ? "positive" : "warning"} />
                <MetricCard label="Positive Folds" value={String(positiveEarningsFolds)} meta="Chronological validation blocks" tone={positiveEarningsFolds >= 2 ? "positive" : "warning"} />
                <MetricCard label="Activation" value={earningsIntelligenceAnalysis.activation_ready ? "Review Ready" : "Locked"} meta="Never activates automatically" tone={earningsIntelligenceAnalysis.activation_ready ? "positive" : "warning"} />
              </div>
              <DiagnosticCard diagnostic={pickRecord(earningsIntelligenceAnalysis.diagnostic)} />
              <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
                <DataTable
                  rows={earningsIntelligenceRequirements}
                  columns={[
                    { key: "requirement", header: "Evidence gate", render: (row) => <span className="font-semibold text-white">{String(row.requirement)}</span> },
                    { key: "required", header: "Required", align: "right" },
                    { key: "current", header: "Current", align: "right" },
                    { key: "status", header: "Status", render: (row) => <StatusBadge tone={row.status === "Passed" ? "positive" : "warning"}>{String(row.status)}</StatusBadge> }
                  ]}
                  emptyLabel="No earnings-intelligence activation requirements are available."
                />
                <DataTable
                  rows={earningsIntelligenceCohorts}
                  columns={calibrationColumns("earnings_intelligence_band")}
                  emptyLabel="Earnings-intelligence cohorts will appear after the new signals resolve."
                />
              </div>
            </div>
          </TerminalPanel>

          <details className="border border-[var(--line-soft)] border-t-[var(--line-strong)] bg-[var(--surface)]">
            <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-[var(--text)] marker:text-[var(--accent)]">
              Historical cohort diagnostics
              <span className="ml-3 text-xs font-normal text-[var(--dim)]">
                Descriptive views using the configured cost model
              </span>
            </summary>
            <div className="space-y-5 border-t border-[var(--line-soft)] p-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Resolved Sample" value={String(summary.resolved_signals ?? 0)} meta="Signals with outcomes" tone="info" />
            <MetricCard label="Buckets" value={String(summary.bucket_count ?? 0)} meta="Active score buckets" tone="neutral" />
            <MetricCard label="Regimes" value={String(summary.regime_count ?? 0)} meta={String(pickRecord(diagnostics.regime_alignment).status ?? "Regime alignment")} tone="info" />
            <MetricCard label="Cost Drag" value={formatPct(summary.estimated_transaction_cost_pct, 4)} meta="Round-trip model" tone="neutral" />
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <TerminalPanel title="Active thresholds" eyebrow="Strategy_v1 alignment">
              <DataTable
                rows={thresholdRows}
                columns={[
                  { key: "setting", header: "Setting", render: (row) => <span className="font-semibold text-white">{String(row.setting)}</span> },
                  { key: "value", header: "Value", align: "right" }
                ]}
                emptyLabel="No threshold data is available."
              />
            </TerminalPanel>
            <TerminalPanel title="Edge weights and costs" eyebrow="Ranking model">
              <div className="grid gap-4 md:grid-cols-2">
                <DataTable
                  rows={edgeWeightRows}
                  columns={[
                    { key: "setting", header: "Weight", render: (row) => <span className="font-semibold text-white">{String(row.setting)}</span> },
                    { key: "value", header: "Value", align: "right" }
                  ]}
                  emptyLabel="No edge-weight data is available."
                />
                <div className="grid gap-3">
                  <MetricCard label="Commission" value={String(costModel.commission_per_trade ?? 0)} meta="Per trade" tone="neutral" />
                  <MetricCard label="Slippage" value={String(costModel.slippage_bps ?? 0)} meta="Basis points" tone="neutral" />
                </div>
              </div>
            </TerminalPanel>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <TerminalPanel title="Score bucket calibration" eyebrow="Expectancy and win rate">
              <ChartLegend
                items={[
                  { label: "Net expectancy", color: "var(--chart-positive)" },
                  { label: "Win rate", color: "var(--chart-secondary)" }
                ]}
                summary="Compares the net return expectation and historical win rate for each score bucket."
              />
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                  <BarChart data={scoreChartRows}>
                    <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                    <XAxis dataKey="bucket" stroke="var(--dim)" fontSize={11} />
                    <YAxis stroke="var(--dim)" fontSize={11} />
                    <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                    <Bar dataKey="expectancy" name="Net expectancy %" fill="var(--chart-positive)" />
                    <Bar dataKey="winRate" name="Win rate %" fill="var(--chart-secondary)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </TerminalPanel>
            <TerminalPanel title="Strategy comparison" eyebrow="Day vs swing">
              <ChartLegend
                items={[
                  { label: "Net expectancy", color: "var(--chart-warning)" },
                  { label: "Win rate", color: "var(--chart-secondary)" }
                ]}
                summary="Compares net expectancy and win rate across short-term strategy families."
              />
              <div className="h-72">
                <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                  <BarChart data={strategyChartRows}>
                    <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                    <XAxis dataKey="strategy" stroke="var(--dim)" fontSize={11} />
                    <YAxis stroke="var(--dim)" fontSize={11} />
                    <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                    <Bar dataKey="expectancy" name="Net expectancy %" fill="var(--chart-warning)" />
                    <Bar dataKey="winRate" name="Win rate %" fill="var(--chart-secondary)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </TerminalPanel>
          </div>

          <TerminalPanel title="Regime calibration" eyebrow="Momentum vs mean reversion">
            <div className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
              <div className="min-w-0">
                <ChartLegend
                  items={[
                    { label: "Net expectancy", color: "var(--chart-positive)" },
                    { label: "Win rate", color: "var(--chart-secondary)" }
                  ]}
                  summary="Shows whether signal performance remains aligned across market regimes."
                />
                <div className="h-72">
                  <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
                    <BarChart data={regimeChartRows}>
                      <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                      <XAxis dataKey="regime" stroke="var(--dim)" fontSize={11} />
                      <YAxis stroke="var(--dim)" fontSize={11} />
                      <Tooltip contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }} />
                      <Bar dataKey="expectancy" name="Net expectancy %" fill="var(--chart-positive)" />
                      <Bar dataKey="winRate" name="Win rate %" fill="var(--chart-secondary)" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
              <DataTable rows={regimeComparison} columns={regimeColumns} emptyLabel="No regime calibration rows are available yet." />
            </div>
          </TerminalPanel>

          <div className="grid gap-5 xl:grid-cols-3">
            <DiagnosticCard diagnostic={pickRecord(diagnostics.score_calibration)} />
            <DiagnosticCard diagnostic={pickRecord(diagnostics.regime_alignment)} />
            <DiagnosticCard diagnostic={pickRecord(diagnostics.confidence_alignment)} />
          </div>

          <DiagnosticCard diagnostic={pickRecord(diagnostics.accounting_risk_alignment)} />

          <TerminalPanel title="Score buckets" eyebrow="Resolved cohorts">
            <DataTable rows={scoreBuckets} columns={calibrationColumns("score_bucket")} emptyLabel="No score bucket calibration rows are available." />
          </TerminalPanel>

          <TerminalPanel title="Strategy comparison" eyebrow="Short-term families">
            <DataTable rows={strategyComparison} columns={strategyColumns} emptyLabel="No strategy comparison rows are available." />
          </TerminalPanel>

          <div className="grid gap-5 xl:grid-cols-2">
            <TerminalPanel title="Confidence bands" eyebrow="Recommendation confidence">
              <DataTable rows={confidenceAnalysis} columns={calibrationColumns("confidence_band")} emptyLabel="No confidence-band rows are available." />
            </TerminalPanel>
            <TerminalPanel title="Accounting risk bands" eyebrow="Quality overlay">
              <DataTable rows={accountingRiskAnalysis} columns={calibrationColumns("accounting_risk_band")} emptyLabel="No accounting-risk rows are available." />
            </TerminalPanel>
          </div>
            </div>
          </details>
        </div>
      ) : null}
    </div>
  );
}
