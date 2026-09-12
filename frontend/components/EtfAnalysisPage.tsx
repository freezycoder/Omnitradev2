"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartLegend } from "@/components/ChartLegend";
import { DataTable, DataTableColumn, tickerHref } from "@/components/DataTable";
import { EtfTabs } from "@/components/EtfTabs";
import { LoadingState } from "@/components/LoadingState";
import { MetricCard } from "@/components/MetricCard";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import { fetchEtfAnalysis } from "@/lib/api";
import { asNumber, formatAvailable, formatCurrency, formatLargeNumber, formatPct, formatSignedPct, pickArray, pickRecord } from "@/lib/format";

type Row = Record<string, unknown>;

function unavailable(value: unknown) {
  return value === null || value === undefined || value === "" ? "Data unavailable" : String(value);
}

function metricLabel(insufficient: Set<string>, keys: string[], value: unknown, formatter: (input: number) => string) {
  if (keys.some((key) => insufficient.has(key))) return "Insufficient data";
  return formatAvailable(value, formatter);
}

function chartDateLabel(value: unknown) {
  const parsed = Date.parse(String(value ?? ""));
  if (!Number.isFinite(parsed)) return String(value ?? "");
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(new Date(parsed));
}

const holdingColumns: DataTableColumn<Row>[] = [
  {
    key: "holding_ticker",
    header: "Ticker",
    render: (row) => {
      const ticker = String(row.holding_ticker ?? "").trim();
      return ticker ? (
        <a href={tickerHref(ticker)} className="font-semibold text-white underline-offset-4 hover:underline">
          {ticker}
        </a>
      ) : (
        "Data unavailable"
      );
    }
  },
  { key: "holding_name", header: "Company", render: (row) => unavailable(row.holding_name) },
  { key: "weight", header: "Weight", align: "right", render: (row) => formatAvailable(row.weight, (value) => formatPct(value * 100, 2)) }
];

