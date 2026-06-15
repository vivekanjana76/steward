import { BrandMark } from "@/components/BrandMark";
import { Clock } from "@/components/Clock";
import type { HealthView } from "@/lib/types";

function Pill({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "cyan" | "violet" | "emerald" | "amber" | "slate";
}) {
  const tones: Record<typeof tone, string> = {
    cyan: "text-cyan-300 border-cyan-400/30",
    violet: "text-violet-300 border-violet-400/30",
    emerald: "text-emerald-300 border-emerald-400/30",
    amber: "text-amber-300 border-amber-400/30",
    slate: "text-slate-300 border-slate-400/20",
  };
  return (
    <div
      className={`flex items-center gap-2 rounded-full border ${tones[tone]} bg-white/[0.02] px-3 py-1`}
    >
      <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500">
        {label}
      </span>
      <span className="font-mono text-xs">{value}</span>
    </div>
  );
}

export function TopBar({ health, online }: { health: HealthView | null; online: boolean }) {
  return (
    <header className="hairline sticky top-0 z-20 backdrop-blur-xl">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-4">
        <div className="flex items-center gap-3">
          <BrandMark />
          <div className="leading-tight">
            <div className="flex items-center gap-2">
              <span className="font-display text-lg font-semibold tracking-tight">Steward</span>
              <span className="rounded bg-cyan-400/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.2em] text-cyan-300">
                Command Center
              </span>
            </div>
            <span className="font-mono text-[10px] uppercase tracking-[0.25em] text-slate-500">
              Bounded autonomy · grounded or silent
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex items-center gap-2 rounded-full border border-emerald-400/20 bg-white/[0.02] px-3 py-1">
            <span
              className={`h-2 w-2 rounded-full ${online ? "bg-emerald-400 live-dot" : "bg-rose-400"}`}
            />
            <span className="font-mono text-xs text-slate-300">
              {online ? "Core online" : "Core offline"}
            </span>
          </div>
          {health && (
            <>
              <Pill
                label="Mode"
                value={health.dry_run ? "DRY-RUN" : "LIVE"}
                tone={health.dry_run ? "cyan" : "amber"}
              />
              <Pill label="Env" value={health.env} tone="violet" />
              {health.target_repo && (
                <Pill label="Repo" value={health.target_repo} tone="slate" />
              )}
            </>
          )}
          <Clock />
        </div>
      </div>
    </header>
  );
}
