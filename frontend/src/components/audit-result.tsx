"use client";

import { ChevronDown, ExternalLink, Mail, Phone, SearchCheck, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";

import { EvidenceSheet, type EvidenceTarget } from "@/components/evidence-sheet";
import { FindingCard } from "@/components/finding-card";
import { LabelTag } from "@/components/label-tag";
import { ReportCard } from "@/components/report-card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { AuditOut, ChecklistOut, Label } from "@/lib/api";
import { ACTIONS, formatDate, LABELS, sourceName, STEP_NAMES } from "@/lib/vocab";

const CITE = /\s*\[[a-z_]+:[^\]]+\]/g;

const sentences = (text: string) =>
  text
    .replace(/([.!?])\s+(?=[A-Z])/g, "$1\n")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);

export function AuditResult({ audit }: { audit: AuditOut }) {
  const [filter, setFilter] = useState<Label | "all">("all");
  const [target, setTarget] = useState<EvidenceTarget | null>(null);

  const counts = useMemo(() => {
    const c: Record<Label, number> = { sourced: 0, ai_suggestion: 0, uncertain: 0 };
    audit.findings.forEach((f) => (c[f.label] += 1));
    return c;
  }, [audit.findings]);
  const shown = filter === "all" ? audit.findings : audit.findings.filter((f) => f.label === filter);
  const failedSources = audit.sources.filter((s) => s.status === "failed");

  return (
    <div className="space-y-10">
      <header>
        {audit.product_name && <p className="text-[0.9375rem] font-medium text-mute">{audit.product_name}</p>}
        <h1 className="mt-1 max-w-3xl text-[1.75rem] font-semibold leading-tight tracking-tight text-ink sm:text-[2.125rem]">
          {audit.question}
        </h1>
        <p className="mt-3 text-sm text-mute">
          {audit.sources.length} sources checked, {audit.stats.claims_verified ?? 0} statements verified against their
          documents{audit.finished_at ? `, ${formatDate(audit.finished_at)}` : ""}.
        </p>
        {audit.status === "partial" && (
          <p role="status" className="mt-4 flex items-start gap-2 rounded-md border border-uncertain bg-uncertain-soft px-4 py-3 text-[0.9375rem] text-ink">
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-uncertain" />
            {failedSources.length} of {audit.sources.length} sources couldn&apos;t be read, so these results are incomplete.
            Upload those documents as PDFs to include them.
          </p>
        )}
        {audit.status === "failed" && (
          <p role="alert" className="mt-4 rounded-md border border-destructive px-4 py-3 text-[0.9375rem] text-destructive">
            This audit didn&apos;t finish. {audit.stats.error ?? "Please run it again."}
          </p>
        )}
      </header>

      <ReportCard
        audit={audit}
        onOpen={setTarget}
        onFilter={(l) => {
          setFilter(l);
          document.getElementById("findings-title")?.scrollIntoView({ behavior: "smooth", block: "start" });
        }}
      />

      <section aria-labelledby="overview-title" className="grid gap-6 lg:grid-cols-[1.25fr_1fr]">
        <h2 id="overview-title" className="sr-only">
          Overview
        </h2>
        {audit.summary && (
          <div className="rounded-lg border border-rule bg-white p-5 sm:p-6">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <LabelTag label="ai_suggestion" />
              <span className="text-sm text-ink/70">In plain words, written by AI from the findings</span>
            </div>
            <ul className="list-disc space-y-2 pl-5 text-[1.0625rem] leading-relaxed text-ink">
              {sentences(audit.summary.text.replace(CITE, "")).map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
        )}
        <CoverageScore audit={audit} />
      </section>

      <div className="grid items-start gap-8 lg:grid-cols-[1fr_22rem]">
        <section aria-labelledby="findings-title">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <h2 id="findings-title" className="scroll-mt-6 text-xl font-semibold tracking-tight text-ink">
              What Ritam found ({audit.findings.length})
            </h2>
            <div role="group" aria-label="Filter findings by label" className="flex flex-wrap gap-1.5">
              <FilterChip active={filter === "all"} onClick={() => setFilter("all")}>
                All {audit.findings.length}
              </FilterChip>
              {(Object.keys(counts) as Label[])
                .filter((l) => counts[l] > 0)
                .map((l) => (
                  <FilterChip key={l} active={filter === l} onClick={() => setFilter(l)}>
                    {LABELS[l].name} {counts[l]}
                  </FilterChip>
                ))}
            </div>
          </div>
          {shown.length === 0 ? (
            <p className="rounded-lg border border-rule bg-white p-5 text-ink">
              {audit.findings.length === 0
                ? "No gaps, conflicts or outdated information were found in these sources. That only covers what was checked; the bank's latest MITC is still the final word."
                : "No findings with this label."}
            </p>
          ) : (
            <div className="space-y-3">
              {shown.map((f) => (
                <FindingCard key={f.id} finding={f} onOpen={setTarget} />
              ))}
            </div>
          )}
        </section>

        <div className="order-first lg:order-none">
          <Checklist items={audit.checklist} />
        </div>
      </div>

      <section aria-label="Details" className="space-y-3">
        <Details title="Everything Ritam read, by card feature" defaultOpen={false}>
          <CoverageTable audit={audit} onOpen={setTarget} />
        </Details>
        <Details title="How Ritam checked this">
          <Trace audit={audit} />
        </Details>
      </section>

      <EvidenceSheet target={target} onClose={() => setTarget(null)} />
    </div>
  );
}

function FilterChip({
  active,
  children,
  ...rest
}: { active: boolean; children: React.ReactNode } & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={`min-h-11 rounded-full border px-4 text-sm disabled:opacity-40 ${
        active ? "border-ink bg-ink text-white" : "border-rule bg-white text-ink hover:border-ink"
      }`}
      {...rest}
    >
      {children}
    </button>
  );
}

