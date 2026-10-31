"use client";

import { ExternalLink } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet, problemMessage, type SourceView } from "@/lib/api";
import { formatDate, SOURCE_KINDS, sourceName } from "@/lib/vocab";

export interface EvidenceTarget {
  sourceId: string;
  claimId?: string;
  pageNo?: number | null;
}

function useIsDesktop() {
  const [desktop, setDesktop] = useState(true);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 768px)");
    const set = () => setDesktop(mq.matches);
    set();
    mq.addEventListener("change", set);
    return () => mq.removeEventListener("change", set);
  }, []);
  return desktop;
}

/** The source document, page by page, with the verified quote highlighted and scrolled into view. */
export function EvidenceSheet({ target, onClose }: { target: EvidenceTarget | null; onClose: () => void }) {
  const desktop = useIsDesktop();
  const [view, setView] = useState<SourceView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const markRef = useRef<HTMLElement | null>(null);
  const pageRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!target) return;
    setView(null);
    setError(null);
    const q = target.claimId ? `?claim=${target.claimId}` : "";
    apiGet<SourceView>(`/api/sources/${target.sourceId}/view${q}`)
      .then(setView)
      .catch((e) => setError(problemMessage(e)));
  }, [target]);

  useEffect(() => {
    if (!view) return;
    const el = markRef.current ?? pageRef.current;
    el?.scrollIntoView({ block: "center" });
  }, [view]);

  const s = view?.source;
  return (
    <Sheet open={!!target} onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        side={desktop ? "right" : "bottom"}
        className={desktop ? "w-full gap-0 p-0 sm:max-w-2xl" : "h-[88vh] gap-0 p-0"}
      >
        <SheetHeader className="border-b border-rule bg-white px-5 py-4">
          <SheetTitle className="pr-8 text-base leading-snug">{s ? sourceName(s) : "Loading source…"}</SheetTitle>
          <SheetDescription asChild>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-mute">
              {s && <span>{SOURCE_KINDS[s.kind] ?? s.kind}</span>}
              {s?.effective_from && <span>Effective {formatDate(s.effective_from)}</span>}
              {s?.archived_at && <span>Archived copy from {formatDate(s.archived_at)}</span>}
              {s && !s.archived_at && s.fetched_at && <span>Fetched {formatDate(s.fetched_at)}</span>}
              {s?.undated && <span className="font-medium text-uncertain">No reliable date</span>}
              {s?.url && (
                <a href={s.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-4">
                  Original <ExternalLink aria-hidden className="size-3.5" />
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
              )}
            </div>
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto bg-paper px-5 py-5">
          {error && <p role="alert" className="text-destructive">{error}</p>}
          {!view && !error && (
            <div className="space-y-3" aria-busy="true">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          )}
          {view?.pages.map((p) => {
            const marks = view.highlights.filter((h) => h.page_no === p.page_no).sort((a, b) => a.char_start - b.char_start);
            const isTargetPage = target?.pageNo === p.page_no || (marks.length > 0 && !target?.pageNo);
            return (
              <section
                key={p.page_no}
                ref={(el) => {
                  if (isTargetPage && !pageRef.current) pageRef.current = el;
                }}
                aria-label={`Page ${p.page_no}`}
                className="mb-6 rounded-md border border-rule bg-white p-4"
              >
                {view.pages.length > 1 && <p className="mb-2 text-xs text-mute">Page {p.page_no}</p>}
                <p className="whitespace-pre-wrap font-serif text-[0.9375rem] leading-[1.75] text-ink">
                  {renderMarked(p.text, marks, markRef)}
                </p>
              </section>
            );
          })}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function renderMarked(
  text: string,
  marks: { char_start: number; char_end: number }[],
  markRef: React.RefObject<HTMLElement | null>,
) {
  if (!marks.length) return text;
  const out: React.ReactNode[] = [];
  let pos = 0;
  marks.forEach((m, i) => {
    if (m.char_start < pos) return;
    out.push(text.slice(pos, m.char_start));
    out.push(
      <mark
        key={i}
        ref={i === 0 ? (el) => { markRef.current = el; } : undefined}
        className="mark-verified"
      >
        {text.slice(m.char_start, m.char_end)}
      </mark>,
    );
    pos = m.char_end;
  });
  out.push(text.slice(pos));
  return out;
}
