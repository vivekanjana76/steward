// Server-side data access for the Steward API. All reads are uncached so the
// command center always reflects the live audit log + approval queue.
//
// Every fetch is wrapped so a missing/unreachable backend degrades gracefully:
// the page renders an honest "core offline" state instead of crashing (the live
// agent + API may not be running yet — CLAUDE.md's no-keys-until-the-end posture).

import type {
  ActionView,
  ApprovalView,
  HealthView,
  ScorecardView,
} from "@/lib/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_STEWARD_API?.replace(/\/$/, "") ?? "http://localhost:8000";

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export interface DashboardData {
  online: boolean;
  health: HealthView | null;
  actions: ActionView[];
  approvals: ApprovalView[];
  scorecard: ScorecardView | null;
}

export async function loadDashboard(): Promise<DashboardData> {
  const [health, actions, approvals, scorecard] = await Promise.all([
    getJson<HealthView>("/api/health"),
    getJson<ActionView[]>("/api/actions?limit=60"),
    getJson<ApprovalView[]>("/api/approvals"),
    getJson<ScorecardView>("/api/scorecard"),
  ]);

  return {
    online: health !== null,
    health,
    actions: actions ?? [],
    approvals: approvals ?? [],
    scorecard,
  };
}
