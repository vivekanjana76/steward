import { Panel } from "@/components/Panel";
import { VerdictBadge } from "@/components/VerdictBadge";
import { humanizeKind, relativeTime, shortHash, VERDICT_META } from "@/lib/format";
import type { ActionView } from "@/lib/types";

function ActionRow({ action }: { action: ActionView }) {
  const meta = VERDICT_META[action.verdict];
  const isHuman = action.actor.startsWith("human:");
  return (
    <li
      className="group relative px-5 py-3.5 transition-colors hover:bg-white/[0.02]"
      style={{ borderLeft: `2px solid rgba(${meta.rgb}, 0.55)` }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <VerdictBadge verdict={action.verdict} />
            <span className="font-mono text-xs text-slate-300">{humanizeKind(action.kind)}</span>
            {action.dry_run && (
              <span className="rounded border border-cyan-400/20 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-cyan-300/80">
                dry-run
              </span>
            )}
            {action.executed && (
              <span className="rounded border border-emerald-400/20 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-emerald-300/80">
                executed
              </span>
            )}
          </div>
          <p className="mt-1.5 truncate text-sm text-slate-200">{action.summary}</p>
          {action.note && (
            <p className="mt-0.5 truncate text-xs text-slate-500">{action.note}</p>
          )}
        </div>
        <div className="shrink-0 text-right">
          <div className="font-mono text-[11px] text-slate-400">
            {relativeTime(action.timestamp)}
          </div>
          <div className="mt-1 font-mono text-[10px] text-slate-600">#{action.seq}</div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10px] text-slate-500">
        <span className={isHuman ? "text-violet-300/80" : "text-slate-500"}>
          {isHuman ? "◆ " : "▸ "}
          {action.actor}
        </span>
        <span title={action.trace_id}>trace {shortHash(action.trace_id)}</span>
        <span title={action.entry_hash} className="text-slate-600">
          ⛓ {shortHash(action.entry_hash)}
        </span>
      </div>
    </li>
  );
}

export function ActivityStream({ actions }: { actions: ActionView[] }) {
  return (
    <Panel
      title="Activity Stream"
      caption="append-only audit log · every decision, replayable"
      accent="34, 211, 238"
      action={
        <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-slate-500">
          {actions.length} records
        </span>
      }
    >
      {actions.length === 0 ? (
        <div className="flex h-full min-h-64 flex-col items-center justify-center gap-2 px-6 text-center">
          <p className="text-sm text-slate-400">No actions recorded yet.</p>
          <p className="max-w-sm font-mono text-[11px] text-slate-600">
            Start the API with STEWARD_SEED_DEMO=true, or let the agent triage an issue —
            every step it takes lands here.
          </p>
        </div>
      ) : (
        <ul className="max-h-[34rem] divide-y divide-white/[0.04] overflow-y-auto">
          {actions.map((a) => (
            <ActionRow key={`${a.seq}-${a.entry_hash}`} action={a} />
          ))}
        </ul>
      )}
    </Panel>
  );
}
