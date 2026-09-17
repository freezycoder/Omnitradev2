"use client";

import { FormEvent, useState } from "react";
import { DataTable, DataTableColumn, etfHref } from "@/components/DataTable";
import { EtfTabs } from "@/components/EtfTabs";
import { LoadingState } from "@/components/LoadingState";
import { MetricCard } from "@/components/MetricCard";
import { SectionHeader } from "@/components/SectionHeader";
import { TerminalPanel } from "@/components/TerminalPanel";
import { fetchEtfCompare } from "@/lib/api";
import { formatAvailable, formatLargeNumber, formatPct, formatSignedPct, pickArray, pickRecord } from "@/lib/format";

type Row = Record<string, unknown>;

const snapshotColumns: DataTableColumn<Row>[] = [
  { key: "ticker", header: "Ticker", render: (row) => <a className="font-semibold text-white" href={etfHref(String(row.ticker ?? ""))}>{String(row.ticker ?? "")}</a> },
  { key: "name", header: "Name", render: (row) => String(row.name ?? "Data unavailable") },
  { key: "expense_ratio", header: "Expense", align: "right", render: (row) => formatAvailable(row.expense_ratio, (value) => formatPct(value > 1 ? value : value * 100, 2)) },
  { key: "aum", header: "AUM", align: "right", render: (row) => formatAvailable(row.aum, (value) => formatLargeNumber(value)) },
  { key: "return_1y", header: "1Y", align: "right", render: (row) => formatAvailable(row.return_1y, (value) => formatSignedPct(value, 2)) },
  { key: "volatility", header: "Vol", align: "right", render: (row) => formatAvailable(row.volatility, (value) => formatPct(value, 1)) },
  { key: "drawdown", header: "Drawdown", align: "right", render: (row) => formatAvailable(row.drawdown, (value) => formatPct(value, 1)) },
  { key: "omni", header: "OmniScore", align: "right", render: (row) => formatAvailable(row.omni, (value) => value.toFixed(1)) }
];

