"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { DataTable, DataTableColumn, etfHref } from "@/components/DataTable";
import { EtfTabs } from "@/components/EtfTabs";
import { LoadingState } from "@/components/LoadingState";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import { EtfScreenerPayload, fetchEtfScreener, fetchEtfUnderlyingSignals } from "@/lib/api";
import { asNumber, formatAvailable, formatLargeNumber, formatPct, formatSignedPct, pickArray } from "@/lib/format";

type Row = Record<string, unknown>;

const columns: DataTableColumn<Row>[] = [
  {
    key: "ticker",
    header: "Ticker",
    render: (row) => (
      <a href={etfHref(String(row.ticker ?? ""))} className="font-semibold text-white underline-offset-4 hover:text-[var(--accent-strong)] hover:underline">
        {String(row.ticker ?? "Data unavailable")}
      </a>
    )
  },
  { key: "name", header: "Name", render: (row) => String(row.name ?? "Data unavailable") },
  { key: "category", header: "Category", render: (row) => String(row.category ?? "Data unavailable") },
  { key: "geography", header: "Geography", render: (row) => String(row.geography ?? "Data unavailable") },
  { key: "price", header: "Price", align: "right", render: (row) => formatAvailable(row.price, (value) => value.toFixed(2)) },
  { key: "return_1d", header: "1D %", align: "right", render: (row) => formatAvailable(row.return_1d, (value) => formatSignedPct(value, 2)) },
  { key: "return_1w", header: "1W %", align: "right", render: (row) => formatAvailable(row.return_1w, (value) => formatSignedPct(value, 2)) },
  { key: "return_1m", header: "1M %", align: "right", render: (row) => formatAvailable(row.return_1m, (value) => formatSignedPct(value, 2)) },
  { key: "return_3m", header: "3M %", align: "right", render: (row) => formatAvailable(row.return_3m, (value) => formatSignedPct(value, 2)) },
  { key: "return_ytd", header: "YTD %", align: "right", render: (row) => formatAvailable(row.return_ytd, (value) => formatSignedPct(value, 2)) },
  { key: "return_1y", header: "1Y %", align: "right", render: (row) => formatAvailable(row.return_1y, (value) => formatSignedPct(value, 2)) },
  { key: "volatility", header: "Volatility", align: "right", render: (row) => formatAvailable(row.volatility, (value) => formatPct(value, 1)) },
  { key: "drawdown", header: "Drawdown", align: "right", render: (row) => formatAvailable(row.drawdown, (value) => formatPct(value, 1)) },
  { key: "aum", header: "AUM", align: "right", render: (row) => formatAvailable(row.aum, (value) => formatLargeNumber(value)) },
  { key: "expense_ratio", header: "Expense Ratio", align: "right", render: (row) => formatAvailable(row.expense_ratio, (value) => formatPct(value > 1 ? value : value * 100, 2)) },
  { key: "dividend_yield", header: "Dividend Yield", align: "right", render: (row) => formatAvailable(row.dividend_yield, (value) => formatPct(value > 1 ? value : value * 100, 2)) },
  { key: "omni_score", header: "OmniScore", align: "right", render: (row) => formatAvailable(row.omni_score, (value) => value.toFixed(1)) }
];

