"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { RouteTransition } from "./RouteTransition";

type NavigationItem = {
  href: string;
  label: string;
  code: string;
  index: string;
  match?: string[];
};

const scannerRoutes = ["/overview", "/long-term", "/short-term", "/international"];

const navGroups: { label: string; index: string; items: NavigationItem[] }[] = [
  {
    label: "Research",
    index: "01",
    items: [
      { href: "/overview", label: "Scanner", code: "SCAN", index: "01", match: scannerRoutes },
      { href: "/ticker", label: "Ticker Analysis", code: "TICK", index: "02" },
      { href: "/watchlist", label: "Watchlist", code: "LIST", index: "03" }
    ]
  },
  {
    label: "Portfolio",
    index: "02",
    items: [{ href: "/portfolio", label: "Portfolio", code: "BOOK", index: "04" }]
  },
  {
    label: "Validation",
    index: "03",
    items: [
      { href: "/performance", label: "Performance Lab", code: "LAB", index: "05" },
      { href: "/long-term-performance", label: "Long-Term Performance", code: "LONG", index: "06" },
      { href: "/calibration", label: "Calibration", code: "CAL", index: "07" }
    ]
  }
];

function isActive(pathname: string, item: NavigationItem) {
  const routes = item.match ?? [item.href];
  return routes.some((route) => pathname === route || pathname.startsWith(`${route}/`));
}

function NavigationGroups({
  pathname,
  onNavigate
}: {
  pathname: string;
  onNavigate?: () => void;
}) {
  return (
    <div className="space-y-8">
      {navGroups.map((group) => (
        <div key={group.label}>
          <div className="mono mb-3 px-3 text-[10px] uppercase tracking-[0.24em] text-[var(--dim)]">
            {group.index} / {group.label}
          </div>
          <div className="space-y-0.5">
            {group.items.map((item) => {
              const active = isActive(pathname, item);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={`group flex min-h-11 items-center gap-3 border-l-2 px-3 transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:translate-x-1 ${
                    active
                      ? "border-l-[var(--accent)] bg-[var(--surface-accent)] text-[var(--accent-strong)]"
                      : "border-l-transparent text-[var(--muted)] hover:border-l-[var(--line-strong)] hover:bg-[var(--surface-muted)] hover:text-[var(--text)]"
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={`mono shrink-0 text-[10px] tracking-[0.08em] transition-colors duration-300 ${
                      active ? "text-[var(--accent)]" : "text-[var(--dim)] group-hover:text-[var(--accent)]"
                    }`}
                  >
                    {item.index}
                  </span>
                  <span className="font-display text-xl leading-none tracking-[0.05em] uppercase">{item.label}</span>
                </Link>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const currentItem = navGroups
    .flatMap((group) => group.items)
    .find((item) => isActive(pathname, item));

  return (
    <div className="terminal-grid min-h-screen">
      <div className="mx-auto flex min-h-screen w-full max-w-[1600px]">
        <aside className="hidden w-[248px] shrink-0 flex-col border-r border-[var(--line-soft)] bg-[var(--background)] py-6 lg:flex">
          <Link href="/overview" aria-label="OmniTrade overview" className="mb-10 block px-5">
            <Image
              src="/brand/omnitrade-sidebar-logo.png"
              alt="OmniTrade Research"
              width={900}
              height={272}
              priority
              className="h-auto w-[172px] transition-opacity duration-300 hover:opacity-80"
            />
            <div className="gold-drift mono mt-2 text-[10px] tracking-[0.22em]">TERMINAL // OPS</div>
          </Link>

          <nav aria-label="Primary navigation" className="flex-1 px-2">
            <NavigationGroups pathname={pathname} />
          </nav>

          <div className="mt-8 flex items-center gap-3 border-t border-[var(--line-soft)] px-5 pt-5">
            <span aria-hidden="true" className="pulse-dot h-1.5 w-1.5 bg-[var(--green)] text-[var(--green)]" />
            <span className="mono text-[10px] uppercase tracking-[0.14em] text-[var(--dim)]">Market live // NYS</span>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
            <div className="mb-6 border-b border-[var(--line-strong)] pb-3 lg:hidden">
              <div className="flex min-h-11 items-center justify-between gap-3">
                <Link href="/overview" aria-label="OmniTrade overview" className="min-w-0">
                  <Image
                    src="/brand/omnitrade-sidebar-logo.png"
                    alt="OmniTrade Research"
                    width={900}
                    height={272}
                    priority
                    className="h-auto w-36"
                  />
                </Link>
                <div className="flex min-w-0 items-center gap-2">
                  <span className="mono max-w-32 truncate text-[10px] tracking-[0.08em] text-[var(--dim)]">
                    {currentItem?.code ?? "NAV"} / {currentItem?.label ?? "Navigation"}
                  </span>
                  <button
                    type="button"
                    aria-expanded={mobileMenuOpen}
                    aria-controls="mobile-navigation"
                    onClick={() => setMobileMenuOpen((open) => !open)}
                    className="button min-w-11 gap-2"
                  >
                    <svg aria-hidden="true" viewBox="0 0 20 20" className="h-4 w-4 fill-none stroke-current" strokeWidth="1.75">
                      <path d="M3 5h14M3 10h14M3 15h14" />
                    </svg>
                    Menu
                  </button>
                </div>
              </div>
              {mobileMenuOpen ? (
                <nav id="mobile-navigation" aria-label="Mobile navigation" className="animate-reveal mt-3 border-t border-[var(--line-soft)] pt-3">
                  <NavigationGroups pathname={pathname} onNavigate={() => setMobileMenuOpen(false)} />
                </nav>
              ) : null}
            </div>
            <RouteTransition>{children}</RouteTransition>
          </main>

          <footer className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 border-t border-[var(--line-soft)] bg-[var(--surface)] px-4 py-2.5 sm:px-6 lg:px-8">
            <div className="flex flex-wrap gap-x-6 gap-y-1">
              <span className="mono text-[10px] uppercase tracking-[0.14em] text-[var(--dim)]">
                Module <span className="text-[var(--accent-strong)]">{currentItem?.code ?? "NAV"}</span>
              </span>
              <span className="mono flex items-center gap-1.5 text-[10px] uppercase tracking-[0.14em] text-[var(--dim)]">
                Stream <span aria-hidden="true" className="pulse-dot h-1 w-1 bg-[var(--green)] text-[var(--green)]" />{" "}
                <span className="text-[var(--green)]">Connected</span>
              </span>
            </div>
            <span className="mono text-[10px] uppercase tracking-[0.14em] text-[var(--dim)]">OmniTrade Research Terminal</span>
          </footer>
        </div>
      </div>
    </div>
  );
}
