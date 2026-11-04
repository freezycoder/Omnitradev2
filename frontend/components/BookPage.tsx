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
  BookCoverage,
  BookPosition,
  BookPosture,
  BookRole,
  BookSnapshot,
  BookStrategy,
  StrategyKind,
  fetchApiCapabilities,
  fetchBook,
  READ_ONLY_API_CAPABILITIES,
  rescoreBook,
  saveBook
} from "@/lib/api";

function coverageLabel(coverage: BookCoverage | undefined) {
  switch (coverage) {
    case "scan":
      return "Scanner";
    case "portfolio":
      return "Scored for you";
    case "fund":
      return "Fund";
    case "none":
      return "No data";
    case undefined:
      return "Not saved";
    default: {
      const unreachable: never = coverage;
      return unreachable;
    }
  }
}

const PORTFOLIO_FUNDS = [
  { ticker: "VWCE", name: "Vanguard FTSE All-World UCITS ETF Acc", sector: "All-world equity" },
  { ticker: "AUM5", name: "Amundi S&P 500 UCITS ETF EUR Acc", sector: "US large cap" },
  { ticker: "QNTM", name: "VanEck Quantum Computing UCITS ETF", sector: "Quantum computing" }
] as const;

type DraftHolding = {
  ticker: string;
  weight_pct: number | null;
};

function StrategyRow({ item }: { item: BookStrategy }) {
  return (
    <li className="border-b border-[var(--line-soft)] pb-3 last:border-0">
      <div className="mb-1">
        <StatusBadge tone={strategyTone(item.kind)}>{item.kind}</StatusBadge>
      </div>
      <div className="text-sm text-white">{item.title}</div>
      <p className="mt-1 text-sm leading-6 text-[var(--muted)]">{item.detail}</p>
    </li>
  );
}

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

function postureTone(posture: BookPosture) {
  switch (posture) {
    case "maintain":
      return "positive" as const;
    case "trim":
      return "warning" as const;
    case "rebuild":
      return "negative" as const;
    case "empty":
      return "neutral" as const;
    default: {
      const unreachable: never = posture;
      return unreachable;
    }
  }
}