export function EtfScreenerPage() {
  const [data, setData] = useState<EtfScreenerPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [query, setQuery] = useState("");
  const [issuer, setIssuer] = useState("");
  const [category, setCategory] = useState("");
  const [assetClass, setAssetClass] = useState("");
  const [sector, setSector] = useState("");
  const [geography, setGeography] = useState("");
  const [maxExpense, setMaxExpense] = useState("");
  const [minAum, setMinAum] = useState("");
  const [minVolume, setMinVolume] = useState("");
  const [minYield, setMinYield] = useState("");
  const [underlying, setUnderlying] = useState<Row[]>([]);

  function load(refresh = false) {
    setError(null);
    const request = refresh ? setRefreshing : setLoading;
    request(true);
    fetchEtfScreener({}, refresh)
      .then((payload) => setData(payload))
      .catch((err: Error) => setError(err.message))
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  }

  useEffect(() => {
    load(false);
    fetchEtfUnderlyingSignals()
      .then((payload) => setUnderlying(pickArray(payload.etfs)))
      .catch(() => setUnderlying([]));
  }, []);

  const rows = useMemo(() => {
    const maxExpenseValue = asNumber(maxExpense);
    const minAumValue = asNumber(minAum);
    const minVolumeValue = asNumber(minVolume);
    const minYieldValue = asNumber(minYield);
    return pickArray(data?.rows).filter((row) => {
      const haystack = `${String(row.ticker ?? "")} ${String(row.name ?? "")}`.toLowerCase();
      if (query && !haystack.includes(query.toLowerCase())) return false;
      if (issuer && !String(row.issuer ?? "").toLowerCase().includes(issuer.toLowerCase())) return false;
      if (category && !String(row.category ?? "").toLowerCase().includes(category.toLowerCase())) return false;
      if (assetClass && !String(row.asset_class ?? "").toLowerCase().includes(assetClass.toLowerCase())) return false;
      if (sector && !String(row.sector ?? "").toLowerCase().includes(sector.toLowerCase())) return false;
      if (geography && !String(row.geography ?? "").toLowerCase().includes(geography.toLowerCase())) return false;
      const expense = asNumber(row.expense_ratio);
      const aum = asNumber(row.aum);
      const volume = asNumber(row.average_volume);
      const dividend = asNumber(row.dividend_yield);
      if (maxExpenseValue !== null && (expense === null || (expense > 1 ? expense : expense * 100) > maxExpenseValue)) return false;
      if (minAumValue !== null && (aum === null || aum < minAumValue)) return false;
      if (minVolumeValue !== null && (volume === null || volume < minVolumeValue)) return false;
      if (minYieldValue !== null && (dividend === null || (dividend > 1 ? dividend : dividend * 100) < minYieldValue)) return false;
      return true;
    });
  }, [data, query, issuer, category, assetClass, sector, geography, maxExpense, minAum, minVolume, minYield]);

  function onFilter(event: FormEvent) {
    event.preventDefault();
  }

  if (loading) {
    return <LoadingState title="ETF screener" message="Loading cached ETF universe" />;
  }

  return (
    <div className="space-y-6">
      <SectionHeader title="ETF screener" badge={data?.universe_name ?? "ETF research"} />
      <EtfTabs activeHref="/etf" />
      <TerminalPanel
        title="Universe"
        eyebrow={data?.note ?? "Research composite, not a forecast"}
        action={
          <button type="button" className="button" onClick={() => load(true)} disabled={refreshing}>
            {refreshing ? "Refreshing" : "Refresh cache"}
          </button>
        }
      >
        <form className="mb-4 grid gap-3 md:grid-cols-3 xl:grid-cols-5" onSubmit={onFilter}>
          <label className="text-xs text-[var(--muted)]">
            Ticker / name
            <input className="mt-1 w-full border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]" value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <label className="text-xs text-[var(--muted)]">
            Issuer
            <input className="mt-1 w-full border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]" value={issuer} onChange={(event) => setIssuer(event.target.value)} />
          </label>
          <label className="text-xs text-[var(--muted)]">
            Category
            <input className="mt-1 w-full border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]" value={category} onChange={(event) => setCategory(event.target.value)} />
          </label>
          <label className="text-xs text-[var(--muted)]">
            Asset class
            <input className="mt-1 w-full border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]" value={assetClass} onChange={(event) => setAssetClass(event.target.value)} />
          </label>
          <label className="text-xs text-[var(--muted)]">
            Sector
            <input className="mt-1 w-full border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]" value={sector} onChange={(event) => setSector(event.target.value)} />
          </label>
          <label className="text-xs text-[var(--muted)]">
            Geography
            <input className="mt-1 w-full border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]" value={geography} onChange={(event) => setGeography(event.target.value)} />
          </label>
          <label className="text-xs text-[var(--muted)]">
            Max expense ratio
            <input className="mt-1 w-full border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]" value={maxExpense} onChange={(event) => setMaxExpense(event.target.value)} placeholder="0.20" />
          </label>
          <label className="text-xs text-[var(--muted)]">
            Min AUM
            <input className="mt-1 w-full border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]" value={minAum} onChange={(event) => setMinAum(event.target.value)} placeholder="1000000000" />
          </label>
          <label className="text-xs text-[var(--muted)]">
            Min volume
            <input className="mt-1 w-full border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]" value={minVolume} onChange={(event) => setMinVolume(event.target.value)} />
          </label>
          <label className="text-xs text-[var(--muted)]">
            Min dividend yield
            <input className="mt-1 w-full border border-[var(--line)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--text)]" value={minYield} onChange={(event) => setMinYield(event.target.value)} placeholder="1.5" />
          </label>
        </form>
        {error ? <p className="mb-3 text-sm text-[var(--red)]">{error}</p> : null}
        <DataTable
          rows={rows}
          columns={columns}
          emptyLabel={
            pickArray(data?.rows).length > 0
              ? "No ETF rows match these filters. Geography is often blank until holdings exposure is cached — clear Geography or refresh the universe."
              : "No ETF rows are cached yet. Refresh the universe to pull provider data."
          }
        />
      </TerminalPanel>
      <TerminalPanel title="Underlying signal exposure" eyebrow="Stock thesis expressed through ETF holdings">
        <DataTable
          rows={underlying}
          columns={[
            { key: "etf_ticker", header: "ETF", render: (row) => <a className="font-semibold text-white" href={etfHref(String(row.etf_ticker ?? ""))}>{String(row.etf_ticker ?? "Data unavailable")}</a> },
            { key: "etf_name", header: "Name", render: (row) => String(row.etf_name ?? "Data unavailable") },
            { key: "exposure_score", header: "Exposure", align: "right", render: (row) => formatAvailable(row.exposure_score, (value) => value.toFixed(1)) },
            { key: "coverage_weight", header: "Coverage", align: "right", render: (row) => formatAvailable(row.coverage_weight, (value) => formatPct(value * 100, 1)) }
          ]}
          emptyLabel="Underlying exposure appears after stock scans and ETF holdings are cached."
        />
      </TerminalPanel>
    </div>
  );
}
