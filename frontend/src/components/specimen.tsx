"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { LabelTag } from "@/components/label-tag";
import { useServerAwake } from "@/components/server-gate";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet, type Evidence, type FindingOut } from "@/lib/api";
import { formatDate } from "@/lib/vocab";

interface Pair {
  auditId: string;
  finding: FindingOut;
  told: Evidence;
  terms: Evidence;
}

/** Hero example: a real finding from a stored demo audit. */
export function Specimen() {
  const [pair, setPair] = useState<Pair | null>(null);
  const [failed, setFailed] = useState(false);
  const server = useServerAwake();

  useEffect(() => {
    if (server !== "ready") return;
    let cancelled = false;
    apiGet<{ audit_id: string; finding: FindingOut; told: Evidence; terms: Evidence } | null>("/api/audits/highlight")
      .then((h) => {
        if (cancelled) return;
        if (h) setPair({ auditId: h.audit_id, finding: h.finding, told: h.told, terms: h.terms });
        else setFailed(true);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [server]);

  if (failed || server === "down") return null;
  if (!pair)
    return (
      <div className="hidden rounded-lg border border-rule bg-surface p-6 md:block" aria-busy="true" aria-label="Loading an example finding">
        <Skeleton className="mb-3 h-4 w-40" />
        <Skeleton className="mb-2 h-5 w-full" />
        <Skeleton className="mb-6 h-5 w-4/5" />
        <Skeleton className="mb-2 h-5 w-full" />
        <Skeleton className="h-5 w-3/5" />
      </div>
    );

  const { finding, told, terms } = pair;
  const saidAt = finding.detail.said_at as string | undefined;
  return (
    <figure className="relative rounded-xl border border-ink/15 bg-surface p-5 shadow-[0_30px_80px_-30px_rgb(204_255_61/0.25)] sm:p-7">
      <figcaption className="mb-4 flex flex-wrap items-center gap-2 text-sm text-mute">
        <LabelTag label={finding.label} />
        <span>A real finding from an example report</span>
      </figcaption>

      <div className="space-y-5">
        <blockquote>
          <p className="mb-1 text-[0.8125rem] text-mute">
            {told.source}
            {saidAt ? `, ${formatDate(saidAt)}` : ""}
          </p>
          <p className="font-serif text-[1.0625rem] leading-relaxed text-ink/85">“{told.quote}”</p>
        </blockquote>

        <blockquote>
          <p className="mb-1 text-[0.8125rem] text-mute">
            {terms.source}
            {terms.page_no ? `, page ${terms.page_no}` : ""}
          </p>
          <p className="font-serif text-[1.0625rem] leading-relaxed">
            <mark className="mark-verified mark-draw">“{terms.quote}”</mark>
          </p>
        </blockquote>
      </div>

      <p className="mt-5 border-t border-rule pt-4 text-[0.9375rem] text-ink">
        {finding.title}.{" "}
        <Link href={`/audit/${pair.auditId}`} className="font-medium text-neon underline underline-offset-4">
          Open this report
        </Link>
      </p>
    </figure>
  );
}
