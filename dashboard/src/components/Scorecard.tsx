import { Panel } from "@/components/Panel";
import { formatMetric } from "@/lib/format";
import type { ScorecardView } from "@/lib/types";

export function Scorecard({ scorecard }: { scorecard: ScorecardView | null }) {
  const available = scorecard?.available ?? false;
  const metrics = scorecard?.metrics ?? [];

  return (
    <Panel
      title="Eval Scorecard"
      caption="measured · published honestly, including failures"
      accent="139, 92, 246"
      action={
        scorecard?.subset ? (
          <span className="font-mono text-[10px] text-slate-500">{scorecard.subset}</span>
        ) : undefined
      }
    >
      {!available ? (
        <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
          <p className="text-sm text-slate-300">Not yet measured.</p>
          <p className="max-w-md font-mono text-[11px] text-slate-600">
            The eval harness (triage F1, dedup P/R, repro accuracy, SWE-bench % resolved,
            cost &amp; latency) lands in M6. Until it writes a report, Steward shows nothing
            rather than fabricating numbers.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-b-2xl bg-white/[0.04] md:grid-cols-3 lg:grid-cols-4">
          {metrics.map((m) => (
            <div key={m.key} className="bg-[var(--color-abyss)] p-4">
              <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">
                {m.label}
              </div>
              <div className="mt-2 font-display text-2xl font-semibold tabular-nums text-violet-200">
                {formatMetric(m.value, m.unit)}
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
