import { VERDICT_META } from "@/lib/format";
import type { PolicyVerdict } from "@/lib/types";

export function VerdictBadge({ verdict }: { verdict: PolicyVerdict }) {
  const meta = VERDICT_META[verdict];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border ${meta.border} ${meta.text} px-2.5 py-0.5 font-mono text-[10px] font-semibold tracking-[0.18em]`}
      style={{
        background: `linear-gradient(180deg, rgba(${meta.rgb}, 0.16), rgba(${meta.rgb}, 0.04))`,
        boxShadow: `0 0 18px -8px rgba(${meta.rgb}, 0.8)`,
      }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: `rgb(${meta.rgb})`, boxShadow: `0 0 8px rgb(${meta.rgb})` }}
      />
      {meta.label}
    </span>
  );
}
