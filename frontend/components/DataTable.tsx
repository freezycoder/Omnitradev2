"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable
} from "@tanstack/react-table";
import { useState } from "react";

export type DataTableColumn<T extends Record<string, unknown>> = {
  key: keyof T | string;
  header: string;
  render?: (row: T) => React.ReactNode;
  align?: "left" | "right" | "center";
  sortable?: boolean;
  sortValue?: (row: T) => string | number | null;
};

export function tickerHref(ticker: string) {
  return `/ticker?ticker=${encodeURIComponent(ticker)}`;
}

export function DataTable<T extends Record<string, unknown>>({
  rows,
  columns,
  emptyLabel = "No rows available"
}: {
  rows: T[];
  columns: DataTableColumn<T>[];
  emptyLabel?: string;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const router = useRouter();
  const tableColumns: ColumnDef<T>[] = columns.map((column) => ({
    id: String(column.key),
    header: column.header,
    accessorFn: (row) => column.sortValue?.(row) ?? row[column.key as keyof T] ?? null,
    enableSorting: column.sortable !== false,
    cell: ({ row }) => {
      const original = row.original;
      const content = column.render
        ? column.render(original)
        : String(original[column.key as keyof T] ?? "N/A");
      if (String(column.key) !== "ticker") return content;
      const ticker = String(original[column.key as keyof T] ?? "").trim().toUpperCase();
      return ticker ? (
        <Link
          href={tickerHref(ticker)}
          className="font-semibold text-[var(--text)] underline-offset-4 hover:text-[var(--accent-strong)] hover:underline"
          aria-label={`Analyze ${ticker}`}
        >
          {content}
        </Link>
      ) : content;
    }
  }));

  const table = useReactTable({
    data: rows,
    columns: tableColumns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel()
  });

  if (rows.length === 0) {
    return <div className="border border-dashed border-[var(--line-strong)] p-5 text-sm text-[var(--muted)]">{emptyLabel}</div>;
  }

  return (
    <div className="overflow-x-auto" tabIndex={0} aria-label="Scrollable data table">
      <table className="w-full min-w-[760px] border-collapse text-left text-sm">
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className="border-b border-[var(--line-soft)]">
              {headerGroup.headers.map((header, index) => {
                const sorted = header.column.getIsSorted();
                const sortable = header.column.getCanSort();
                const sticky = String(columns[index]?.key) === "ticker";
                return (
                  <th
                    key={header.id}
                    aria-sort={sortable ? (sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none") : undefined}
                    className={`mono bg-[var(--surface-accent)] px-3 py-2 text-[10px] font-medium uppercase tracking-[0.06em] text-[var(--muted)] ${
                      columns[index]?.align === "right" ? "text-right" : columns[index]?.align === "center" ? "text-center" : "text-left"
                    } ${sticky ? "data-sticky-header sticky left-0 z-20" : ""}`}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className={`inline-flex min-h-11 w-full items-center gap-1.5 focus-visible:outline-offset-[-2px] hover:text-[var(--text)] ${
                          columns[index]?.align === "right"
                            ? "justify-end"
                            : columns[index]?.align === "center"
                              ? "justify-center"
                              : "justify-start"
                        }`}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        <svg aria-hidden="true" viewBox="0 0 12 12" className="h-3 w-3 fill-none stroke-current" strokeWidth="1.4">
                          {sorted === "asc" ? (
                            <path d="m3 7 3-3 3 3" />
                          ) : sorted === "desc" ? (
                            <path d="m3 5 3 3 3-3" />
                          ) : (
                            <path d="m3 4 3-2 3 2M3 8l3 2 3-2" />
                          )}
                        </svg>
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => {
            const rowTicker = String((row.original as Record<string, unknown>).ticker ?? "").trim().toUpperCase();
            const openTicker = () => {
              if (rowTicker) router.push(tickerHref(rowTicker));
            };
            return (
            <tr
              key={row.id}
              onClick={rowTicker ? openTicker : undefined}
              onKeyDown={
                rowTicker
                  ? (event) => {
                      if (event.target !== event.currentTarget) return;
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openTicker();
                      }
                    }
                  : undefined
              }
              tabIndex={rowTicker ? 0 : undefined}
              role={rowTicker ? "link" : undefined}
              aria-label={rowTicker ? `Open ${rowTicker} ticker analysis` : undefined}
              className={`data-row border-b border-[var(--line-soft)] transition-colors hover:bg-[var(--accent-soft)] ${
                rowTicker ? "cursor-pointer focus-visible:outline focus-visible:outline-1 focus-visible:outline-[var(--accent)]" : ""
              }`}
            >
              {row.getVisibleCells().map((cell, index) => {
                const sticky = String(columns[index]?.key) === "ticker";
                return (
                  <td
                    key={cell.id}
                    className={`px-3 py-2.5 text-[var(--muted)] ${
                      columns[index]?.align === "right" ? "text-right" : columns[index]?.align === "center" ? "text-center" : "text-left"
                    } ${sticky ? "data-sticky-cell sticky left-0 z-10 bg-[var(--surface)]" : ""}`}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                );
              })}
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
