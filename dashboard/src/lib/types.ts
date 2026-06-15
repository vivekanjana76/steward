// Typed mirrors of the Steward API response schemas (src/steward/api/schemas.py).
// Keep these in sync with the Pydantic models — they are the dashboard's contract.

export type PolicyVerdict = "allow" | "require_approval" | "deny";

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";

export interface HealthView {
  status: string;
  env: string;
  dry_run: boolean;
  target_repo: string | null;
}

export interface ActionView {
  seq: number;
  timestamp: string;
  trace_id: string;
  actor: string;
  kind: string;
  repo: string;
  summary: string;
  verdict: PolicyVerdict;
  rule: string;
  reason: string;
  dry_run: boolean;
  executed: boolean;
  note: string | null;
  entry_hash: string;
}

export interface ApprovalView {
  approval_id: string;
  kind: string;
  repo: string;
  summary: string;
  reason: string;
  trace_id: string;
  requested_at: string;
  expires_at: string;
  status: ApprovalStatus;
  resolved_by: string | null;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface ScorecardMetric {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  note: string | null;
}

export interface ScorecardView {
  available: boolean;
  generated_at: string | null;
  subset: string | null;
  source: string | null;
  metrics: ScorecardMetric[];
}