function strategyTone(kind: StrategyKind) {
  switch (kind) {
    case "keep":
      return "positive" as const;
    case "trim":
      return "warning" as const;
    case "review":
      return "negative" as const;
    case "research":
      return "info" as const;
    case "cash":
      return "neutral" as const;
    default: {
      const unreachable: never = kind;
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
      return "No data";
    default: {
      const unreachable: never = role;
      return unreachable;
    }
  }
}

export function BookPage() {
  const [snapshot, setSnapshot] = useState<BookSnapshot | null>(null);
  const [draft, setDraft] = useState<DraftHolding[]>([]);
  const [tickerInput, setTickerInput] = useState("");
  const [weightInput, setWeightInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [capabilities, setCapabilities] = useState<ApiCapabilities>(READ_ONLY_API_CAPABILITIES);

  function apply(payload: BookSnapshot) {
    setSnapshot(payload);
    setDraft(
      payload.holdings.length > 0
        ? payload.holdings
        : PORTFOLIO_FUNDS.map((fund) => ({ ticker: fund.ticker, weight_pct: null }))
    );
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

  function setWeight(ticker: string, value: string) {
    const weight = value.trim() === "" ? null : Number(value);
    setDraft((current) =>
      current.map((holding) =>
        holding.ticker === ticker
          ? { ...holding, weight_pct: weight !== null && Number.isFinite(weight) ? weight : null }
          : holding
      )
    );
  }

  function rescore() {
    if (!writesEnabled) return;
    setSaving(true);
    setError(null);
    setStatus("Scoring each stock you hold. This can take up to a minute.");
    rescoreBook()
      .then((payload) => {
        apply(payload);
        setStatus("Held stocks scored.");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setSaving(false));
  }

  function persist() {
    if (!writesEnabled) return;
    if (draft.some((holding) => holding.weight_pct === null || holding.weight_pct <= 0 || holding.weight_pct > 100)) {
      setError("Enter a weight between 0 and 100 for each fund, then save.");
      return;
    }
    const holdings = draft.flatMap((holding) =>
      holding.weight_pct === null ? [] : [{ ticker: holding.ticker, weight_pct: holding.weight_pct }]
    );
    setSaving(true);
    setError(null);
    saveBook(holdings)
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
      render: (row) =>
        writesEnabled ? (
          <input
            aria-label={`${row.ticker} weight percent`}
            value={row.weight_pct || ""}
            onClick={(event) => event.stopPropagation()}
            onChange={(event) => setWeight(row.ticker, event.target.value)}
            className="field w-20 text-right"
            inputMode="decimal"
            placeholder="%"
          />
        ) : (
          `${row.weight_pct.toFixed(1)}%`
        )
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
      key: "coverage",
      header: "Score from",
      render: (row) => coverageLabel(row.coverage)
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
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              removeHolding(row.ticker);
            }}
            className="button button-danger px-2"
          >
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
    const fund = PORTFOLIO_FUNDS.find((item) => item.ticker === holding.ticker);
    return {
      ticker: holding.ticker,
      weight_pct: holding.weight_pct ?? 0,
      sector: fund?.sector ?? null,
      long_term_score: null,
      recommendation_label: fund?.name ?? null,
      role: "neutral"
    };
  });
  const weightTotal = draft.reduce((sum, holding) => sum + (holding.weight_pct ?? 0), 0);

  return (
    <div>
      <SectionHeader title="Your portfolio" badge="Risk model" />

      <TerminalPanel title="Holdings" eyebrow="Percent of the book you want read">
        <form onSubmit={addHolding} className="grid gap-3 md:grid-cols-[1fr_140px_110px_110px_110px]">
          <label htmlFor="book-ticker" className="grid gap-2 text-xs text-[var(--muted)]">
            Ticker
            <input
              id="book-ticker"
              value={tickerInput}
              onChange={(event) => setTickerInput(event.target.value)}
              className="field"
              placeholder="VWCE, AUM5, QNTM, AAPL"
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
          <button
            type="button"
            onClick={rescore}
            className="button self-end disabled:cursor-not-allowed disabled:opacity-60"
            disabled={!writesEnabled || saving}
          >
            Rescore
          </button>
        </form>
        <p className="mt-3 text-xs leading-5 text-[var(--muted)]">
          Draft weight {weightTotal.toFixed(1)}%. VWCE, AUM5, and QNTM are already in this portfolio. Enter each weight and save. Anything under 100% is treated as cash. Use CSP5 instead of AUM5 if the Amundi fund is the physical Core share class.
        </p>
        {!writesEnabled ? (
          <div role="status" className="mt-3 border-t border-[var(--line-soft)] pt-3 text-xs text-[var(--amber)]">
            {capabilities.message}
          </div>
        ) : null}
        {status ? <div role="status" aria-live="polite" className="mt-3 text-xs text-[var(--muted)]">{status}</div> : null}
      </TerminalPanel>

      {loading ? <LoadingState title="Loading your portfolio" message="Reading saved weights against the scan and the 20% name cap." /> : null}
      {error ? (
        <TerminalPanel title="API error">
          <div role="alert" className="text-sm text-[var(--red)]">{error}</div>
        </TerminalPanel>
      ) : null}

      {snapshot ? (
        <div className="mt-5 space-y-5">
          <TerminalPanel title={snapshot.posture_label} eyebrow={`Risk score ${snapshot.risk_score} of 100`}>
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge tone={postureTone(snapshot.posture)}>{snapshot.posture_label}</StatusBadge>
              <p className="max-w-3xl text-sm leading-6 text-[var(--muted)]">{snapshot.posture_reason}</p>
            </div>
            <p className="mt-3 text-xs leading-5 text-[var(--dim)]">
              The score rises when a name exceeds the strategy engine&apos;s 20% cap, a sector exceeds 40%, or weight sits on a weak score or outside the scan. It is not a forecast of returns.
            </p>
          </TerminalPanel>

          <TerminalPanel title="Next research steps" eyebrow="Keep, trim, review, or research">
            {snapshot.strategies.length ? (
              <ul className="space-y-4">
                {snapshot.strategies.map((item) => (
                  <StrategyRow key={`${item.kind}-${item.ticker ?? "cash"}-${item.title}`} item={item} />
                ))}
              </ul>
            ) : (
              <p className="text-sm leading-6 text-[var(--muted)]">Save at least one holding to see the next research steps.</p>
            )}
          </TerminalPanel>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard label="Names" value={String(draft.length)} meta={snapshot.summary} tone="info" />
            <MetricCard label="Largest" value={`${snapshot.largest_weight_pct.toFixed(1)}%`} meta="20% is the strategy cap" tone={snapshot.largest_weight_pct > 20 ? "warning" : "neutral"} />
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
