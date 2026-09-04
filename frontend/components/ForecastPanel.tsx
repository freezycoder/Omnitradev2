"use client";

import { useEffect, useMemo, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ChartLegend } from "@/components/ChartLegend";
import { StatusBadge } from "@/components/StatusBadge";
import { TerminalPanel } from "@/components/TerminalPanel";
import { fetchForecast, ForecastPayload } from "@/lib/api";
import { formatCurrency, formatSignedPct } from "@/lib/format";

const HORIZONS = [10, 30, 60];

function forecastDateLabel(value: unknown): string {
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.getTime())) return String(value ?? "");
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

type TradeLevels = { entryPrice: number; stopLossPrice: number; targetPrice: number };

export function ForecastPanel({ ticker, levels }: { ticker: string; levels?: TradeLevels }) {
  const [horizon, setHorizon] = useState(30);
  const [data, setData] = useState<ForecastPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchForecast(ticker, horizon, levels)
      .then((payload) => {
        if (active) setData(payload);
      })
      .catch((cause: unknown) => {
        if (active) {
          setData(null);
          setError(cause instanceof Error ? cause.message : "The forecast service is unavailable.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [ticker, horizon, levels]);

  const rows = useMemo(() => {
    if (!data) return [];
    const bands = data.bands ?? null;
    return data.points.map((point, index) => ({
      date: point.t,
      close: point.c,
      low: bands ? bands.p10[index] : null,
      high: bands ? bands.p90[index] : null,
      spread: bands ? Math.max(bands.p90[index] - bands.p10[index], 0) : null
    }));
  }, [data]);

  const expectedReturn = data?.expected_return_pct ?? null;
  const tone = expectedReturn === null ? "info" : expectedReturn >= 0 ? "positive" : "negative";

  return (
    <TerminalPanel
      title="Kronos forecast"
      eyebrow={data ? `${data.model} · ${data.horizon}D · research only` : "Foundation model · research only"}
      action={
        <div className="flex items-center gap-1">
          {HORIZONS.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setHorizon(value)}
              aria-pressed={horizon === value}
              className={`mono border px-2 py-1 text-[10px] uppercase tracking-[0.16em] transition-colors duration-200 ${
                horizon === value
                  ? "border-[var(--accent)] text-[var(--accent)]"
                  : "border-[var(--line-soft)] text-[var(--dim)] hover:text-[var(--text)]"
              }`}
            >
              {value}D
            </button>
          ))}
        </div>
      }
    >
      {loading && !data ? (
        <div className="mono text-xs uppercase tracking-[0.16em] text-[var(--dim)]">Requesting forecast…</div>
      ) : null}

      {error && !data ? (
        <div className="space-y-2 text-sm text-[var(--muted)]">
          <StatusBadge tone="warning">Forecast service offline</StatusBadge>
          <div>{error}</div>
        </div>
      ) : null}

      {data ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <StatusBadge tone={tone}>
              {expectedReturn === null ? "No projection" : `${formatSignedPct(expectedReturn, 2)} over ${data.horizon}D`}
            </StatusBadge>
            <div className="mono text-[10px] uppercase tracking-[0.16em] text-[var(--dim)]">
              Last close {formatCurrency(data.last_close)} → projected {formatCurrency(data.expected_close)}
            </div>
          </div>

          {data.trade_level_diagnostics ? (
            <div className="flex items-start gap-3 border border-[var(--line-soft)] p-3 text-xs text-[var(--muted)]">
              <StatusBadge tone={data.trade_level_diagnostics.status === "aligned" ? "positive" : data.trade_level_diagnostics.status === "conflict" ? "negative" : "warning"}>
                Levels {data.trade_level_diagnostics.status}
              </StatusBadge>
              <span>{data.trade_level_diagnostics.summary}</span>
            </div>
          ) : null}

          <ChartLegend
            items={[
              { label: "Forecast close", color: "var(--chart-accent)" },
              ...(data.bands ? [{ label: "P10–P90 band", color: "var(--chart-warning)", dashed: true }] : [])
            ]}
            summary={`${data.lookback} bars of context · ${data.points.length} projected sessions`}
          />

          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%" minWidth={1} minHeight={1} initialDimension={{ width: 1, height: 1 }}>
              <ComposedChart data={rows}>
                <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                <XAxis dataKey="date" stroke="var(--dim)" fontSize={11} minTickGap={28} tickFormatter={forecastDateLabel} />
                <YAxis stroke="var(--dim)" fontSize={11} domain={["dataMin", "dataMax"]} />
                <Tooltip
                  labelFormatter={forecastDateLabel}
                  contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", color: "var(--text)" }}
                />
                {data.bands ? (
                  <>
                    <Area type="monotone" dataKey="low" name="P10" stroke="none" fill="transparent" stackId="band" />
                    <Area
                      type="monotone"
                      dataKey="spread"
                      name="P10–P90"
                      stroke="none"
                      fill="var(--chart-warning)"
                      fillOpacity={0.12}
                      stackId="band"
                    />
                  </>
                ) : null}
                <Line type="monotone" dataKey="close" name="Forecast close" stroke="var(--chart-accent)" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          <div className="text-xs text-[var(--dim)]">
            {data.disclaimer ?? "Kronos output is a research forecast and does not affect signals."}
          </div>
        </div>
      ) : null}
    </TerminalPanel>
  );
}
