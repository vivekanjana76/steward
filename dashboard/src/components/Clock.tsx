"use client";

import { useEffect, useState } from "react";

// A live UTC clock. Rendered client-side only (after mount) to avoid a
// server/client hydration mismatch on the changing time string.
export function Clock() {
  const [now, setNow] = useState<string | null>(null);

  useEffect(() => {
    const tick = () =>
      setNow(
        new Date().toLocaleTimeString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          timeZone: "UTC",
        }),
      );
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <span className="font-mono text-xs tabular-nums text-slate-400">
      {now ?? "--:--:--"} <span className="text-slate-600">UTC</span>
    </span>
  );
}
