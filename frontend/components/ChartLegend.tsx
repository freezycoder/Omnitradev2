type LegendItem = {
  label: string;
  color: string;
  dashed?: boolean;
};

export function ChartLegend({
  items,
  summary
}: {
  items: LegendItem[];
  summary: string;
}) {
  return (
    <div className="mb-3 flex flex-col gap-2 text-xs text-[var(--muted)] sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap gap-x-4 gap-y-2" aria-label="Chart legend">
        {items.map((item) => (
          <div key={item.label} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className={`block w-5 border-t-2 ${item.dashed ? "border-dashed" : ""}`}
              style={{ borderColor: item.color }}
            />
            <span>{item.label}</span>
          </div>
        ))}
      </div>
      <p className="max-w-xl leading-5 text-[var(--dim)]">{summary}</p>
    </div>
  );
}
