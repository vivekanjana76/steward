"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Panel } from "@/components/Panel";
import { humanizeKind, relativeTime, shortHash } from "@/lib/format";
import { API_BASE } from "@/lib/steward";
import type { ApprovalView } from "@/lib/types";

type Action = "approve" | "reject";

export function ApprovalQueue({ approvals }: { approvals: ApprovalView[] }) {
  const router = useRouter();
  const [actor, setActor] = useState("maintainer");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function resolve(id: string, action: Action) {
    setBusy(`${id}:${action}`);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/approvals/${id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ by: actor.trim() || "maintainer" }),
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(detail?.detail ?? `Request failed (${res.status})`);
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Panel
      title="Approval Queue"
      caption="greylist actions · a human decides"
      accent="251, 191, 36"
      action={
        <label className="flex items-center gap-2">
          <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-slate-500">
            as
          </span>
          <input
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            className="w-28 rounded-md border border-white/10 bg-white/[0.03] px-2 py-1 font-mono text-xs text-slate-200 outline-none focus:border-amber-400/40"
            aria-label="Approver login"
          />
        </label>
      }
    >
      <div className="flex h-full flex-col">
        {error && (
          <div className="mx-4 mt-3 rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-2 font-mono text-[11px] text-rose-300">
            {error}
          </div>
        )}
        {approvals.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-12 text-center">
            <div className="text-2xl">✓</div>
            <p className="text-sm text-slate-300">Queue clear.</p>
            <p className="max-w-xs font-mono text-[11px] text-slate-600">
              No greylist actions are waiting. Steward never acts on these without an
              explicit human approval.
            </p>
          </div>
        ) : (
          <ul className="max-h-[34rem] space-y-3 overflow-y-auto p-4">
            <AnimatePresence initial={false}>
              {approvals.map((item) => {
                const pending = busy?.startsWith(item.approval_id);
                return (
                  <motion.li
                    key={item.approval_id}
                    layout
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.96 }}
                    transition={{ duration: 0.2 }}
                    className="rounded-xl border border-amber-400/20 bg-gradient-to-b from-amber-400/[0.06] to-transparent p-4"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs text-amber-200">
                        {humanizeKind(item.kind)}
                      </span>
                      <span className="font-mono text-[10px] text-slate-500">
                        expires {relativeTime(item.expires_at)}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-slate-100">{item.summary}</p>
                    <p className="mt-1 text-xs text-slate-400">{item.reason}</p>
                    <div className="mt-2 font-mono text-[10px] text-slate-600">
                      {item.repo} · trace {shortHash(item.trace_id)}
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        disabled={pending}
                        onClick={() => resolve(item.approval_id, "approve")}
                        className="flex-1 rounded-lg border border-emerald-400/30 bg-emerald-400/10 py-2 font-mono text-[11px] font-semibold uppercase tracking-wider text-emerald-200 transition hover:bg-emerald-400/20 disabled:opacity-40"
                      >
                        {busy === `${item.approval_id}:approve` ? "…" : "Approve"}
                      </button>
                      <button
                        type="button"
                        disabled={pending}
                        onClick={() => resolve(item.approval_id, "reject")}
                        className="flex-1 rounded-lg border border-rose-400/30 bg-rose-400/10 py-2 font-mono text-[11px] font-semibold uppercase tracking-wider text-rose-200 transition hover:bg-rose-400/20 disabled:opacity-40"
                      >
                        {busy === `${item.approval_id}:reject` ? "…" : "Reject"}
                      </button>
                    </div>
                  </motion.li>
                );
              })}
            </AnimatePresence>
          </ul>
        )}
      </div>
    </Panel>
  );
}
