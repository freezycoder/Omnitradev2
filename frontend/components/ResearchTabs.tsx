import Link from "next/link";

const tabs = [
  { href: "/overview", label: "Overview", code: "00" },
  { href: "/long-term", label: "Long term", code: "01" },
  { href: "/short-term", label: "Short term", code: "02" },
  { href: "/international", label: "International", code: "03" }
];

export function ResearchTabs({
  activeHref,
  queryString
}: {
  activeHref: string;
  queryString?: string;
}) {
  return (
    <nav aria-label="Scanner views" className="mb-6 overflow-x-auto border-b border-[var(--line-soft)]">
      <div className="flex min-w-max gap-6">
        {tabs.map((tab) => {
          const active = tab.href === activeHref;
          return (
            <Link
              key={tab.href}
              href={queryString ? `${tab.href}?${queryString}` : tab.href}
              aria-current={active ? "page" : undefined}
              data-active={active}
              className={`underline-grow flex min-h-11 items-center gap-2 pb-1 pt-2 transition-colors duration-300 ${
                active ? "text-[var(--text)]" : "text-[var(--dim)] hover:text-[var(--text)]"
              }`}
            >
              <span aria-hidden="true" className={`mono text-[10px] tracking-[0.1em] ${active ? "text-[var(--accent)]" : ""}`}>
                {tab.code}
              </span>
              <span className="font-display text-2xl uppercase leading-none tracking-[0.05em]">{tab.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
