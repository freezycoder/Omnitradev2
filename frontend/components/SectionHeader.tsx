export function SectionHeader({
  title,
  badge
}: {
  title: string;
  badge?: string;
}) {
  return (
    <div className="mb-6 flex flex-col justify-between gap-3 border-b border-[var(--line-strong)] pb-4 sm:flex-row sm:items-end">
      <div className="min-w-0">
        <h1 className="animate-reveal font-display text-[2.75rem] uppercase leading-[0.95] tracking-[0.02em] text-[var(--text)] sm:text-[3.25rem]">
          {title}
          <span className="gold-drift">.</span>
        </h1>
        <div aria-hidden="true" className="hairline animate-draw mt-3 w-40" />
      </div>
      {badge ? (
        <div className="mono w-fit text-[10px] uppercase leading-5 tracking-[0.18em] text-[var(--accent-strong)]">{badge}</div>
      ) : null}
    </div>
  );
}
