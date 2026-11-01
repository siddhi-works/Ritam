"use client";

import { ChevronDown, FileSearch } from "lucide-react";
import { useState } from "react";

import type { EvidenceTarget } from "@/components/evidence-sheet";
import { LabelTag } from "@/components/label-tag";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import type { Evidence, FindingOut } from "@/lib/api";
import { formatDate, MEANS, TYPE_NAMES } from "@/lib/vocab";

interface Item {
  heading?: string;
  ev?: Evidence;
  note?: string;
  target?: EvidenceTarget;
}

/** Normalise the different detail shapes each rule produces into one evidence list. */
function evidenceItems(f: FindingOut): Item[] {
  const d = f.detail as Record<string, unknown>;
  const asEv = (x: unknown) => (Array.isArray(x) ? (x as Evidence[]) : []);
  const items: Item[] = [];
  const push = (heading: string | undefined, list: Evidence[]) =>
    list.forEach((ev) => items.push({ heading, ev, target: { sourceId: ev.source_id, claimId: ev.claim_id } }));

  if (f.type === "chat_mismatch") {
    if (d.told) push("What you were told", [d.told as Evidence]);
    push("What the terms said then", asEv(d.terms_valid_then));
  } else if (d.stale || d.current) {
    push("Outdated source says", asEv(d.stale));
    push("Official current terms say", asEv(d.current));
  } else if (d.evidence) {
    push(undefined, asEv(d.evidence));
  }
  const mentions = (d.mentions as { source_id: string; page_no: number; snippet: string }[] | undefined) ?? [];
  mentions.forEach((m) =>
    items.push({ heading: "Mentioned here, but no clear value", note: `…${m.snippet}…`, target: { sourceId: m.source_id, pageNo: m.page_no } }),
  );
  if (d.redirected_to)
    items.push({ note: `The link ${String(d.requested_url)} now opens ${String(d.redirected_to)}.`, target: f.source_ids[0] ? { sourceId: f.source_ids[0] } : undefined });
  if (Array.isArray(d.reasons)) items.push({ note: (d.reasons as string[]).join(" ") });
  if (d.searched_keywords && !mentions.length)
    items.push({ note: `Ritam searched every page for: ${(d.searched_keywords as string[]).join(", ")}. Nothing matched.` });
  if (f.type === "undated" && f.source_ids[0]) items.push({ note: "Open the document to look for a date yourself.", target: { sourceId: f.source_ids[0] } });
  return items;
}

export function FindingCard({ finding, onOpen }: { finding: FindingOut; onOpen: (t: EvidenceTarget) => void }) {
  const [open, setOpen] = useState(false);
  const items = evidenceItems(finding);
  const titleId = `f-${finding.id}`;
  let lastHeading: string | undefined;

  return (
    <article aria-labelledby={titleId} className="rounded-lg border border-rule bg-surface">
      <div className="p-4 sm:p-5">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <LabelTag label={finding.label} />
          <span className="text-sm text-mute">{TYPE_NAMES[finding.type] ?? finding.type}</span>
        </div>
        <h3 id={titleId} className="text-[1.0625rem] font-semibold leading-snug text-ink">
          {finding.title}
        </h3>
        {MEANS[finding.type] && <p className="mt-1.5 text-[0.9375rem] text-ink/75">{MEANS[finding.type]}</p>}
      </div>

      {items.length > 0 && (
        <Collapsible open={open} onOpenChange={setOpen}>
          <CollapsibleTrigger className="flex w-full items-center justify-between border-t border-rule px-4 py-3 text-left text-sm font-medium text-ink hover:bg-white/5 sm:px-5">
            {open ? "Hide the evidence" : `Show the evidence (${items.length})`}
            <ChevronDown aria-hidden className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className="space-y-4 border-t border-rule px-4 py-4 sm:px-5">
              {items.map((it, i) => {
                const showHeading = it.heading && it.heading !== lastHeading;
                lastHeading = it.heading;
                return (
                  <li key={i}>
                    {showHeading && <p className="mb-1.5 text-sm font-medium text-ink">{it.heading}</p>}
                    {it.ev && (
                      <>
                        <p className="text-[0.8125rem] text-mute">
                          {it.ev.source}
                          {it.ev.page_no ? `, page ${it.ev.page_no}` : ""}
                          {it.ev.valid_from ? `, effective ${formatDate(it.ev.valid_from)}` : ""}
                          {it.ev.conditions ? `, ${it.ev.conditions}` : ""}
                        </p>
                        <blockquote className="mt-1 font-serif text-[0.9375rem] leading-relaxed">
                          <mark className="mark-verified">“{it.ev.quote}”</mark>
                        </blockquote>
                      </>
                    )}
                    {it.note && <p className="mt-1 text-[0.9375rem] text-ink/80">{it.note}</p>}
                    {it.target && (
                      <button
                        type="button"
                        onClick={() => onOpen(it.target!)}
                        className="mt-1.5 inline-flex min-h-9 items-center gap-1.5 text-sm font-medium text-ink underline underline-offset-4"
                      >
                        <FileSearch aria-hidden className="size-4" /> See it in the document
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      )}
    </article>
  );
}
