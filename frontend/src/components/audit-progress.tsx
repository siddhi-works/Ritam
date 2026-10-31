"use client";

import { Check, Loader2, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";

import { API_URL, type TraceStep } from "@/lib/api";
import { STEP_NAMES } from "@/lib/vocab";

interface Row {
  key: string;
  name: string;
  detail?: string;
  done: boolean;
  error?: string;
}

/** Live progress over server-sent events; calls onDone when the audit finishes. */
export function AuditProgress({ auditId, onDone }: { auditId: string; onDone: () => void }) {
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    const es = new EventSource(`${API_URL}/api/audits/${auditId}/events`);
    const label = (s: TraceStep) => {
      const extra = (s.title as string) || (s.url as string) || "";
      return { name: STEP_NAMES[s.step] ?? s.step, detail: extra ? extra.slice(0, 80) : undefined };
    };
    const keyOf = (s: TraceStep) => `${s.step}:${(s.source_id as string) ?? ""}`;
    es.addEventListener("snapshot", (e) => {
      const snap = JSON.parse((e as MessageEvent).data) as { status: string; trace: TraceStep[] };
      setRows(snap.trace.map((s) => ({ key: keyOf(s), ...label(s), done: true, error: s.error as string | undefined })));
      if (["complete", "partial", "failed"].includes(snap.status)) onDone();
    });
    es.addEventListener("step.started", (e) => {
      const s = JSON.parse((e as MessageEvent).data) as TraceStep;
      setRows((rs) => [...rs.filter((r) => r.key !== keyOf(s)), { key: keyOf(s), ...label(s), done: false }]);
    });
    es.addEventListener("step.done", (e) => {
      const s = JSON.parse((e as MessageEvent).data) as TraceStep;
      setRows((rs) => rs.map((r) => (r.key === keyOf(s) ? { ...r, done: true, error: (s.error as string) || undefined } : r)));
    });
    const finish = () => {
      es.close();
      onDone();
    };
    es.addEventListener("complete", finish);
    es.addEventListener("failed", finish);
    return () => es.close();
  }, [auditId, onDone]);

  return (
    <section aria-labelledby="progress-title" className="rounded-lg border border-rule bg-white p-5 sm:p-6">
      <h2 id="progress-title" className="text-lg font-semibold text-ink">
        Checking your sources
      </h2>
      <p className="mt-1 text-sm text-mute">Usually about 2 minutes. You can leave this page open.</p>
      <ol className="mt-5 space-y-3" aria-live="polite">
        {rows.length === 0 && (
          <li className="flex items-center gap-3 text-ink">
            <Loader2 aria-hidden className="size-4 animate-spin" /> Starting…
          </li>
        )}
        {rows.map((r) => (
          <li key={r.key} className="flex items-start gap-3">
            {r.error ? (
              <TriangleAlert aria-label="Problem" className="mt-0.5 size-4 shrink-0 text-uncertain" />
            ) : r.done ? (
              <Check aria-label="Done" className="mt-0.5 size-4 shrink-0 text-sourced" />
            ) : (
              <Loader2 aria-label="In progress" className="mt-0.5 size-4 shrink-0 animate-spin text-ink" />
            )}
            <span>
              <span className="text-[0.9375rem] text-ink">{r.name}</span>
              {r.detail && <span className="block text-sm text-mute">{r.detail}</span>}
              {r.error && <span className="block text-sm text-uncertain">Skipped: {r.error.slice(0, 120)}</span>}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
