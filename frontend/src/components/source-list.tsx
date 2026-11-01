import { Globe, MessageSquareText, ShieldCheck } from "lucide-react";

import type { SourceOut } from "@/lib/api";
import { SOURCE_KINDS, sourceName } from "@/lib/vocab";

export function SourceBadge({ source }: { source: SourceOut }) {
  if (source.kind === "user_chat" || source.kind === "user_upload")
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-rule px-2 py-0.5 text-xs text-ink/75">
        <MessageSquareText aria-hidden className="size-3.5" /> From you
      </span>
    );
  if (source.authority_tier === 1)
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-sourced bg-sourced-soft px-2 py-0.5 text-xs font-medium text-sourced">
        <ShieldCheck aria-hidden className="size-3.5" /> Official
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-rule px-2 py-0.5 text-xs text-ink/75">
      <Globe aria-hidden className="size-3.5" /> Other website
    </span>
  );
}

/** The documents Ritam read (or is reading), official ones first. */
export function SourceList({ sources, onOpen }: { sources: SourceOut[]; onOpen?: (sourceId: string) => void }) {
  const sorted = [...sources].sort((a, b) => a.authority_tier - b.authority_tier);
  return (
    <ul className="divide-y divide-rule">
      {sorted.map((s) => (
        <li key={s.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
          {onOpen && s.status !== "failed" ? (
            <button
              type="button"
              onClick={() => onOpen(s.id)}
              className="text-left text-[0.9375rem] text-ink underline decoration-rule underline-offset-4 hover:decoration-ink"
            >
              {sourceName(s)}
            </button>
          ) : (
            <span className="text-[0.9375rem] text-ink">{sourceName(s)}</span>
          )}
          <SourceBadge source={s} />
          <span className="text-xs text-ink/70">{SOURCE_KINDS[s.kind] ?? s.kind}</span>
          {s.status === "failed" && <span className="text-xs text-uncertain">Couldn&apos;t be read</span>}
        </li>
      ))}
    </ul>
  );
}