const SEGMENTS = [
  { key: "official", name: "Confirmed officially", cls: "bg-sourced" },
  { key: "third_party", name: "Only on other sites", cls: "bg-ai" },
  { key: "conflict", name: "Sources disagree", cls: "bg-uncertain" },
  { key: "missing", name: "Not found", cls: "bg-rule" },
] as const;

function CoverageScore({ audit }: { audit: AuditOut }) {
  const c = audit.coverage;
  if (!c.total) return null;
  return (
    <div className="rounded-lg border border-rule bg-white p-5 sm:p-6">
      <h3 className="text-[0.9375rem] font-medium text-mute">How complete is this card&apos;s information?</h3>
      <p className="mt-2 text-ink">
        <span className="text-[2rem] font-semibold leading-none tracking-tight">{c.official}</span>
        <span className="text-lg"> of {c.total} key terms confirmed by the bank</span>
      </p>
      <div
        className="mt-4 flex h-3 overflow-hidden rounded-full bg-paper"
        role="img"
        aria-label={SEGMENTS.map((s) => `${c[s.key]} ${s.name.toLowerCase()}`).join(", ")}
      >
        {SEGMENTS.map((s) =>
          c[s.key] ? <span key={s.key} className={`${s.cls} h-full`} style={{ width: `${(c[s.key] / c.total) * 100}%` }} /> : null,
        )}
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
        {SEGMENTS.map((s) => (
          <div key={s.key} className="flex items-center gap-2">
            <span aria-hidden className={`size-2.5 rounded-full ${s.cls}`} />
            <dt className="text-ink/80">{s.name}</dt>
            <dd className="ml-auto font-medium text-ink">{c[s.key]}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

const ACTION_ICONS = { check_page: SearchCheck, call_bank: Phone, grievance: Mail, ombudsman: Mail } as const;

function Checklist({ items }: { items: ChecklistOut[] }) {
  if (!items.length) return null;
  return (
    <aside aria-labelledby="checklist-title" className="rounded-lg border border-ink bg-white p-5 lg:sticky lg:top-6">
      <h2 id="checklist-title" className="text-lg font-semibold text-ink">
        Verify next
      </h2>
      <p className="mt-1 text-sm text-mute">Most important first.</p>
      <ol className="mt-4 space-y-4">
        {items.map((c) => {
          const Icon = ACTION_ICONS[c.action];
          return (
            <li key={c.rank} className="grid grid-cols-[1.75rem_1fr] gap-x-2">
              <span className="pt-0.5 text-sm font-semibold text-mute">{c.rank}.</span>
              <div>
                <p className="text-[0.9375rem] leading-snug text-ink">{c.text}</p>
                <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-mute">
                  <span className="inline-flex items-center gap-1">
                    <Icon aria-hidden className="size-3.5" /> {ACTIONS[c.action]}
                  </span>
                  {c.verify_url && (
                    <a href={c.verify_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-4">
                      Bank page <ExternalLink aria-hidden className="size-3" />
                      <span className="sr-only">(opens in a new tab)</span>
                    </a>
                  )}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </aside>
  );
}

function Details({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="rounded-lg border border-rule bg-white">
      <CollapsibleTrigger className="flex w-full items-center justify-between px-5 py-4 text-left text-[1.0625rem] font-semibold text-ink hover:bg-paper">
        {title}
        <ChevronDown aria-hidden className={`size-5 transition-transform ${open ? "rotate-180" : ""}`} />
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t border-rule px-5 py-5">{children}</CollapsibleContent>
    </Collapsible>
  );
}

const STATUS_TEXT: Record<string, string> = {
  official: "Confirmed officially",
  third_party: "Only on other sites",
  conflict: "Sources disagree",
  missing: "Not found",
};

function CoverageTable({ audit, onOpen }: { audit: AuditOut; onOpen: (t: EvidenceTarget) => void }) {
  const sources = audit.sources.filter((s) => audit.matrix.some((r) => r.cells[s.id]));
  if (!audit.matrix.length) return <p className="text-mute">No card features were extracted.</p>;
  return (
    <div className="-mx-5 overflow-x-auto px-5">
      <table className="w-full min-w-[40rem] border-collapse text-sm">
        <caption className="sr-only">Values found for each card feature in each source</caption>
        <thead>
          <tr className="border-b border-rule text-left align-bottom">
            <th scope="col" className="py-2 pr-4 font-medium text-mute">Feature</th>
            <th scope="col" className="py-2 pr-4 font-medium text-mute">Status</th>
            {sources.map((s) => (
              <th key={s.id} scope="col" className="max-w-[12rem] py-2 pr-4 font-medium text-mute">
                <span className="line-clamp-2">{sourceName(s)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {audit.matrix.map((r) => (
            <tr key={r.attribute} className="border-b border-rule align-top">
              <th scope="row" className="py-3 pr-4 text-left font-medium text-ink">{r.label}</th>
              <td className="py-3 pr-4 text-ink/80">{STATUS_TEXT[audit.coverage.by_attribute[r.attribute]] ?? "—"}</td>
              {sources.map((s) => (
                <td key={s.id} className="py-3 pr-4">
                  {(r.cells[s.id] ?? []).slice(0, 3).map((c) => (
                    <button
                      key={c.claim_id}
                      type="button"
                      onClick={() => onOpen({ sourceId: s.id, claimId: c.claim_id })}
                      className="mb-1 block text-left text-ink underline decoration-rule underline-offset-4 hover:decoration-ink"
                      title={c.quote}
                    >
                      {c.value}
                    </button>
                  ))}
                  {!r.cells[s.id] && <span className="text-mute">—</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Trace({ audit }: { audit: AuditOut }) {
  const steps = audit.stats.trace ?? [];
  const totalMs = steps.reduce((n, s) => n + (s.ms ?? 0), 0);
  return (
    <div>
      <p className="mb-4 max-w-prose text-[0.9375rem] text-ink/80">
        Every step, how long it took and which AI model read each source. Statements whose quote couldn&apos;t be found in
        the document, or whose numbers didn&apos;t match, were dropped.
      </p>
      <ol className="space-y-2 text-sm">
        {steps.map((s, i) => {
          const dropped = s.dropped as Record<string, number> | undefined;
          const droppedN = dropped ? Object.values(dropped).reduce((a, b) => a + b, 0) : 0;
          const models = s.models as Record<string, number> | undefined;
          return (
            <li key={i} className="grid grid-cols-[1fr_auto] gap-4 border-b border-rule pb-2">
              <span className="text-ink">
                {STEP_NAMES[s.step] ?? s.step}
                {s.title ? <span className="text-mute">: {String(s.title).slice(0, 70)}</span> : null}
                {typeof s.verified === "number" && (
                  <span className="block text-mute">
                    {s.verified} statements verified{droppedN ? `, ${droppedN} dropped` : ""}
                    {models ? ` · read by ${Object.keys(models).join(", ")}` : ""}
                  </span>
                )}
                {s.planner ? <span className="block text-mute">Planned by {String(s.planner)}</span> : null}
                {s.generated_by ? <span className="block text-mute">Written by {String(s.generated_by)}</span> : null}
                {s.error ? <span className="block text-uncertain">Problem: {String(s.error).slice(0, 140)}</span> : null}
              </span>
              <span className="tabular-nums text-mute">{((s.ms ?? 0) / 1000).toFixed(1)} s</span>
            </li>
          );
        })}
      </ol>
      {totalMs > 0 && <p className="mt-3 text-sm text-mute">Total {Math.round(totalMs / 1000)} seconds.</p>}
    </div>
  );
}
