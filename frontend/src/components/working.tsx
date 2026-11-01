"use client";

import { useEffect, useState } from "react";

/** Progress bar with a percentage and a line saying what Ritam is doing right now. */
export function Working({ percent, lines, title }: { percent: number; lines: string[]; title: string }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((n) => n + 1), 2600);
    return () => clearInterval(t);
  }, []);
  const pct = Math.max(1, Math.min(100, Math.round(percent)));
  return (
    <div className="rounded-lg border border-rule bg-white p-5 sm:p-6">
      <div className="flex items-baseline justify-between gap-4">
        <p className="text-lg font-semibold text-ink" role="status">
          {title}
        </p>
        <p className="text-2xl font-semibold tabular-nums text-ink">{pct}%</p>
      </div>
      <div
        className="mt-3 h-3 overflow-hidden rounded-full bg-paper"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={title}
      >
        <div className="h-full rounded-full bg-sourced transition-[width] duration-700 ease-out" style={{ width: `${pct}%` }} />
      </div>
      <p key={i} aria-hidden className="mt-3 text-[0.9375rem] text-mute motion-safe:animate-[fadein_400ms_ease-out]">
        {lines[i % lines.length]}
      </p>
    </div>
  );
}

/** Percentage that creeps towards `ceiling` while we wait on something without real progress events. */
export function useCreep(running: boolean, ceiling = 90, seconds = 20) {
  const [p, setP] = useState(0);
  useEffect(() => {
    if (!running) return;
    setP(3);
    const t = setInterval(() => setP((x) => x + (ceiling - x) * (1 / seconds)), 1000);
    return () => clearInterval(t);
  }, [running, ceiling, seconds]);
  return p;
}
