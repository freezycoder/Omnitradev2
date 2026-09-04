"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { RouteSkeleton } from "./RouteSkeleton";

/**
 * Ordered map of dashboard sections. Navigating "down" the list animates
 * forward (content enters from the right), navigating "up" animates back.
 */
const ROUTE_ORDER = [
  "/overview",
  "/long-term",
  "/short-term",
  "/international",
  "/ticker",
  "/watchlist",
  "/portfolio",
  "/performance",
  "/long-term-performance",
  "/calibration"
];

const OUT_MS = 170;
const IN_MS = 460;
const SKELETON_HOLD_MS = 180;

function rank(pathname: string) {
  let best = 0;
  let matched = -1;
  ROUTE_ORDER.forEach((route, index) => {
    const hit = pathname === route || pathname.startsWith(`${route}/`);
    if (hit && route.length > matched) {
      matched = route.length;
      best = index;
    }
  });
  return best;
}

export function RouteTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [view, setView] = useState<{ key: string; node: React.ReactNode }>({
    key: pathname,
    node: children
  });
  const [phase, setPhase] = useState<"in" | "out">("in");
  const [direction, setDirection] = useState(1);
  const [transitioning, setTransitioning] = useState(false);
  const [skeleton, setSkeleton] = useState<"in" | "out" | null>(null);

  const latestChildren = useRef(children);
  latestChildren.current = children;
  const target = useRef(pathname);

  useEffect(() => {
    if (pathname === view.key) {
      // Same route, fresh children (data update) — swap without animating.
      setView({ key: pathname, node: children });
      return;
    }
    if (target.current === pathname) return;

    target.current = pathname;
    setDirection(rank(pathname) >= rank(view.key) ? 1 : -1);
    setTransitioning(true);
    setPhase("out");
    setSkeleton("in");

    const timers: number[] = [];

    timers.push(
      window.setTimeout(() => {
        setView({ key: pathname, node: latestChildren.current });
        setPhase("in");
      }, OUT_MS)
    );
    // Fade the skeleton out just as the new section blurs in.
    timers.push(window.setTimeout(() => setSkeleton("out"), OUT_MS + SKELETON_HOLD_MS));
    timers.push(window.setTimeout(() => setSkeleton(null), OUT_MS + SKELETON_HOLD_MS + 200));
    timers.push(window.setTimeout(() => setTransitioning(false), OUT_MS + IN_MS));

    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [pathname, children, view.key]);

  return (
    <div className="route-host min-w-0">
      {transitioning ? (
        <span aria-hidden="true" className="route-rail" data-dir={direction} key={pathname} />
      ) : null}
      {skeleton ? <RouteSkeleton phase={skeleton} /> : null}
      <div
        key={view.key}
        data-phase={phase}
        className="route-view stagger min-w-0"
        style={{ ["--route-dir" as string]: direction }}
      >
        {view.node}
      </div>
    </div>
  );
}
