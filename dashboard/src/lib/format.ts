// Small presentation helpers shared across components.

import type { PolicyVerdict } from "@/lib/types";

export interface VerdictMeta {
  label: string;
  /** Tailwind text color for the accent. */
  text: string;
  /** Tailwind border color. */
  border: string;
  /** rgb triplet for inline glow / gradient. */
  rgb: string;
}

export const VERDICT_META: Record<PolicyVerdict, VerdictMeta> = {
  allow: {
    label: "ALLOW",
    text: "text-emerald-300",
    border: "border-emerald-400/30",
    rgb: "52, 211, 153",
  },
  require_approval: {
    label: "APPROVAL",
    text: "text-amber-300",
    border: "border-amber-400/30",
    rgb: "251, 191, 36",
  },
  deny: {
    label: "DENY",
    text: "text-rose-300",
    border: "border-rose-400/30",
    rgb: "251, 113, 133",
  },
};

const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

/** A compact "3m ago" / "in 12h" string from an ISO timestamp. */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const diffMs = new Date(iso).getTime() - now;
  const abs = Math.abs(diffMs);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (abs < minute) return diffMs >= 0 ? "now" : "just now";
  if (abs < hour) return RELATIVE.format(Math.round(diffMs / minute), "minute");
  if (abs < day) return RELATIVE.format(Math.round(diffMs / hour), "hour");
  return RELATIVE.format(Math.round(diffMs / day), "day");
}

/** Shorten a hex hash/trace id to `abcd…wxyz` for dense display. */
export function shortHash(value: string, head = 6, tail = 4): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

/** Format a scorecard metric value with its unit, or an em dash when absent. */
export function formatMetric(value: number | null, unit: string): string {
  if (value === null) return "—";
  if (unit === "%") return `${value.toFixed(1)}%`;
  if (unit === "USD") return `$${value.toFixed(4)}`;
  if (unit === "s") return `${value.toFixed(2)}s`;
  return value.toFixed(2);
}

/** Humanize an ActionKind enum value, e.g. "open_draft_pr" -> "Open draft PR". */
export function humanizeKind(kind: string): string {
  const words = kind.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