export function EtfComparePage() {
  const [symbols, setSymbols] = useState("QQQ,SPY");
  const [data, setData] = useState<Row | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    const tickers = symbols.split(",").map((item) => item.trim().toUpperCase()).filter(Boolean);
    setLoading(true);
    setError(null);
    fetchEtfCompare(tickers)
      .then((payload) => setData(payload))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }

  const etfs = pickArray(data?.etfs);
  const pairs = pickArray(data?.pairs);

  return (
    <div className="space-y-6">
      <SectionHeader title="ETF comparison" badge="Holdings overlap" />
      <EtfTabs activeHref="/etf/compare" />
      <TerminalPanel title="Select ETFs" eyebrow="No winner score is produced">
        <form className="flex flex-wrap gap-3" onSubmit={submit}>
          <input
            className="min-w-64 flex-1 border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]"
            value={symbols}
            onChange={(event) => setSymbols(event.target.value)}
            placeholder="QQQ, SPY, XLK"
          />
          <button type="submit" className="button" disabled={loading}>
            Compare
          </button>
        </form>
        {error ? <p className="mt-3 text-sm text-[var(--red)]">{error}</p> : null}
      </TerminalPanel>
      {loading ? <LoadingState title="Comparison" message="Calculating overlap from cached holdings" /> : null}
      {etfs.length ? (
        <TerminalPanel title="Fund snapshot">
          <DataTable<Row>
            rows={etfs.map((row): Row => {
              const profile = pickRecord(row.profile);
              const metrics = pickRecord(row.metrics);
              return {
                ticker: profile.ticker,
                name: profile.name,
                expense_ratio: profile.expense_ratio,
                aum: profile.aum,
                asset_type: "ETF",
                omni: pickRecord(row.omni_score).score,
                return_1y: metrics.return_1y,
                volatility: metrics.annualized_volatility,
                drawdown: metrics.maximum_drawdown
              };
            })}
            columns={snapshotColumns}
            emptyLabel="Data unavailable"
          />
        </TerminalPanel>
      ) : null}
      {pairs.map((pair) => {
        const overlap = pair.overlap_pct;
        return (
          <TerminalPanel key={`${String(pair.ticker_a)}-${String(pair.ticker_b)}`} title={`${String(pair.ticker_a)} vs ${String(pair.ticker_b)}`}>
            <div className="mb-4 grid gap-3 sm:grid-cols-3">
              <MetricCard label="Holdings overlap" value={formatAvailable(overlap, (value) => formatPct(value, 2))} meta="sum of min weights" />
              <MetricCard label="Correlation" value={formatAvailable(pair.correlation, (value) => value.toFixed(2))} meta="Insufficient history stays blank" />
              <MetricCard label="Top-10 A / B" value={`${formatAvailable(pair.top_10_concentration_a, (value) => formatPct(value * 100, 1))} / ${formatAvailable(pair.top_10_concentration_b, (value) => formatPct(value * 100, 1))}`} />
            </div>
            <DataTable
              rows={pickArray(pair.shared_holdings)}
              columns={[
                { key: "ticker", header: "Shared holding" },
                { key: "name", header: "Name" },
                { key: "weight_a", header: "Weight A", align: "right", render: (row) => formatAvailable(row.weight_a, (value) => formatPct(value * 100, 2)) },
                { key: "weight_b", header: "Weight B", align: "right", render: (row) => formatAvailable(row.weight_b, (value) => formatPct(value * 100, 2)) },
                { key: "overlap_weight", header: "Min weight", align: "right", render: (row) => formatAvailable(row.overlap_weight, (value) => formatPct(value * 100, 2)) }
              ]}
              emptyLabel="Shared holdings unavailable."
            />
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <DataTable
                rows={pickArray(pair.unique_holdings_a)}
                columns={[
                  { key: "ticker", header: `Unique ${String(pair.ticker_a)}` },
                  { key: "name", header: "Name" },
                  { key: "weight_a", header: "Weight", align: "right", render: (row) => formatAvailable(row.weight_a, (value) => formatPct(value * 100, 2)) }
                ]}
                emptyLabel={`No unique holdings for ${String(pair.ticker_a)}.`}
              />
              <DataTable
                rows={pickArray(pair.unique_holdings_b)}
                columns={[
                  { key: "ticker", header: `Unique ${String(pair.ticker_b)}` },
                  { key: "name", header: "Name" },
                  { key: "weight_b", header: "Weight", align: "right", render: (row) => formatAvailable(row.weight_b, (value) => formatPct(value * 100, 2)) }
                ]}
                emptyLabel={`No unique holdings for ${String(pair.ticker_b)}.`}
              />
            </div>
            <div className="mt-4 grid gap-4 xl:grid-cols-2">
              <DataTable
                rows={pickArray(pair.sector_exposure)}
                columns={[
                  { key: "label", header: "Sector" },
                  { key: "weight_a", header: String(pair.ticker_a), align: "right", render: (row) => formatAvailable(row.weight_a, (value) => formatPct(value > 1 ? value : value * 100, 1)) },
                  { key: "weight_b", header: String(pair.ticker_b), align: "right", render: (row) => formatAvailable(row.weight_b, (value) => formatPct(value > 1 ? value : value * 100, 1)) }
                ]}
                emptyLabel="Sector comparison unavailable."
              />
              <DataTable
                rows={pickArray(pair.geographic_exposure)}
                columns={[
                  { key: "label", header: "Geography" },
                  { key: "weight_a", header: String(pair.ticker_a), align: "right", render: (row) => formatAvailable(row.weight_a, (value) => formatPct(value > 1 ? value : value * 100, 1)) },
                  { key: "weight_b", header: String(pair.ticker_b), align: "right", render: (row) => formatAvailable(row.weight_b, (value) => formatPct(value > 1 ? value : value * 100, 1)) }
                ]}
                emptyLabel="Geographic comparison unavailable."
              />
            </div>
          </TerminalPanel>
        );
      })}
    </div>
  );
}
