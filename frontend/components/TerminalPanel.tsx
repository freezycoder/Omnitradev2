import { RESEARCH_OVERLAY_DISCLAIMER } from "@/lib/researchOverlay";

export function TerminalPanel({
  title,
  eyebrow,
  researchOverlay = false,
  children,
  action
}: {
  title: string;
  eyebrow?: string;
  researchOverlay?: boolean;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="tile animate-reveal group relative min-w-0 border border-[var(--line-soft)] bg-[var(--surface)]">
      <span aria-hidden="true" className="scanline" />
      <div className="border-b border-[var(--line-soft)]">
        <div className="flex min-h-12 items-center justify-between gap-4 px-4 py-3">
          <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="font-display text-2xl uppercase leading-none tracking-[0.05em] text-[var(--text)] transition-colors duration-300 group-hover:text-[var(--accent-strong)]">
              {title}
            </h2>
            {eyebrow ? (
              <div className="mono truncate text-[10px] uppercase tracking-[0.16em] text-[var(--accent)]">{eyebrow}</div>
            ) : null}
          </div>
          {action}
        </div>
        {researchOverlay ? (
          <div className="border-t border-[var(--line-soft)] bg-[var(--amber-soft)] px-4 py-2 font-display text-sm uppercase leading-snug tracking-[0.08em] text-[var(--amber)]">
            {RESEARCH_OVERLAY_DISCLAIMER}
          </div>
        ) : null}
      </div>
      <div className="min-w-0 p-4">{children}</div>
    </section>
  );
}
