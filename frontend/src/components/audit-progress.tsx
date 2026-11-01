"use client";

import { Check, Loader2, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { SourceList } from "@/components/source-list";
import { Working } from "@/components/working";
import { API_URL, type SourceOut, type TraceStep } from "@/lib/api";
import { STEP_NAMES } from "@/lib/vocab";

interface Row {
  key: string;
  step: string;
  name: string;
  detail?: string;
  done: boolean;
  error?: string;
}

const STAGE_LINES: Record<string, string[]> = {
  plan: ["Reading your question", "Working out which card terms answer it"],
  fetch: ["Opening the bank's pages", "Downloading the card's terms", "Opening comparison sites"],
  extract: [
    "Reading the fine print line by line",
    "Matching every number to the sentence it came from",
    "Throwing out anything the document doesn't actually say",
  ],
  analyse: [
    "Comparing the bank's own documents with each other",
    "Checking if comparison sites show old figures",
    "Checking dates against RBI's one-month notice rule",
    "Looking for terms RBI expects that are missing",
  ],
  summary: ["Writing your report in plain words", "Ranking what you should check first"],
};

function percentOf(rows: Row[], finished: boolean): number {
  if (finished) return 100;
  const n = (step: string, done?: boolean) => rows.filter((r) => r.step === step && (done === undefined || r.done === done)).length;
  if (n("summary")) return 94;
  if (n("analyse")) return 88;
  const fetches = n("fetch");
  const extracts = n("extract");
  if (extracts) return 40 + 45 * (n("extract", true) / Math.max(extracts, fetches, 1));
  if (fetches) return 14 + 24 * (n("fetch", true) / fetches);
  if (n("plan", true)) return 12;
  return 4;
}

/** Live progress over server-sent events; calls onDone when the audit finishes. */
export function AuditProgress({ auditId, sources, onDone }: { auditId: string; sources: SourceOut[]; onDone: () => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [finished, setFinished] = useState(false);
  const best = useRef(0);

  useEffect(() => {
    const es = new EventSource(`${API_URL}/api/audits/${auditId}/events`);
    const label = (s: TraceStep) => {
      const extra = (s.title as string) || (s.url as string) || "";
      return { step: s.step, name: STEP_NAMES[s.step] ?? s.step, detail: extra ? extra.slice(0, 80) : undefined };
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
      setFinished(true);
      setTimeout(onDone, 600);
    };
    es.addEventListener("complete", finish);
    es.addEventListener("failed", finish);
    return () => es.close();
  }, [auditId, onDone]);

  best.current = Math.max(best.current, percentOf(rows, finished));
  const current = [...rows].reverse().find((r) => !r.done) ?? rows[rows.length - 1];
  const stage = current?.step ?? "plan";
  const host = (s: string) => {
    try {
      return new URL(s).hostname.replace(/^www\./, "");
    } catch {
      return s;
    }
  };
  const live =
    current?.detail && stage === "fetch"
      ? `Opening ${host(current.detail)}`
      : current?.detail && stage === "extract"
        ? `Reading ${current.detail}`
        : null;
  const lines = [
    ...(live ? [live] : []),
    ...(STAGE_LINES[stage] ?? STAGE_LINES.plan),
  ];

  return (
    <section aria-labelledby="progress-title" className="space-y-4">
      <h2 id="progress-title" className="sr-only">
        Checking your card
      </h2>
      <Working title={finished ? "Your report is ready" : "Checking your card"} percent={best.current} lines={lines} />
      <p className="text-sm text-ink/70">Usually about 2 minutes. Keep this page open; the report appears here by itself.</p>
      {sources.length > 0 && (
        <div className="rounded-lg border border-rule bg-white px-5 py-4">
          <h3 className="text-[0.9375rem] font-semibold text-ink">Ritam is reading these {sources.length} documents</h3>
          <SourceList sources={sources} />
        </div>
      )}
      <details className="rounded-lg border border-rule bg-white">
        <summary className="cursor-pointer px-5 py-3 text-[0.9375rem] font-medium text-ink">See each step</summary>
        <ol className="space-y-3 px-5 pb-5">
          {rows.length === 0 && (
            <li className="flex items-center gap-3 text-ink">
              <Loader2 aria-hidden className="size-4 animate-spin" /> Starting
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
      </details>
    </section>
  );
}
