"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ServerNotice, useServerAwake } from "@/components/server-gate";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet, type AuditListItem } from "@/lib/api";

export function ExampleAudits() {
  const [items, setItems] = useState<AuditListItem[] | null>(null);
  const [failed, setFailed] = useState(false);
  const server = useServerAwake();

  useEffect(() => {
    if (server !== "ready") return;
    apiGet<AuditListItem[]>("/api/audits")
      .then(setItems)
      .catch(() => setFailed(true));
  }, [server]);

  if (server === "waking" || server === "down") return <ServerNotice state={server} />;
  if (failed)
    return <p className="text-mute">The examples couldn&apos;t load. Reload the page in a moment.</p>;
  if (!items)
    return (
      <div className="space-y-3" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );

  return (
    <ul className="divide-y divide-rule rounded-lg border border-rule bg-white">
      {items.map((a) => (
        <li key={a.id}>
          <Link
            href={`/audit/${a.id}`}
            className="flex flex-col gap-1 px-4 py-4 hover:bg-paper sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-5"
          >
            <span className="text-[0.9375rem] font-medium text-ink">{a.question}</span>
            <span className="shrink-0 text-sm text-mute">{a.findings ?? 0} findings</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
