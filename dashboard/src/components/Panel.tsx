import type { ReactNode } from "react";

export function Panel({
  title,
  caption,
  accent,
  action,
  children,
}: {
  title: string;
  caption: string;
  accent: string; // rgb triplet
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="glass flex h-full flex-col overflow-hidden rounded-2xl">
      <div className="hairline flex items-center justify-between gap-3 px-5 py-4">
        <div className="flex items-center gap-3">
          <span
            className="h-7 w-1 rounded-full"
            style={{ background: `rgb(${accent})`, boxShadow: `0 0 14px rgb(${accent})` }}
            aria-hidden
          />
          <div>
            <h2 className="font-display text-sm font-semibold tracking-wide text-slate-100">
              {title}
            </h2>
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-slate-500">
              {caption}
            </p>
          </div>
        </div>
        {action}
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </section>
  );
}
