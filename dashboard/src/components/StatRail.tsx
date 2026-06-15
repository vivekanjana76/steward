import type { ActionView, ApprovalView } from "@/lib/types";

interface Stat {
  label: string;
  value: string;
  sub: string;
  rgb: string;
}

function buildStats(actions: ActionView[], approvals: ApprovalView[]): Stat[] {
  const total = actions.length;
  const denied = actions.filter((a) => a.verdict === "deny").length;
  const dryRun = actions.filter((a) => a.dry_run).length;
  const dryPct = total === 0 ? 100 : Math.round((dryRun / total) * 100);

  return [
    {
      label: "Pending approvals",
      value: String(approvals.length),
      sub: approvals.length === 0 ? "queue clear" : "awaiting a human",
      rgb: "251, 191, 36",
    },
    {
      label: "Actions recorded",
      value: String(total),
      sub: "append-only · hash-chained",
      rgb: "34, 211, 238",
    },
    {
      label: "Dry-run share",
      value: `${dryPct}%`,
      sub: "nothing live without opt-in",
      rgb: "139, 92, 246",
    },
    {
      label: "Blacklist denials",
      value: String(denied),
      sub: "structurally impossible to run",
      rgb: "251, 113, 133",
    },
  ];
}

export function StatRail({
  actions,
  approvals,
}: {
  actions: ActionView[];
  approvals: ApprovalView[];
}) {
  const stats = buildStats(actions, approvals);
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {stats.map((s) => (
        <div
          key={s.label}
          className="glass glass-hover relative overflow-hidden rounded-2xl p-5"
          style={{ animation: "rise 0.5s ease both" }}
        >
          <div
            className="absolute -right-6 -top-6 h-24 w-24 rounded-full blur-2xl"
            style={{ background: `rgba(${s.rgb}, 0.18)` }}
            aria-hidden
          />
          <div className="font-mono text-[10px] uppercase tracking-[0.22em] text-slate-500">
            {s.label}
          </div>
          <div
            className="mt-3 font-display text-4xl font-semibold tabular-nums"
            style={{ color: `rgb(${s.rgb})`, textShadow: `0 0 30px rgba(${s.rgb}, 0.45)` }}
          >
            {s.value}
          </div>
          <div className="mt-1 text-xs text-slate-400">{s.sub}</div>
        </div>
      ))}
    </div>
  );
}
