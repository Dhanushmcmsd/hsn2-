"use client";

import React from "react";

export interface GSTBadgeProps {
  rate: number | null;
  effectiveFrom: string | null; // ISO date string e.g. "2024-01-01"
  effectiveTo: string | null;   // ISO date string or null = currently active
}

/**
 * Formats an ISO date string ("YYYY-MM-DD" or full ISO) as "01 Jan 2024".
 * Falls back gracefully if the string is invalid.
 */
function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return new Intl.DateTimeFormat("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }).format(d);
  } catch {
    return iso;
  }
}

/**
 * GSTBadge
 * --------
 * Renders a green pill showing the GST rate and an optional date range line.
 * Returns null if rate is null.
 *
 * Usage:
 *   <GSTBadge rate={18} effectiveFrom="2024-01-01" effectiveTo={null} />
 */
export function GSTBadge({ rate, effectiveFrom, effectiveTo }: GSTBadgeProps) {
  if (rate == null) return null;

  // Date range label
  let dateLabel: string | null = null;
  if (effectiveFrom) {
    const from = formatDate(effectiveFrom);
    if (effectiveTo) {
      const to = formatDate(effectiveTo);
      dateLabel = `${from}\u2013${to}`; // en-dash
    } else {
      dateLabel = `Effective from ${from}`;
    }
  }

  return (
    <div className="inline-flex flex-col items-center gap-0.5">
      {/* Main pill */}
      <span
        className="inline-flex items-center gap-1.5 rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-800 dark:bg-green-900/30 dark:text-green-400"
        aria-label={`GST rate: ${rate}%`}
      >
        {/* Rupee icon */}
        <span className="text-[0.65rem] opacity-70" aria-hidden>&#x20B9;</span>
        GST {rate}%
      </span>

      {/* Date range subtitle */}
      {dateLabel && (
        <span className="mt-0.5 text-xs text-muted-foreground">
          {dateLabel}
        </span>
      )}
    </div>
  );
}

export default GSTBadge;