export function EtfAnalysisPage() {
  const params = useParams<{ symbol: string }>();
  const ticker = String(params.symbol ?? "").toUpperCase();
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetchEtfAnalysis(ticker)
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
  }, [ticker]);

  const profile = pickRecord(data?.profile);
  const metrics = pickRecord(data?.metrics);
  const risk = pickRecord(data?.risk);
  const omni = pickRecord(data?.omni_score);
  const components = pickArray(omni.components);
  const holdings = pickRecord(data?.holdings);
  const topHoldings = pickArray(data?.top_holdings);
  const sectorAllocation = pickArray(holdings.sector_allocation).length
    ? pickArray(holdings.sector_allocation)
    : pickArray(profile.sector_exposure);
  const geographicAllocation = pickArray(holdings.geographic_allocation).length
    ? pickArray(holdings.geographic_allocation)
    : pickArray(profile.geographic_exposure);
  const insufficient = new Set(
    Array.isArray(risk.insufficient_data) ? risk.insufficient_data.map((item) => String(item)) : []
  );
  const flows = pickRecord(data?.flows);
  const underlying = pickRecord(data?.underlying_signal_exposure);
  const chartRows = useMemo(
    () =>
      pickArray(data?.enriched_history).map((row) => ({
        date: chartDateLabel(row.Date),
        close: asNumber(row.Close),
        ma50: asNumber(row.MA50),
        ma200: asNumber(row.MA200)
      })),
    [data]
  );

  if (loading) return <LoadingState title="ETF analysis" message={`Loading ${ticker}`} />;
  if (error || !data) {
    return (
      <div className="space-y-6">
        <SectionHeader title={ticker} badge="ETF" />
        <TerminalPanel title="Unavailable">
          <p className="text-sm text-[var(--muted)]">{error ?? "Data unavailable"}</p>
        </TerminalPanel>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SectionHeader title={String(profile.name ?? ticker)} badge={ticker} />
      <EtfTabs activeHref="/etf" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Price" value={formatAvailable(metrics.current_price, (value) => formatCurrency(value))} meta={unavailable(profile.issuer)} />
        <MetricCard label="Daily change" value={formatAvailable(metrics.daily_change_pct, (value) => formatSignedPct(value, 2))} tone={(asNumber(metrics.daily_change_pct) ?? 0) >= 0 ? "positive" : "negative"} />
        <MetricCard label="AUM" value={formatAvailable(profile.aum, (value) => formatLargeNumber(value))} meta={unavailable(profile.category)} />
        <MetricCard label="Expense ratio" value={formatAvailable(profile.expense_ratio, (value) => formatPct(value > 1 ? value : value * 100, 2))} />
        <MetricCard label="Dividend yield" value={formatAvailable(profile.dividend_yield, (value) => formatPct(value > 1 ? value : value * 100, 2))} />
        <MetricCard label="Holdings" value={unavailable(holdings.holdings_count ?? profile.holdings_count)} />
        <MetricCard label="OmniScore" value={formatAvailable(omni.score, (value) => value.toFixed(1))} meta="Not a validated forecast" tone="info" />
        <MetricCard label="Issuer" value={unavailable(profile.issuer)} />
      </div>

      <TerminalPanel title="Performance" eyebrow="Price history from the market provider">
        {chartRows.length ? (
          <>
            <ChartLegend
              items={[
                { label: "Close", color: "var(--accent)" },
                { label: "SMA50", color: "var(--chart-positive)" },
                { label: "SMA200", color: "var(--chart-secondary)", dashed: true }
              ]}
              summary="Returns are omitted when the history window is too short."
            />
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={chartRows}>
                  <CartesianGrid stroke="var(--line-soft)" />
                  <XAxis dataKey="date" tick={{ fill: "var(--dim)", fontSize: 11 }} />
                  <YAxis tick={{ fill: "var(--dim)", fontSize: 11 }} />
                  <Tooltip />
                  <Area type="monotone" dataKey="close" stroke="var(--accent)" fill="var(--accent-soft)" />
                  <Line type="monotone" dataKey="ma50" stroke="var(--chart-positive)" dot={false} />
                  <Line type="monotone" dataKey="ma200" stroke="var(--chart-secondary)" dot={false} strokeDasharray="4 4" />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </>
        ) : (
          <p className="text-sm text-[var(--muted)]">Data unavailable</p>
        )}
        <div className="mt-4 grid gap-3 sm:grid-cols-3 xl:grid-cols-5">
          {[
            ["1D", metrics.return_1d, "1D"],
            ["1W", metrics.return_1w, "1W"],
            ["1M", metrics.return_1m, "1M"],
            ["3M", metrics.return_3m, "3M"],
            ["6M", metrics.return_6m, "6M"],
            ["YTD", metrics.return_ytd, "YTD"],
            ["1Y", metrics.return_1y, "1Y"],
            ["3Y", metrics.return_3y, "3Y"],
            ["5Y", metrics.return_5y, "5Y"]
          ].map(([label, value, key]) => (
            <MetricCard key={String(label)} label={String(label)} value={metricLabel(insufficient, [String(key)], value, (item) => formatSignedPct(item, 2))} />
          ))}
        </div>
      </TerminalPanel>

      <TerminalPanel title="Risk" eyebrow="Insufficient windows are labeled explicitly">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Volatility" value={metricLabel(insufficient, ["volatility"], risk.annualized_volatility, (value) => formatPct(value, 1))} />
          <MetricCard label="Max drawdown" value={metricLabel(insufficient, ["drawdown"], risk.maximum_drawdown, (value) => formatPct(value, 1))} />
          <MetricCard label="Sharpe" value={metricLabel(insufficient, ["sharpe"], risk.sharpe_ratio, (value) => value.toFixed(2))} />
          <MetricCard label="Downside vol" value={metricLabel(insufficient, ["downside_volatility"], risk.downside_volatility, (value) => formatPct(value, 1))} />
        </div>
      </TerminalPanel>

      <TerminalPanel title="Holdings look-through" eyebrow={holdings.source ? String(holdings.source) : "Cached holdings"}>
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <MetricCard label="Top 5 concentration" value={formatAvailable(holdings.top_5_concentration, (value) => formatPct(value * 100, 1))} />
          <MetricCard label="Top 10 concentration" value={formatAvailable(holdings.top_10_concentration, (value) => formatPct(value * 100, 1))} />
          <MetricCard label="Holdings count" value={unavailable(holdings.holdings_count)} />
        </div>
        <DataTable rows={topHoldings} columns={holdingColumns} emptyLabel="Holdings data unavailable from the configured providers." />
        <div className="mt-4 grid gap-4 xl:grid-cols-2">
          <DataTable
            rows={sectorAllocation}
            columns={[
              { key: "label", header: "Sector" },
              { key: "weight", header: "Weight", align: "right", render: (row) => formatAvailable(row.weight, (value) => formatPct(value > 1 ? value : value * 100, 1)) }
            ]}
            emptyLabel="Sector allocation unavailable."
          />
          <DataTable
            rows={geographicAllocation}
            columns={[
              { key: "label", header: "Geography" },
              { key: "weight", header: "Weight", align: "right", render: (row) => formatAvailable(row.weight, (value) => formatPct(value > 1 ? value : value * 100, 1)) }
            ]}
            emptyLabel="Geographic allocation unavailable."
          />
        </div>
      </TerminalPanel>

      <TerminalPanel title="OmniScore components" eyebrow="Missing components are excluded, not scored as zero">
        <DataTable
          rows={components}
          columns={[
            { key: "label", header: "Component" },
            { key: "score", header: "Score", align: "right", render: (row) => formatAvailable(row.score, (value) => value.toFixed(1)) },
            { key: "applied_weight", header: "Applied weight", align: "right", render: (row) => formatAvailable(row.applied_weight, (value) => formatPct(value * 100, 1)) },
            { key: "summary", header: "Notes", render: (row) => String(row.summary ?? "Data unavailable") }
          ]}
          emptyLabel="OmniScore components are unavailable."
        />
      </TerminalPanel>

      <TerminalPanel title="Underlying signal exposure" eyebrow="Stock signal strength × holding weight">
        {underlying.available ? (
          <DataTable
            rows={pickArray(underlying.contributing_holdings)}
            columns={[
              { key: "ticker", header: "Holding" },
              { key: "weight", header: "Weight", align: "right", render: (row) => formatAvailable(row.weight, (value) => formatPct(value * 100, 2)) },
              { key: "signal_score", header: "Stock signal", align: "right", render: (row) => formatAvailable(row.signal_score, (value) => value.toFixed(1)) },
              { key: "contribution", header: "Contribution", align: "right", render: (row) => formatAvailable(row.contribution, (value) => value.toFixed(2)) }
            ]}
            emptyLabel="No contributing stock signals are cached."
          />
        ) : (
          <p className="text-sm text-[var(--muted)]">Data unavailable until stock scans and ETF holdings overlap.</p>
        )}
      </TerminalPanel>

      <TerminalPanel title="Flows">
        <StatusBadge tone={flows.available ? "positive" : "warning"}>{flows.available ? "Available" : "Unavailable"}</StatusBadge>
        <p className="mt-3 text-sm text-[var(--muted)]">{String(flows.unavailable_reason ?? "Data unavailable")}</p>
      </TerminalPanel>
    </div>
  );
}
