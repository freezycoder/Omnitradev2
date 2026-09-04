type Tone = "positive" | "negative" | "warning" | "neutral" | "info";

const toneClasses: Record<Tone, string> = {
  positive: "border-[var(--green-line)] bg-[var(--green-soft)] text-[var(--green)]",
  negative: "border-[var(--red-line)] bg-[var(--red-soft)] text-[var(--red)]",
  warning: "border-[var(--amber-line)] bg-[var(--amber-soft)] text-[var(--amber)]",
  neutral: "border-[var(--line)] bg-[var(--surface-muted)] text-[var(--muted)]",
  info: "border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent-strong)]"
};

export function StatusBadge({ children, tone = "neutral" }: { children: React.ReactNode; tone?: Tone }) {
  return (
    <span
      className={`mono inline-flex items-center gap-1.5 border px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] transition-all duration-300 hover:brightness-125 ${toneClasses[tone]}`}
    >
      <span aria-hidden="true" className="pulse-dot h-1 w-1 bg-current" />
      {children}
    </span>
  );
}
