"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { DataTable, DataTableColumn } from "@/components/DataTable";
import { LoadingState } from "@/components/LoadingState";
import { MetricCard } from "@/components/MetricCard";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import {
  addWatchlistItem,
  ApiCapabilities,
  fetchApiCapabilities,
  fetchOverview,
  fetchWatchlist,
  READ_ONLY_API_CAPABILITIES,
  removeWatchlistItem,
  ScanPayload,
  WatchlistItem
} from "@/lib/api";
import { formatPct, pickArray, pickRecord } from "@/lib/format";

type Row = Record<string, unknown>;

export function WatchlistPage() {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [scan, setScan] = useState<ScanPayload | null>(null);
  const [tickerInput, setTickerInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [capabilities, setCapabilities] = useState<ApiCapabilities>(READ_ONLY_API_CAPABILITIES);

  function load() {
    setLoading(true);
    setError(null);
    Promise.all([
      fetchWatchlist(),
      fetchOverview({ universe: "global", dataMode: "auto", refresh: false }),
      fetchApiCapabilities().catch(() => READ_ONLY_API_CAPABILITIES)
    ])
      .then(([watchlistPayload, scanPayload, capabilityPayload]) => {
        setWatchlist(watchlistPayload);
        setScan(scanPayload);
        setCapabilities(capabilityPayload);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  const marketRows = pickArray(scan?.market_rows);
  const longRows = pickArray(scan?.long_term);
  const shortRows = pickArray(scan?.short_term);
  const stats = pickRecord(scan?.market_stats);
  const watchlistWritesEnabled = capabilities.watchlist_mutations_enabled;

  const watchlistRows = useMemo<Row[]>(() => {
    return watchlist.map((item) => {
      const ticker = item.ticker.toUpperCase();
      const market = marketRows.find((row) => String(row.ticker ?? "").toUpperCase() === ticker) ?? {};
      const long = longRows.find((row) => String(row.ticker ?? "").toUpperCase() === ticker) ?? {};
      const short = shortRows.find((row) => String(row.ticker ?? "").toUpperCase() === ticker) ?? {};
      return {
        ...market,
        watchlist_source: item.source,
        ticker,
        company_name: String(market.company_name ?? long.company_name ?? short.company_name ?? ticker),
        long_term_score: market.long_term_score ?? long.long_term_score,
        short_term_score: market.short_term_score ?? short.short_term_score,
        long_recommendation: long.recommendation_label,
        short_recommendation: short.recommendation_label,
        trade_state: market.trade_state ?? short.trade_state
      };
    });
  }, [longRows, marketRows, shortRows, watchlist]);

  function addItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!watchlistWritesEnabled) return;
    const ticker = tickerInput.trim().toUpperCase();
    if (!ticker) return;
    addWatchlistItem(ticker, "watchlist_page")
      .then((payload) => {
        setWatchlist(payload.watchlist);
        setTickerInput("");
        setStatus(`${ticker} saved.`);
      })
      .catch((err: Error) => setError(err.message));
  }

  function removeItem(ticker: string) {
    if (!watchlistWritesEnabled) return;
    removeWatchlistItem(ticker)
      .then((payload) => {
        setWatchlist(payload.watchlist);
        setStatus(`${ticker} removed.`);
      })
      .catch((err: Error) => setError(err.message));
  }

  const columns: DataTableColumn<Row>[] = [
    { key: "ticker", header: "Ticker", render: (row) => <span className="font-semibold text-white">{String(row.ticker ?? "N/A")}</span> },
    { key: "company_name", header: "Company" },
    { key: "daily_change_pct", header: "Day", align: "right", render: (row) => formatPct(row.daily_change_pct, 2) },
    { key: "long_term_score", header: "Long", align: "right" },
    { key: "short_term_score", header: "Short", align: "right" },
    { key: "long_recommendation", header: "Long Rec", render: (row) => row.long_recommendation ? <StatusBadge tone="positive">{String(row.long_recommendation)}</StatusBadge> : "N/A" },
    { key: "short_recommendation", header: "Short Rec", render: (row) => row.short_recommendation ? <StatusBadge tone="warning">{String(row.short_recommendation)}</StatusBadge> : "N/A" },
    {
      key: "remove",
      header: "",
      align: "right",
      sortable: false,
      render: (row) =>
        watchlistWritesEnabled ? (
          <button type="button" onClick={() => removeItem(String(row.ticker))} className="button button-danger px-2">
            Remove
          </button>
        ) : (
          <span className="text-xs text-[var(--dim)]">Read only</span>
        )
    }
  ];

  return (
    <div>
      <SectionHeader title="Watchlist" />

      <TerminalPanel title="Watchlist controls" eyebrow={String(scan?.universe_name ?? "Global Universe")}>
        <form onSubmit={addItem} className="grid gap-3 md:grid-cols-[1fr_130px_130px]">
          <label htmlFor="watchlist-ticker" className="grid gap-2 text-xs text-[var(--muted)]">
            Ticker
            <input
              id="watchlist-ticker"
              value={tickerInput}
              onChange={(event) => setTickerInput(event.target.value)}
              className="field"
              placeholder="AAPL, NVDA, ASML..."
              disabled={!watchlistWritesEnabled}
              autoCapitalize="characters"
              autoComplete="off"
            />
          </label>
          <button
            type="submit"
            className="button button-primary self-end disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!watchlistWritesEnabled}
          >
            Add
          </button>
          <button type="button" onClick={load} disabled={loading} className="button self-end disabled:cursor-not-allowed disabled:opacity-60">
            {loading ? "Loading…" : "Reload"}
          </button>
        </form>
        {!watchlistWritesEnabled ? (
          <div role="status" className="mt-3 border-t border-[var(--line-soft)] pt-3 text-xs text-[var(--amber)]">
            {capabilities.message}
          </div>
        ) : null}
        {status ? <div role="status" aria-live="polite" className="mt-3 text-xs text-[var(--muted)]">{status}</div> : null}
      </TerminalPanel>

      {loading && !scan ? <LoadingState title="Loading watchlist" message="Loading saved tickers and market context." /> : null}
      {error ? <TerminalPanel title="API error"><div role="alert" className="text-sm text-[var(--red)]">{error}</div></TerminalPanel> : null}

      <div className="mt-5 space-y-5">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="Saved" value={String(watchlist.length)} meta="Watchlist tickers" tone="info" />
          <MetricCard label="Matched" value={String(watchlistRows.filter((row) => row.daily_change_pct !== undefined).length)} meta="Present in latest scan" tone="positive" />
          <MetricCard label="Scan Size" value={String(stats.scanned_count ?? 0)} meta={String(scan?.updated_at ?? "No scan timestamp")} tone="neutral" />
          <MetricCard label="Ideas" value={`${stats.long_candidates ?? 0} / ${stats.short_candidates ?? 0}`} meta="Long / short candidates" tone="warning" />
        </div>

        <TerminalPanel title="Saved names" eyebrow="Watchlist repository">
          <DataTable rows={watchlistRows} columns={columns} emptyLabel="No watchlist names saved yet." />
        </TerminalPanel>
      </div>
    </div>
  );
}
