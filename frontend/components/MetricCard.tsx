type Tone = "positive" | "negative" | "warning" | "neutral" | "info";

const toneClasses: Record<Tone, string> = {
  positive: "text-[var(--green)]",
  negative: "text-[var(--red)]",
  warning: "text-[var(--amber)]",
  neutral: "text-[var(--text)]",
  info: "text-[var(--accent-strong)]"
};

const barClasses: Record<Tone, string> = {
  positive: "bg-[var(--green)]",
  negative: "bg-[var(--red)]",
  warning: "bg-[var(--amber)]",
  neutral: "bg-[var(--line-strong)]",
  info: "bg-[var(--accent)]"
};

const glowClasses: Record<Tone, string> = {
  positive: "before:bg-[var(--green-soft)]",
  negative: "before:bg-[var(--red-soft)]",
  warning: "before:bg-[var(--amber-soft)]",
  neutral: "before:bg-[var(--accent-soft)]",
  info: "before:bg-[var(--accent-soft)]"
};

export function MetricCard({
  label,
  value,
  meta,
  tone = "neutral"
}: {
  label: string;
  value: React.ReactNode;
  meta?: React.ReactNode;
  tone?: Tone;
}) {
  return (
    <div
      className={`tile group relative min-w-0 border border-[var(--line-soft)] bg-[var(--surface)] px-4 py-4 before:pointer-events-none before:absolute before:-right-12 before:-top-16 before:h-36 before:w-36 before:rounded-full before:opacity-0 before:blur-2xl before:transition-opacity before:duration-500 hover:before:opacity-100 ${glowClasses[tone]}`}
    >
      <div className="flex items-baseline justify-between gap-3">
        <div className="font-display text-lg uppercase leading-none tracking-[0.06em] text-[var(--muted)] transition-colors duration-300 group-hover:text-[var(--text)]">
          {label}
        </div>
        <span
          aria-hidden="true"
          className={`pulse-dot h-1.5 w-1.5 opacity-0 transition-opacity duration-300 group-hover:opacity-100 ${barClasses[tone]}`}
        />
      </div>
      <div
        className={`metric-number mt-4 text-[2.4rem] leading-none transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] group-hover:-translate-y-0.5 ${toneClasses[tone]}`}
      >
        {value}
      </div>
      <div className="mt-4 h-[2px] w-full overflow-hidden bg-[var(--line-soft)]">
        <div className={`animate-draw h-full w-full ${barClasses[tone]}`} />
      </div>
      {meta ? <div className="mt-3 text-xs leading-5 text-[var(--dim)]">{meta}</div> : null}
    </div>
  );
}
