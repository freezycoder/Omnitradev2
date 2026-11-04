"use client";

import { FormEvent, useEffect, useState } from "react";
import { DataTable, DataTableColumn } from "@/components/DataTable";
import { LoadingState } from "@/components/LoadingState";
import { MetricCard } from "@/components/MetricCard";
import { SectionHeader } from "@/components/SectionHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import {
  ApiCapabilities,
  BookHolding,
  BookPosition,
  BookRole,
  BookSnapshot,
  fetchApiCapabilities,
  fetchBook,
  READ_ONLY_API_CAPABILITIES,
  saveBook
} from "@/lib/api";

function roleTone(role: BookRole) {
  switch (role) {
    case "risk":
      return "negative" as const;
    case "benefit":
      return "positive" as const;
    case "neutral":
      return "neutral" as const;
    case "unscored":
      return "warning" as const;
    default: {
      const unreachable: never = role;
      return unreachable;
    }
  }
}

function roleLabel(role: BookRole) {
  switch (role) {
    case "risk":
      return "Risk";
    case "benefit":
      return "Benefit";
    case "neutral":
      return "Neutral";
    case "unscored":
      return "Not in scan";
    default: {
      const unreachable: never = role;
      return unreachable;
    }
  }
}

export function BookPage() {
  const [snapshot, setSnapshot] = useState<BookSnapshot | null>(null);
  const [draft, setDraft] = useState<BookHolding[]>([]);
  const [tickerInput, setTickerInput] = useState("");
  const [weightInput, setWeightInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [capabilities, setCapabilities] = useState<ApiCapabilities>(READ_ONLY_API_CAPABILITIES);

  function apply(payload: BookSnapshot) {
    setSnapshot(payload);
    setDraft(payload.holdings);
  }

  useEffect(() => {
    let active = true;
    Promise.all([fetchBook(), fetchApiCapabilities().catch(() => READ_ONLY_API_CAPABILITIES)])
      .then(([book, capabilityPayload]) => {
        if (!active) return;
        apply(book);
        setCapabilities(capabilityPayload);
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

  const writesEnabled = capabilities.user_mutations_enabled;

  function addHolding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ticker = tickerInput.trim().toUpperCase();
    const weight = Number(weightInput);
    if (!ticker || !Number.isFinite(weight) || weight <= 0 || weight > 100) {
      setError("Enter a ticker and a weight between 0 and 100.");
      return;
    }
    setError(null);
    setDraft((current) => {
      const without = current.filter((holding) => holding.ticker !== ticker);
      return [...without, { ticker, weight_pct: Math.round(weight * 100) / 100 }];
    });
    setTickerInput("");
    setWeightInput("");
    setStatus(`${ticker} added to the draft. Save to keep it.`);
  }

  function removeHolding(ticker: string) {
    setDraft((current) => current.filter((holding) => holding.ticker !== ticker));
    setStatus(`${ticker} removed from the draft. Save to keep it.`);
  }

  function persist() {
    if (!writesEnabled) return;
    setSaving(true);
    setError(null);
    saveBook(draft)
      .then((payload) => {
        apply(payload);
        setStatus("Book saved.");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setSaving(false));
  }

  const columns: DataTableColumn<BookPosition>[] = [
    {
      key: "ticker",
      header: "Ticker",
      render: (row) => <span className="font-semibold text-white">{row.ticker}</span>
    },
    { key: "sector", header: "Sector", render: (row) => row.sector ?? "n/a" },
    {
      key: "weight_pct",
      header: "Weight",
      align: "right",
      render: (row) => `${row.weight_pct.toFixed(1)}%`
    },
    {
      key: "long_term_score",
      header: "Long score",
      align: "right",
      render: (row) => (row.long_term_score === null ? "n/a" : String(row.long_term_score))
    },
    {
      key: "recommendation_label",
      header: "Label",
      render: (row) => row.recommendation_label ?? "n/a"
    },
    {
      key: "role",
      header: "Reading",
      render: (row) => <StatusBadge tone={roleTone(row.role)}>{roleLabel(row.role)}</StatusBadge>
    },
    {
      key: "remove",
      header: "",
      align: "right",
      sortable: false,
      render: (row) =>
        writesEnabled ? (
          <button type="button" onClick={() => removeHolding(row.ticker)} className="button button-danger px-2">
            Remove
          </button>
        ) : (
          <span className="text-xs text-[var(--dim)]">Read only</span>
        )
    }
  ];

  const draftRows: BookPosition[] = draft.map((holding) => {
    const saved = snapshot?.positions.find((position) => position.ticker === holding.ticker);
    if (saved && saved.weight_pct === holding.weight_pct) return saved;
    return {
      ...holding,
      sector: null,
      long_term_score: null,
      recommendation_label: null,
      role: "neutral"
    };
  });
  const weightTotal = draft.reduce((sum, holding) => sum + holding.weight_pct, 0);

  return (
    <div>
      <SectionHeader title="Your book" badge="Saved weights" />

      <TerminalPanel title="Holdings" eyebrow="Percent of the book you want read">
        <form onSubmit={addHolding} className="grid gap-3 md:grid-cols-[1fr_140px_130px_130px]">
          <label htmlFor="book-ticker" className="grid gap-2 text-xs text-[var(--muted)]">
            Ticker
            <input
              id="book-ticker"
              value={tickerInput}
              onChange={(event) => setTickerInput(event.target.value)}
              className="field"
              placeholder="AAPL"
              disabled={!writesEnabled}
              autoCapitalize="characters"
              autoComplete="off"
            />
          </label>
          <label htmlFor="book-weight" className="grid gap-2 text-xs text-[var(--muted)]">
            Weight %
            <input
              id="book-weight"
              value={weightInput}
              onChange={(event) => setWeightInput(event.target.value)}
              className="field"
              placeholder="12.5"
              inputMode="decimal"
              disabled={!writesEnabled}
            />
          </label>
          <button
            type="submit"
            className="button button-primary self-end disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!writesEnabled}
          >
            Add
          </button>
          <button
            type="button"
            onClick={persist}
            className="button self-end disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!writesEnabled || saving}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </form>
        <p className="mt-3 text-xs leading-5 text-[var(--muted)]">
          Draft weight {weightTotal.toFixed(1)}%. Anything under 100% is treated as cash. Scores come from the latest scan, and the weekly email includes this reading after you save.
        </p>
        {!writesEnabled ? (
          <div role="status" className="mt-3 border-t border-[var(--line-soft)] pt-3 text-xs text-[var(--amber)]">
            {capabilities.message}
          </div>
        ) : null}
        {status ? <div role="status" aria-live="polite" className="mt-3 text-xs text-[var(--muted)]">{status}</div> : null}
      </TerminalPanel>

      {loading ? <LoadingState title="Loading your book" message="Reading saved weights and the latest scan." /> : null}
      {error ? (
        <TerminalPanel title="API error">
          <div role="alert" className="text-sm text-[var(--red)]">{error}</div>
        </TerminalPanel>
      ) : null}

      {snapshot ? (
        <div className="mt-5 space-y-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Names" value={String(draft.length)} meta={snapshot.summary} tone="info" />
            <MetricCard label="Largest" value={`${snapshot.largest_weight_pct.toFixed(1)}%`} meta="Biggest saved weight" tone={snapshot.largest_weight_pct >= 25 ? "warning" : "neutral"} />
            <MetricCard label="Cash" value={`${snapshot.cash_pct.toFixed(1)}%`} meta="Unallocated under 100%" tone="neutral" />
            <MetricCard label="Scan" value={snapshot.scan_source ?? "none"} meta={snapshot.scan_updated_at ?? "No scan timestamp"} tone="info" />
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <TerminalPanel title="Risk" eyebrow="Concentration and weak scores">
              {snapshot.risks.length ? (
                <ul className="space-y-2 text-sm leading-6 text-[var(--muted)]">
                  {snapshot.risks.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm leading-6 text-[var(--muted)]">No concentration or weak-score notes for the saved book.</p>
              )}
            </TerminalPanel>
            <TerminalPanel title="Possible benefit" eyebrow="Overlap with strong long-term scores">
              {snapshot.benefits.length ? (
                <ul className="space-y-2 text-sm leading-6 text-[var(--muted)]">
                  {snapshot.benefits.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm leading-6 text-[var(--muted)]">
                  No saved name is a long-term Strong Buy at 80 or above in this scan.
                </p>
              )}
            </TerminalPanel>
          </div>

          <TerminalPanel title="Saved names" eyebrow={snapshot.store === "postgres" ? "Alert ledger" : "This server"}>
            <DataTable rows={draftRows} columns={columns} emptyLabel="No holdings saved yet." />
            <p className="mt-3 text-xs leading-5 text-[var(--muted)]">
              Decision support, not financial advice, and not a broker. A benefit is overlap with the scanner, not a forecast of your returns.
            </p>
          </TerminalPanel>
        </div>
      ) : null}
    </div>
  );
}
