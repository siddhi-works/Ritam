"use client";

import { useEffect, useState } from "react";

import { API_URL } from "@/lib/api";

/**
 * The free API host sleeps after 15 idle minutes and takes about a minute to wake.
 * Instead of an error, explain what's happening and keep trying.
 */
export function useServerAwake(): "checking" | "waking" | "ready" | "down" {
  const [state, setState] = useState<"checking" | "waking" | "ready" | "down">("checking");
  useEffect(() => {
    let cancelled = false;
    const started = Date.now();
    async function ping() {
      while (!cancelled) {
        try {
          const ctrl = new AbortController();
          const t = setTimeout(() => ctrl.abort(), 8000);
          const r = await fetch(`${API_URL}/livez`, { cache: "no-store", signal: ctrl.signal });
          clearTimeout(t);
          if (r.ok) {
            if (!cancelled) setState("ready");
            return;
          }
        } catch {
          /* still waking */
        }
        if (cancelled) return;
        setState(Date.now() - started > 150_000 ? "down" : "waking");
        await new Promise((res) => setTimeout(res, 4000));
      }
    }
    ping();
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}

export function ServerNotice({ state }: { state: ReturnType<typeof useServerAwake> }) {
  if (state === "ready" || state === "checking") return null;
  return (
    <p role="status" className="rounded-md border border-rule bg-surface px-4 py-3 text-sm text-ink">
      {state === "waking"
        ? "Waking Ritam's free server. This takes about a minute the first time; your page will work as soon as it's up."
        : "Ritam's server isn't answering. Please try again in a few minutes."}
    </p>
  );
}
