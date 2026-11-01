"use client";

import { CircleCheck, CircleHelp, TriangleAlert } from "lucide-react";

import type { EvidenceTarget } from "@/components/evidence-sheet";
import { SourceList } from "@/components/source-list";
import type { AuditOut, Label } from "@/lib/api";
import { formatDate } from "@/lib/vocab";

const STATUS: Record<string, { text: string; cls: string }> = {
  official: { text: "Confirmed by the bank", cls: "text-sourced" },
  third_party: { text: "Only on other websites", cls: "text-ai" },
  conflict: { text: "Sources disagree", cls: "text-uncertain" },
  missing: { text: "Not found", cls: "text-mute" },
};

function verdict(toCheck: number, unclear: number): string {
  if (toCheck > 0) return `${toCheck} ${toCheck === 1 ? "thing needs" : "things need"} checking before you rely on this card's information.`;
  if (unclear > 0) return `Nothing clearly wrong. ${unclear} ${unclear === 1 ? "point needs" : "points need"} a closer look.`;
  return "No problems found in the documents Ritam read.";
}

/** Top of the report: one plain sentence, three tiles and the card's key facts. */
export function ReportCard({
  audit,
  onFilter,
  onOpen,
}: {
  audit: AuditOut;
  onFilter: (label: Label) => void;
  onOpen: (t: EvidenceTarget) => void;
}) {
  const toCheck = audit.findings.filter((f) => f.label === "sourced").length;
  const unclear = audit.findings.filter((f) => f.label === "uncertain").length;
  const c = audit.coverage;
  const bySource = new Map(audit.sources.map((s) => [s.id, s]));
  // Most authoritative source first; among equals, the newest dated value (old brochures lose).
  const rank = (sid: string, validFrom: string | null) => {
    const s = bySource.get(sid);
    const date = validFrom || s?.effective_from || s?.published_at || "";
    return [s?.authority_tier ?? 9, date] as const;
  };

  const facts = audit.matrix.slice(0, 10).map((row) => {
    const cells = Object.entries(row.cells).flatMap(([sid, list]) => list.map((cell) => ({ sid, cell })));
    cells.sort((a, b) => {
      const [ta, da] = rank(a.sid, a.cell.valid_from);
      const [tb, db] = rank(b.sid, b.cell.valid_from);
      return ta - tb || db.localeCompare(da);
    });
    const more = cells[0] ? cells.filter((x) => x.sid === cells[0].sid).length - 1 : 0;
    return { row, best: cells[0], more, status: STATUS[c.by_attribute[row.attribute]] ?? STATUS.missing };
  });

  // What the bank's own change notice says, shown first when one was read.
  const noticeIds = new Set(audit.sources.filter((s) => s.kind === "bank_notice").map((s) => s.id));
  const changes = audit.matrix.flatMap((row) =>
    Object.entries(row.cells)
      .filter(([sid]) => noticeIds.has(sid))
      .flatMap(([sid, list]) => list.map((cell) => ({ row, sid, cell }))),
  );

  const tiles = [
    { label: "sourced" as Label, n: toCheck, name: "To check", hint: "Backed by the documents", icon: TriangleAlert, cls: "border-uncertain text-uncertain" },
    { label: "uncertain" as Label, n: unclear, name: "Take a closer look", hint: "Unclear or mixed evidence", icon: CircleHelp, cls: "border-rule text-ink/80" },
  ];

  return (
    <section aria-labelledby="answer-title" className="space-y-6">
      <div className="rounded-lg border border-ink bg-white p-5 sm:p-7">
        <h2 id="answer-title" className="text-sm font-medium text-ink/70">
          The short answer
        </h2>
        <p className="mt-2 text-[1.375rem] font-semibold leading-snug text-ink sm:text-[1.625rem]">{verdict(toCheck, unclear)}</p>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          {tiles.map((t) => (
            <button
              key={t.name}
              type="button"
              onClick={() => onFilter(t.label)}
              disabled={t.n === 0}
              className={`flex min-h-20 items-center gap-3 rounded-lg border-2 bg-white px-4 py-3 text-left hover:bg-paper disabled:opacity-60 ${t.cls}`}
            >
              <t.icon aria-hidden className="size-6 shrink-0" />
              <span>
                <span className="block text-2xl font-semibold leading-none tabular-nums">{t.n}</span>
                <span className="mt-1 block text-[0.9375rem] font-medium text-ink">{t.name}</span>
                <span className="block text-[0.8125rem] text-ink/70">{t.hint}</span>
              </span>
            </button>
          ))}
          <div className="flex min-h-20 items-center gap-3 rounded-lg border-2 border-sourced bg-white px-4 py-3 text-sourced">
            <CircleCheck aria-hidden className="size-6 shrink-0" />
            <span>
              <span className="block text-2xl font-semibold leading-none tabular-nums">
                {c.official}
                <span className="text-base font-medium text-ink/70"> of {c.total}</span>
              </span>
              <span className="mt-1 block text-[0.9375rem] font-medium text-ink">Confirmed by the bank</span>
              <span className="block text-[0.8125rem] text-ink/70">Key terms with an official quote</span>
            </span>
          </div>
        </div>
      </div>

      {changes.length > 0 && (
        <div className="rounded-lg border border-uncertain bg-white p-5 sm:p-6">
          <h2 className="text-lg font-semibold text-ink">What the bank&apos;s notice says is changing</h2>
          <p className="mt-1 text-sm text-ink/70">From the bank&apos;s own notice. Tap a line to see it in the document.</p>
          <ul className="mt-3 divide-y divide-rule">
            {changes.slice(0, 8).map(({ row, sid, cell }) => (
              <li key={cell.claim_id} className="py-2.5">
                <button
                  type="button"
                  onClick={() => onOpen({ sourceId: sid, claimId: cell.claim_id })}
                  className="text-left text-[0.9375rem] text-ink hover:underline"
                >
                  <span className="font-medium">{row.label}:</span> {cell.value}
                  {cell.valid_from && <span className="text-ink/70"> from {formatDate(cell.valid_from)}</span>}
                </button>
                {cell.conditions && <span className="block text-sm text-ink/70">{cell.conditions}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {facts.length > 0 && (
        <div className="rounded-lg border border-rule bg-white p-5 sm:p-6">
          <h2 className="text-lg font-semibold text-ink">Key facts about this card</h2>
          <p className="mt-1 text-sm text-ink/70">
            Official figures first. Tap a figure to see the exact line in the document.
          </p>
          <dl className="mt-4 grid gap-x-8 sm:grid-cols-2">
            {facts.map(({ row, best, more, status }) => (
              <div key={row.attribute} className="border-t border-rule py-3">
                <dt className="text-sm text-ink/70">{row.label}</dt>
                <dd className="mt-0.5">
                  {best ? (
                    <button
                      type="button"
                      onClick={() => onOpen({ sourceId: best.sid, claimId: best.cell.claim_id })}
                      className="text-left text-[1.0625rem] font-medium text-ink underline decoration-rule decoration-2 underline-offset-4 hover:decoration-ink"
                    >
                      {best.cell.value}
                    </button>
                  ) : (
                    <span className="text-[1.0625rem] text-mute">Not found in the documents read</span>
                  )}
                  {best?.cell.conditions && <span className="block text-sm text-ink/70">{best.cell.conditions}</span>}
                  {more > 0 && (
                    <span className="block text-sm text-ink/70">
                      +{more} more {more === 1 ? "value" : "values"} for other cases. Tap to see all.
                    </span>
                  )}
                  <span className={`mt-0.5 block text-xs font-medium ${status.cls}`}>{status.text}</span>
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div className="rounded-lg border border-rule bg-white p-5 sm:p-6">
        <h2 className="text-lg font-semibold text-ink">Documents Ritam read ({audit.sources.length})</h2>
        <p className="mt-1 text-sm text-ink/70">Official documents first. Tap one to read it with the checked lines highlighted.</p>
        <SourceList sources={audit.sources} onOpen={(sourceId) => onOpen({ sourceId })} />
      </div>
    </section>
  );
}
