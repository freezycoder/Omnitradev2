/**
 * Lightweight placeholder shown while a dashboard section swaps in.
 * Mirrors the terminal layout (header rule + bento tiles + panel) so the
 * transition reads as continuous rather than as an empty flash.
 */
export function RouteSkeleton({ phase }: { phase: "in" | "out" }) {
  return (
    <div className="route-skeleton" data-phase={phase} aria-hidden="true">
      <div className="space-y-3">
        <div className="skeleton-block h-3 w-40" />
        <div className="skeleton-block h-8 w-72" />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="skeleton-block h-28" />
        ))}
      </div>
      <div className="skeleton-block h-[320px]" />
    </div>
  );
}
