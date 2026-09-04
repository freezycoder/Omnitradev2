"use client";

import { useEffect, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { ChartLegend } from "@/components/ChartLegend";
import { DataTable, DataTableColumn } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import {
  asNumber,
  formatPct,
  pickArray,
  pickRecord,
  sentenceCase
} from "@/lib/format";

type Row = Record<string, unknown>;

const strategyOptions = [
  { value: "short_term_day", label: "1–2 Day Trades" },
  { value: "short_term_swing", label: "5–15 Day Swings" }
];

const regimeOptions = [
  { value: "ALL", label: "All Regimes" },
  { value: "MOMENTUM", label: "Momentum" },
  { value: "MEAN_REVERSION", label: "Mean Reversion" }
];

function verdictTone(verdict: string): "positive" | "negative" | "warning" | "neutral" | "info" {
  if (verdict === "strong_shadow_candidate") return "positive";
  if (verdict === "promising_for_shadow") return "info";
  if (verdict === "negative") return "negative";
  if (verdict === "unstable" || verdict === "insufficient") return "warning";
  return "neutral";
}

function evidenceTone(evidence: string): "positive" | "warning" | "neutral" {
  if (evidence === "established") return "positive";
  if (evidence === "developing") return "warning";
  return "neutral";
}

function comparisonRow(label: string, row: Row): Row {
  const low = asNumber(row.confidence_interval_low_pct);
  const high = asNumber(row.confidence_interval_high_pct);
  return {
    variant: label,
    min_score: row.min_score,
    oos_resolved_signals: row.oos_resolved_signals,
    oos_distinct_signal_dates: row.oos_distinct_signal_dates,
    oos_net_expectancy_pct: row.oos_net_expectancy_pct,
    interval:
      low === null || high === null
        ? "Unavailable"
        : `${formatPct(low, 2)} to ${formatPct(high, 2)}`,
    folds: `${String(row.positive_fold_count ?? 0)}/${String(row.eligible_fold_count ?? 0)}`,
    evidence_level: row.evidence_level,
    verdict: row.verdict
  };
}

const comparisonColumns: DataTableColumn<Row>[] = [
  {
    key: "variant",
    header: "Variant",
    render: (row) => (
      <span className="font-semibold text-[var(--text)]">{String(row.variant)}</span>
    )
  },
  { key: "min_score", header: "Score Floor", align: "right" },
  { key: "oos_resolved_signals", header: "OOS Signals", align: "right" },
  { key: "oos_distinct_signal_dates", header: "Signal Dates", align: "right" },
  {
    key: "oos_net_expectancy_pct",
    header: "OOS Net Exp.",
    align: "right",
    render: (row) => formatPct(row.oos_net_expectancy_pct, 2)
  },
  { key: "interval", header: "80% Clustered Interval", align: "right" },
  { key: "folds", header: "Positive Folds", align: "right" },
  {
    key: "evidence_level",
    header: "Evidence",
    render: (row) => {
      const evidence = String(row.evidence_level ?? "insufficient");
      return <StatusBadge tone={evidenceTone(evidence)}>{sentenceCase(evidence)}</StatusBadge>;
    }
  },
  {
    key: "verdict",
    header: "Verdict",
    render: (row) => {
      const verdict = String(row.verdict ?? "insufficient");
      return <StatusBadge tone={verdictTone(verdict)}>{sentenceCase(verdict)}</StatusBadge>;
    }
  }
];

const sensitivityColumns: DataTableColumn<Row>[] = [
  {
    key: "min_score",
    header: "Score Floor",
    render: (row) => (
      <span className="font-semibold text-[var(--text)]">{String(row.min_score)}</span>
    )
  },
  { key: "oos_resolved_signals", header: "OOS Signals", align: "right" },
  { key: "oos_distinct_signal_dates", header: "Dates", align: "right" },
  {
    key: "oos_win_rate_pct",
    header: "Win Rate",
    align: "right",
    render: (row) => formatPct(row.oos_win_rate_pct, 1)
  },
  {
    key: "oos_net_expectancy_pct",
    header: "Net Expectancy",
    align: "right",
    render: (row) => formatPct(row.oos_net_expectancy_pct, 2)
  },
  {
    key: "interval",
    header: "80% Interval",
    align: "right"
  },
  {
    key: "positive_fold_count",
    header: "Positive Folds",
    align: "right",
    render: (row) =>
      `${String(row.positive_fold_count ?? 0)}/${String(row.eligible_fold_count ?? 0)}`
  },
  {
    key: "verdict",
    header: "Verdict",
    render: (row) => {
      const verdict = String(row.verdict ?? "insufficient");
      return <StatusBadge tone={verdictTone(verdict)}>{sentenceCase(verdict)}</StatusBadge>;
    }
  }
];

const foldColumns: DataTableColumn<Row>[] = [
  { key: "fold", header: "Fold" },
  { key: "training_end", header: "Training Ends" },
  { key: "validation_start", header: "Validation Starts" },
  { key: "validation_end", header: "Validation Ends" },
  { key: "training_observations", header: "Train Signals", align: "right" },
  { key: "validation_observations", header: "Validation Signals", align: "right" },
  {
    key: "eligible",
    header: "Status",
    render: (row) => (
      <StatusBadge tone={row.eligible ? "positive" : "warning"}>
        {row.eligible ? "Eligible" : "Insufficient"}
      </StatusBadge>
    )
  }
];

const reliabilityColumns: DataTableColumn<Row>[] = [
  {
    key: "confidence_band",
    header: "Confidence Band",
    render: (row) => (
      <span className="font-semibold text-[var(--text)]">
        {String(row.confidence_band)}
      </span>
    )
  },
  { key: "resolved_signals", header: "OOS Signals", align: "right" },
  { key: "distinct_signal_dates", header: "Dates", align: "right" },
  {
    key: "observed_success_rate_pct",
    header: "Observed Success",
    align: "right",
    render: (row) => formatPct(row.observed_success_rate_pct, 1)
  },
  {
    key: "shrunk_reference_rate_pct",
    header: "Shrunk Reference",
    align: "right",
    render: (row) => formatPct(row.shrunk_reference_rate_pct, 1)
  },
  {
    key: "interval",
    header: "80% Interval",
    align: "right"
  },
  {
    key: "evidence_level",
    header: "Evidence",
    render: (row) => {
      const evidence = String(row.evidence_level ?? "insufficient");
      return <StatusBadge tone={evidenceTone(evidence)}>{sentenceCase(evidence)}</StatusBadge>;
    }
  }
];

export function CalibrationResearchWorkbench({ research }: { research: Row }) {
  const methodology = pickRecord(research.methodology);
  const dataQuality = pickRecord(research.data_quality);
  const deploymentGuard = pickRecord(research.deployment_guard);
  const reliability = pickRecord(research.confidence_reliability);
  const thresholdRows = pickArray(research.threshold_sensitivity);
  const comparisons = pickArray(research.current_vs_candidate);
  const folds = pickArray(research.walk_forward_folds);
  const thresholds = Array.isArray(methodology.score_thresholds)
    ? methodology.score_thresholds.map((value) => Number(value))
    : [55, 60, 65, 70, 75, 80, 85];
  const costs = Array.isArray(methodology.cost_scenarios_bps)
    ? methodology.cost_scenarios_bps.map((value) => Number(value))
    : [5, 10, 20];

  const [strategy, setStrategy] = useState("short_term_swing");
  const [regime, setRegime] = useState("ALL");
  const [costBps, setCostBps] = useState(
    Number(methodology.default_cost_scenario_bps ?? 10)
  );
  const [candidateThreshold, setCandidateThreshold] = useState(
    Number(methodology.current_execution_threshold ?? 70)
  );

  const serverComparison = comparisons.find(
    (row) => row.strategy_family === strategy && row.regime === regime
  );
  const suggestedThreshold = asNumber(
    pickRecord(serverComparison?.candidate).min_score
  );

  useEffect(() => {
    if (suggestedThreshold !== null) setCandidateThreshold(suggestedThreshold);
  }, [strategy, regime, suggestedThreshold]);

  const selectedRows = thresholdRows
    .filter(
      (row) =>
        row.strategy_family === strategy &&
        row.regime === regime &&
        asNumber(row.cost_bps) === costBps
    )
    .sort((left, right) => Number(left.min_score) - Number(right.min_score));
  const currentThreshold = Number(methodology.current_execution_threshold ?? 70);
  const currentRow = selectedRows.find(
    (row) => asNumber(row.min_score) === currentThreshold
  );
  const candidateRow = selectedRows.find(
    (row) => asNumber(row.min_score) === candidateThreshold
  );
  const selectedVerdict = String(candidateRow?.verdict ?? "insufficient");

  const chartRows = selectedRows.map((row) => {
    const low = asNumber(row.confidence_interval_low_pct);
    const high = asNumber(row.confidence_interval_high_pct);
    return {
      ...row,
      threshold: asNumber(row.min_score),
      expectancy: asNumber(row.oos_net_expectancy_pct),
      interval: low === null || high === null ? undefined : [low, high],
      intervalLabel:
        low === null || high === null
          ? "Unavailable"
          : `${formatPct(low, 2)} to ${formatPct(high, 2)}`
    };
  });
  const sensitivityTableRows = chartRows.map((row) => ({
    ...row,
    interval: row.intervalLabel
  }));

  const reliabilityRows = pickArray(reliability.rows)
    .filter((row) => row.strategy_family === strategy)
    .map((row) => {
      const low = asNumber(row.confidence_interval_low_pct);
      const high = asNumber(row.confidence_interval_high_pct);
      return {
        ...row,
        interval:
          low === null || high === null
            ? "Unavailable"
            : `${formatPct(low, 1)} to ${formatPct(high, 1)}`
      };
    });
  const reliabilityDiagnostic = pickArray(reliability.diagnostics).find(
    (row) => row.strategy_family === strategy
  );
  const warnings = Array.isArray(dataQuality.warnings)
    ? dataQuality.warnings.map(String)
    : [];
  const sourceCounts = pickRecord(dataQuality.source_quality_counts);

  if (!research.status) return null;

  return (
    <div className="space-y-5">
      <div
        role="note"
        className="border-l-2 border-[var(--amber)] bg-[var(--amber-soft)] px-4 py-3 text-sm leading-6 text-[var(--muted)]"
      >
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge tone="warning">Research only</StatusBadge>
          <strong className="text-[var(--text)]">No production setting is changed here.</strong>
        </div>
        <p className="mt-2">
          {String(
            deploymentGuard.message ??
              "Candidates are for shadow validation and do not update live thresholds."
          )}
        </p>
      </div>

      <TerminalPanel
        title="Threshold research"
        eyebrow="Current versus shadow candidate"
        action={
          <StatusBadge tone={verdictTone(selectedVerdict)}>
            {sentenceCase(selectedVerdict)}
          </StatusBadge>
        }
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <label className="text-xs font-medium text-[var(--muted)]">
            Strategy
            <select
              data-testid="calibration-strategy"
              className="field mt-1"
              value={strategy}
              onChange={(event) => setStrategy(event.target.value)}
            >
              {strategyOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-[var(--muted)]">
            Regime
            <select
              data-testid="calibration-regime"
              className="field mt-1"
              value={regime}
              onChange={(event) => setRegime(event.target.value)}
            >
              {regimeOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-[var(--muted)]">
            Round-trip cost
            <select
              data-testid="calibration-cost"
              className="field mt-1"
              value={costBps}
              onChange={(event) => setCostBps(Number(event.target.value))}
            >
              {costs.map((cost) => (
                <option key={cost} value={cost}>
                  {cost} bps
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-[var(--muted)]">
            Shadow score floor
            <select
              data-testid="calibration-shadow-threshold"
              className="field mt-1"
              value={candidateThreshold}
              onChange={(event) => setCandidateThreshold(Number(event.target.value))}
            >
              {thresholds.map((threshold) => (
                <option key={threshold} value={threshold}>
                  {threshold}
                  {threshold === suggestedThreshold ? " · suggested" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mt-5">
          <DataTable
            rows={[
              comparisonRow("Current production", currentRow ?? {}),
              comparisonRow("Shadow candidate", candidateRow ?? {})
            ]}
            columns={comparisonColumns}
            emptyLabel="No current-versus-candidate comparison is available."
          />
        </div>

        <div className="mt-4 border-t border-[var(--line-soft)] pt-4 text-sm text-[var(--muted)]">
          <p className="font-medium text-[var(--text)]">How to read this candidate</p>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {candidateRow?.evidence_level === "insufficient" ? (
              <li>There is not enough time-diverse evidence to support promotion.</li>
            ) : null}
            <li>
              A positive expectancy is not enough by itself; fold consistency, adjacent
              thresholds, and the clustered interval also affect the verdict.
            </li>
            <li>
              “Strong shadow candidate” means keep observing it out of sample. It does
              not mean deploy.
            </li>
          </ul>
        </div>
      </TerminalPanel>

      <TerminalPanel
        title="Score-floor sensitivity"
        eyebrow={`${costBps} bps costs · embargoed validation`}
      >
        <ChartLegend
          items={[
            { label: "OOS net expectancy", color: "var(--chart-positive)" },
            { label: "80% clustered interval", color: "var(--chart-accent)" },
            { label: "Current threshold", color: "var(--chart-warning)", dashed: true }
          ]}
          summary="The interval resamples signal dates and then tickers, so same-day observations are not treated as fully independent."
        />
        <div
          className="h-80"
          role="img"
          aria-label="Out-of-sample net expectancy by score floor with an 80 percent clustered uncertainty interval"
        >
          <ResponsiveContainer
            width="100%"
            height="100%"
            minWidth={1}
            minHeight={1}
            initialDimension={{ width: 1, height: 1 }}
          >
            <ComposedChart data={chartRows}>
              <CartesianGrid stroke="var(--line-soft)" vertical={false} />
              <XAxis
                dataKey="threshold"
                stroke="var(--dim)"
                fontSize={11}
                label={{
                  value: "Minimum score",
                  position: "insideBottom",
                  offset: -2,
                  fill: "var(--dim)"
                }}
              />
              <YAxis
                stroke="var(--dim)"
                fontSize={11}
                label={{
                  value: "Net expectancy %",
                  angle: -90,
                  position: "insideLeft",
                  fill: "var(--dim)"
                }}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--line)",
                  color: "var(--text)"
                }}
              />
              <Area
                dataKey="interval"
                name="80% clustered interval"
                stroke="none"
                fill="var(--chart-accent)"
                fillOpacity={0.18}
                isAnimationActive={false}
              />
              <Line
                dataKey="expectancy"
                name="OOS net expectancy %"
                type="monotone"
                stroke="var(--chart-positive)"
                strokeWidth={2}
                dot={{ r: 3 }}
                isAnimationActive={false}
              />
              <ReferenceLine
                x={currentThreshold}
                stroke="var(--chart-warning)"
                strokeDasharray="5 4"
                label={{
                  value: `Current ${currentThreshold}`,
                  fill: "var(--chart-warning)",
                  fontSize: 11
                }}
              />
              <ReferenceLine y={0} stroke="var(--line-strong)" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-4">
          <DataTable
            rows={sensitivityTableRows}
            columns={sensitivityColumns}
            emptyLabel="No sensitivity rows are available for this segment."
          />
        </div>
      </TerminalPanel>

      <div className="grid gap-5 xl:grid-cols-2">
        <TerminalPanel title="Data quality" eyebrow="Independence and coverage">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <div>
              <dt className="text-[var(--dim)]">Resolved signals</dt>
              <dd className="mt-1 font-semibold text-[var(--text)]">
                {String(dataQuality.resolved_signals ?? 0)}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--dim)]">Distinct tickers</dt>
              <dd className="mt-1 font-semibold text-[var(--text)]">
                {String(dataQuality.distinct_tickers ?? 0)}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--dim)]">Distinct signal dates</dt>
              <dd className="mt-1 font-semibold text-[var(--text)]">
                {String(dataQuality.distinct_signal_dates ?? 0)}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--dim)]">Largest date cluster</dt>
              <dd className="mt-1 font-semibold text-[var(--text)]">
                {String(dataQuality.largest_signal_date_cluster ?? 0)} ·{" "}
                {formatPct(dataQuality.largest_signal_date_share_pct, 1)}
              </dd>
            </div>
            <div className="col-span-2">
              <dt className="text-[var(--dim)]">Signal period</dt>
              <dd className="mt-1 font-semibold text-[var(--text)]">
                {String(dataQuality.period_start ?? "N/A")} to{" "}
                {String(dataQuality.period_end ?? "N/A")}
              </dd>
            </div>
            <div className="col-span-2">
              <dt className="text-[var(--dim)]">Source quality</dt>
              <dd className="mt-1 font-semibold text-[var(--text)]">
                {Object.entries(sourceCounts)
                  .map(([label, count]) => `${sentenceCase(label)} ${String(count)}`)
                  .join(" · ") || "N/A"}
              </dd>
            </div>
          </dl>
          {warnings.length ? (
            <div className="mt-4 border-t border-[var(--line-soft)] pt-4">
              <p className="text-xs font-medium uppercase tracking-wide text-[var(--amber)]">
                Evidence warnings
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-[var(--muted)]">
                {warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </TerminalPanel>

        <TerminalPanel title="Walk-forward folds" eyebrow="15-day calendar embargo">
          <p className="mb-3 text-sm leading-6 text-[var(--muted)]">
            Training ends 15 calendar days before validation begins. Only eligible
            validation windows feed the out-of-sample curve.
          </p>
          <DataTable
            rows={folds}
            columns={foldColumns}
            emptyLabel="There is not enough time history to construct walk-forward folds."
          />
        </TerminalPanel>
      </div>

      <TerminalPanel
        title="Confidence reliability"
        eyebrow="Ordinal labels · 10 bps success reference"
        action={
          reliabilityDiagnostic ? (
            <StatusBadge
              tone={
                reliabilityDiagnostic.status === "aligned"
                  ? "positive"
                  : reliabilityDiagnostic.status === "not_aligned"
                    ? "warning"
                    : "neutral"
              }
            >
              {sentenceCase(String(reliabilityDiagnostic.status))}
            </StatusBadge>
          ) : null
        }
      >
        <div role="note" className="mb-4 text-sm leading-6 text-[var(--muted)]">
          {String(reliability.reason ?? "")}{" "}
          {String(reliability.research_reference ?? "")}
        </div>
        <DataTable
          rows={reliabilityRows}
          columns={reliabilityColumns}
          emptyLabel="No confidence-reliability rows are available for this strategy."
        />
      </TerminalPanel>
    </div>
  );
}
