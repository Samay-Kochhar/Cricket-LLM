"use client";

import { useMemo, useState } from "react";

import type { TableBlock } from "@/lib/api-types";

const DEFAULT_VISIBLE_ROWS = 5;

type CompactDataTableProps = {
  table: TableBlock;
  initialRows?: number;
  onMinimumBallsApply?: (minimumBalls: number) => Promise<void> | void;
};

type SortState = {
  columnIndex: number;
  direction: "asc" | "desc";
} | null;

function numericValue(value: string | number | null | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value !== "string") {
    return null;
  }
  const cleaned = value.replace(/,/g, "").replace("%", "").trim();
  if (!cleaned) {
    return null;
  }
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function compareCells(a: string | number | null, b: string | number | null, direction: "asc" | "desc") {
  const aNumber = numericValue(a);
  const bNumber = numericValue(b);
  const multiplier = direction === "asc" ? 1 : -1;

  if (aNumber !== null && bNumber !== null) {
    return (aNumber - bNumber) * multiplier;
  }
  return String(a ?? "").localeCompare(String(b ?? ""), undefined, { numeric: true }) * multiplier;
}

export function CompactDataTable({
  table,
  initialRows = DEFAULT_VISIBLE_ROWS,
  onMinimumBallsApply,
}: CompactDataTableProps) {
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const [minimumBalls, setMinimumBalls] = useState("");
  const [isApplyingMinimum, setIsApplyingMinimum] = useState(false);
  const [sort, setSort] = useState<SortState>(null);
  const ballsColumnIndex = table.columns.findIndex((column) => column.toLowerCase() === "balls");
  const trimmedQuery = query.trim().toLowerCase();
  const minimumBallsValue = numericValue(minimumBalls);

  const filteredRows = useMemo(() => {
    const rows = table.rows.filter((row) => {
      const matchesQuery =
        !trimmedQuery ||
        row.some((cell) => String(cell ?? "").toLowerCase().includes(trimmedQuery));
      const matchesMinimumBalls =
        onMinimumBallsApply !== undefined ||
        ballsColumnIndex < 0 ||
        minimumBallsValue === null ||
        (numericValue(row[ballsColumnIndex]) ?? -Infinity) >= minimumBallsValue;
      return matchesQuery && matchesMinimumBalls;
    });

    if (!sort) {
      return rows;
    }

    return [...rows].sort((a, b) => compareCells(a[sort.columnIndex], b[sort.columnIndex], sort.direction));
  }, [ballsColumnIndex, minimumBallsValue, onMinimumBallsApply, sort, table.rows, trimmedQuery]);

  const visibleRows = expanded ? filteredRows : filteredRows.slice(0, initialRows);
  const hiddenCount = Math.max(filteredRows.length - initialRows, 0);

  function handleSort(columnIndex: number) {
    setSort((current) => {
      if (!current || current.columnIndex !== columnIndex) {
        return { columnIndex, direction: "asc" };
      }
      if (current.direction === "asc") {
        return { columnIndex, direction: "desc" };
      }
      return null;
    });
  }

  return (
    <div className="compact-table">
      <div className="table-controls">
        <label className="table-control">
          <span>Search</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
        {ballsColumnIndex >= 0 ? (
          <div className="table-control compact-number-control">
            <label htmlFor={`${table.title}-minimum-balls`}>
              {onMinimumBallsApply ? "Min balls" : "Filter shown rows by balls"}
            </label>
            <div className="minimum-balls-row">
              <input
                id={`${table.title}-minimum-balls`}
                inputMode="numeric"
                min="0"
                type="number"
                value={minimumBalls}
                onChange={(event) => setMinimumBalls(event.target.value)}
              />
              {onMinimumBallsApply ? (
                <button
                  className="ghost-button inline-button"
                  disabled={isApplyingMinimum || minimumBallsValue === null || minimumBallsValue < 0}
                  onClick={async () => {
                    if (minimumBallsValue === null || minimumBallsValue < 0) {
                      return;
                    }
                    setIsApplyingMinimum(true);
                    try {
                      await onMinimumBallsApply(minimumBallsValue);
                    } finally {
                      setIsApplyingMinimum(false);
                    }
                  }}
                  type="button"
                >
                  {isApplyingMinimum ? "Applying…" : "Apply to query"}
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
      <div className="table-wrap">
        <table className="result-table">
          <thead>
            <tr>
              {table.columns.map((column, columnIndex) => (
                <th key={column}>
                  <button className="table-sort-button" onClick={() => handleSort(columnIndex)} type="button">
                    <span>{column}</span>
                    <span aria-hidden="true" className="sort-indicator">
                      {sort?.columnIndex === columnIndex ? (sort.direction === "asc" ? "↑" : "↓") : "↕"}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, rowIndex) => (
              <tr key={`${table.title}-${rowIndex}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${table.title}-${rowIndex}-${cellIndex}`}>{cell ?? "-"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-footer">
        <span className="table-row-count">
          Showing {visibleRows.length} of {filteredRows.length} rows
          {filteredRows.length !== table.rows.length ? ` (${table.rows.length} total)` : ""}
        </span>
        {hiddenCount > 0 ? (
          <button className="ghost-button inline-button table-toggle" onClick={() => setExpanded((current) => !current)} type="button">
            {expanded ? "Show top 5" : `View ${hiddenCount} more rows`}
          </button>
        ) : null}
      </div>
    </div>
  );
}
