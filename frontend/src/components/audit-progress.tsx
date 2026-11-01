"use client";

import { Check, Copy, Loader2, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { SourceList } from "@/components/source-list";
import { Working } from "@/components/working";
import { API_URL, type SourceOut, type TraceStep } from "@/lib/api";
import { sourceName } from "@/lib/vocab";

interface Row {
  key: string;
  step: string;
  done: boolean;
  data: Record<string, unknown>;
}

const PHASES = [
  { step: "plan", name: "Understand your question" },
  { step: "fetch", name: "Open the documents" },
  { step: "extract", name: "Read and verify facts" },
  { step: "analyse", name: "Compare and apply rules" },
  { step: "summary", name: "Write your report" },
] as const;

const STAGE_LINES: Record<string, string[]> = {
  plan: ["Reading your question", "Working out which charges and benefits answer it"],
  fetch: ["Opening the bank's pages and PDFs", "Opening comparison sites for the same card"],
  extract: [
    "Reading the fine print line by line",
    "Long terms PDFs are read in parts, so this step takes the longest",
    "Matching every number to the exact sentence it came from",
    "Throwing out anything the document doesn't actually say",
  ],
  analyse: [
    "Comparing the bank's documents with each other",
    "Checking if comparison sites show old figures",
    "Checking dates against RBI's one-month notice rule",
  ],
  summary: ["Writing your report in plain words", "Ranking what you should check first"],
};

const HOW: Record<string, string> = {
  httpx: "Downloaded directly",
  browser: "Read through a page renderer",
  jina: "Read through a page renderer",
  wayback: "Used an archived copy",
  snapshot: "Used a saved copy",
};

function counts(rows: Row[], step: string) {
  const all = rows.filter((r) => r.step === step);
  return { total: all.length, done: all.filter((r) => r.done).length };
}

/** Floor for the bar from finished steps, and the ceiling it may creep towards meanwhile. */
function bounds(rows: Row[], sources: number, finished: boolean): [number, number] {
  if (finished) return [100, 100];
  const fetch = counts(rows, "fetch");
  const extract = counts(rows, "extract");
  const total = Math.max(sources, fetch.total, extract.total, 1);
  if (counts(rows, "summary").total) return [94, 99];
  if (counts(rows, "analyse").total) return [88, 93];
  if (extract.total) {
    const floor = 40 + 45 * (extract.done / total);
    return [floor, Math.min(86, floor + 45 / total - 1)];
  }
  if (fetch.total) {
    const floor = 14 + 24 * (fetch.done / total);
    return [floor, Math.min(39, floor + 24 / total - 1)];
  }
  return counts(rows, "plan").done ? [12, 13] : [3, 11];
}

function estimateMinutes(sources: number) {
  return Math.min(6, Math.max(2, Math.round(1 + sources * 0.4)));
}

/** Live progress over server-sent events; calls onDone when the report is ready. */
export function AuditProgress({ auditId, sources, onDone }: { auditId: string; sources: SourceOut[]; onDone: () => void }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [finished, setFinished] = useState(false);
  const [percent, setPercent] = useState(3);
  const [copied, setCopied] = useState(false);
  const rowsRef = useRef<Row[]>([]);
  rowsRef.current = rows;
  const titles = new Map(sources.map((s) => [s.id, sourceName(s)]));

  useEffect(() => {
    const es = new EventSource(`${API_URL}/api/audits/${auditId}/events`);
    const keyOf = (s: TraceStep) => `${s.step}:${(s.source_id as string) ?? ""}`;
    es.addEventListener("snapshot", (e) => {
      const snap = JSON.parse((e as MessageEvent).data) as { status: string; trace: TraceStep[] };
      setRows(snap.trace.map((s) => ({ key: keyOf(s), step: s.step, done: true, data: s })));
      if (["complete", "partial", "failed"].includes(snap.status)) onDone();
    });
    es.addEventListener("step.started", (e) => {
      const s = JSON.parse((e as MessageEvent).data) as TraceStep;
      setRows((rs) => [...rs.filter((r) => r.key !== keyOf(s)), { key: keyOf(s), step: s.step, done: false, data: s }]);
    });
    es.addEventListener("step.done", (e) => {
      const s = JSON.parse((e as MessageEvent).data) as TraceStep;
      setRows((rs) => rs.map((r) => (r.key === keyOf(s) ? { ...r, done: true, data: { ...r.data, ...s } } : r)));
    });
    const finish = () => {
      es.close();
      setFinished(true);
      setTimeout(onDone, 700);
    };
    es.addEventListener("complete", finish);
    es.addEventListener("failed", finish);
    return () => es.close();
  }, [auditId, onDone]);

  // Never jumps back; creeps towards the next milestone so long reads don't look frozen.
  useEffect(() => {
    const t = setInterval(() => {
      const [floor, ceiling] = bounds(rowsRef.current, sources.length, finished);
      setPercent((p) => {
        const base = Math.max(p, floor);
        return base >= ceiling ? base : base + (ceiling - base) * 0.04;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [sources.length, finished]);

  const titleOf = (r: Row) => {
    const id = r.data.source_id as string | undefined;
    const t = (id && titles.get(id)) || (r.data.title as string) || (r.data.url as string) || "";
    return t.length > 90 ? `${t.slice(0, 88)}…` : t;
  };

  const describe = (r: Row): { text: string; detail?: string; problem?: string } => {
    const d = r.data;
    switch (r.step) {
      case "plan":
        return r.done
          ? { text: "Understood your question", detail: d.sub_questions ? `Split it into ${d.sub_questions} things to check` : undefined }
          : { text: "Understanding your question" };
      case "fetch":
        if (d.error && r.done) return { text: `Couldn't open ${titleOf(r)}`, problem: "Ritam carries on with the other documents." };
        return r.done ? { text: `Opened ${titleOf(r)}`, detail: HOW[(d.method as string) ?? ""] } : { text: `Opening ${titleOf(r)}` };
      case "extract": {
        if (d.error && r.done) return { text: `Couldn't read ${titleOf(r)}`, problem: "Ritam carries on with the other documents." };
        if (!r.done) return { text: `Reading ${titleOf(r)}`, detail: "Matching each fact to the exact sentence in the document" };
        const dropped = Object.values((d.dropped as Record<string, number>) ?? {}).reduce((a, b) => a + b, 0);
        const verified = (d.verified as number) ?? 0;
        return {
          text: `Read ${titleOf(r)}`,
          detail: `${verified} ${verified === 1 ? "fact" : "facts"} matched word-for-word${dropped ? `, ${dropped} thrown out` : ""}`,
        };
      }
      case "analyse":
        return r.done
          ? { text: "Compared all documents and applied the rules", detail: `${d.findings ?? 0} things worth checking found` }
          : { text: "Comparing documents and applying the rules" };
      case "summary":
        return r.done ? { text: "Wrote your report" } : { text: "Writing your report in plain words" };
      default:
        return { text: r.step };
    }
  };

  const current = [...rows].reverse().find((r) => !r.done) ?? rows[rows.length - 1];
  const stage = current?.step ?? "plan";
  const lines = [...(current ? [describe(current).text] : []), ...(STAGE_LINES[stage] ?? STAGE_LINES.plan)];
  const minutes = estimateMinutes(sources.length);
  const stageIndex = PHASES.findIndex((p) => p.step === stage);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section aria-labelledby="progress-title" className="space-y-5">
      <h2 id="progress-title" className="sr-only">
        Preparing your report
      </h2>
      <Working title={finished ? "Your report is ready" : "Reading your card's papers"} percent={percent} lines={lines} />

      <ol className="grid gap-2 sm:grid-cols-5" aria-label="Progress by stage">
        {PHASES.map((p, i) => {
          const st = finished || i < stageIndex ? "done" : i === stageIndex ? "now" : "todo";
          const c = counts(rows, p.step);
          const tally = (p.step === "fetch" || p.step === "extract") && sources.length ? ` (${c.done}/${sources.length})` : "";
          return (
            <li
              key={p.step}
              className={`flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm ${
                st === "now" ? "border-neon text-ink" : st === "done" ? "border-rule text-ink" : "border-rule text-mute"
              }`}
            >
              {st === "done" ? (
                <Check aria-label="Done" className="size-4 shrink-0 text-neon" />
              ) : st === "now" ? (
                <Loader2 aria-label="In progress" className="size-4 shrink-0 animate-spin text-neon" />
              ) : (
                <span aria-label="Not started" className="grid size-4 shrink-0 place-items-center text-xs">
                  {i + 1}
                </span>
              )}
              <span>
                {p.name}
                {tally}
              </span>
            </li>
          );
        })}
      </ol>

      <div className="rounded-lg border border-rule bg-surface p-5">
        <p className="text-[0.9375rem] font-semibold text-ink">Please bear with us.</p>
        <p className="mt-1 text-[0.9375rem] leading-relaxed text-ink/80">
          Ritam checks every fact against the bank&apos;s exact words, so it takes a little time. For{" "}
          {sources.length || "a few"} documents this can take up to {minutes} minutes. You can close this tab: Ritam keeps
          working, and your report will be waiting at this link.
        </p>
        <button
          type="button"
          onClick={copyLink}
          className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-md border border-ink/45 px-4 text-sm font-medium text-ink hover:border-neon"
        >
          {copied ? <Check aria-hidden className="size-4 text-neon" /> : <Copy aria-hidden className="size-4" />}
          {copied ? "Link copied" : "Copy the link to this report"}
        </button>
      </div>

      <details open className="rounded-lg border border-rule bg-surface">
        <summary className="cursor-pointer px-5 py-3 text-[0.9375rem] font-medium text-ink">What Ritam is doing, step by step</summary>
        <ol className="space-y-3 px-5 pb-5">
          {rows.length === 0 && (
            <li className="flex items-center gap-3 text-ink">
              <Loader2 aria-hidden className="size-4 animate-spin" /> Starting
            </li>
          )}
          {rows.map((r) => {
            const x = describe(r);
            return (
              <li key={r.key} className="flex items-start gap-3">
                {x.problem ? (
                  <TriangleAlert aria-label="Problem" className="mt-0.5 size-4 shrink-0 text-uncertain" />
                ) : r.done ? (
                  <Check aria-label="Done" className="mt-0.5 size-4 shrink-0 text-neon" />
                ) : (
                  <Loader2 aria-label="In progress" className="mt-0.5 size-4 shrink-0 animate-spin text-ink" />
                )}
                <span>
                  <span className="text-[0.9375rem] text-ink">{x.text}</span>
                  {x.detail && <span className="block text-sm text-mute">{x.detail}</span>}
                  {x.problem && <span className="block text-sm text-uncertain">{x.problem}</span>}
                </span>
              </li>
            );
          })}
        </ol>
      </details>

      {sources.length > 0 && (
        <details className="rounded-lg border border-rule bg-surface">
          <summary className="cursor-pointer px-5 py-3 text-[0.9375rem] font-medium text-ink">
            The {sources.length} documents Ritam is reading
          </summary>
          <div className="px-5 pb-4">
            <SourceList sources={sources} />
          </div>
        </details>
      )}
    </section>
  );
}
