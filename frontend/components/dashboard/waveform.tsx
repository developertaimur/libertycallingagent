"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

export function Waveform({ active }: { active: boolean }) {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 120);
    return () => window.clearInterval(id);
  }, [active]);

  const bars = Array.from({ length: 48 }, (_, i) => {
    if (!active) return 18;
    const h =
      12 +
      Math.abs(Math.sin((tick + i) * 0.45)) * 28 +
      Math.abs(Math.cos((tick + i) * 0.22)) * 18;
    return Math.min(56, h);
  });

  return (
    <div
      className={cn(
        "flex h-16 items-end justify-center gap-[3px] rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2",
        active && "ring-1 ring-cyan-500/20",
      )}
      aria-hidden
    >
      {bars.map((h, i) => (
        <span
          key={i}
          className="w-[3px] rounded-full transition-[height] duration-100"
          style={{
            height: `${h}%`,
            background:
              i % 5 === 0
                ? "rgb(244 63 94 / 0.85)"
                : "rgb(34 211 238 / 0.85)",
          }}
        />
      ))}
    </div>
  );
}
