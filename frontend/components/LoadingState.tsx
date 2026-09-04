import { TerminalPanel } from "@/components/TerminalPanel";

export function LoadingState({
  title,
  message
}: {
  title: string;
  message: string;
}) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{message}</span>
      <TerminalPanel title={title}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-hidden="true">
          {[0, 1, 2, 3].map((item) => (
            <div key={item} className="border border-l-2 border-[var(--line-soft)] border-l-[var(--line-strong)] p-4">
              <div className="skeleton h-3 w-20" />
              <div className="skeleton mt-4 h-8 w-28" />
              <div className="skeleton mt-3 h-3 w-full" />
            </div>
          ))}
        </div>
        <div className="skeleton mt-4 h-56 w-full" aria-hidden="true" />
      </TerminalPanel>
    </div>
  );
}
