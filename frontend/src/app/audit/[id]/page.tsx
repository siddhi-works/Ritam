"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";

import { AuditProgress } from "@/components/audit-progress";
import { AuditResult } from "@/components/audit-result";
import { ServerNotice, useServerAwake } from "@/components/server-gate";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet, problemMessage, type AuditOut } from "@/lib/api";

const RUNNING = new Set(["queued", "running"]);

export default function AuditPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const server = useServerAwake();
  const [audit, setAudit] = useState<AuditOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiGet<AuditOut>(`/api/audits/${id}`)
      .then((a) => {
        setAudit(a);
        setError(null);
      })
      .catch((e) => setError(problemMessage(e)));
  }, [id]);

  useEffect(() => {
    if (server === "ready") load();
  }, [server, load]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
      <p className="mb-6 text-sm">
        <Link href="/" className="text-mute underline-offset-4 hover:text-ink hover:underline">
          Back to Ritam
        </Link>
      </p>
      <ServerNotice state={server} />
      {error && (
        <p role="alert" className="rounded-md border border-destructive bg-white px-4 py-3 text-destructive">
          {error}
        </p>
      )}
      {!audit && !error && server !== "down" && (
        <div className="space-y-4" aria-busy="true" aria-label="Loading audit">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-10 w-3/4" />
          <Skeleton className="h-40 w-full" />
        </div>
      )}
      {audit && RUNNING.has(audit.status) && (
        <div className="space-y-6">
          <div>
            {audit.product_name && <p className="text-[0.9375rem] font-medium text-mute">{audit.product_name}</p>}
            <h1 className="mt-1 max-w-3xl text-[1.75rem] font-semibold leading-tight tracking-tight text-ink">{audit.question}</h1>
          </div>
          <AuditProgress auditId={audit.id} onDone={load} />
        </div>
      )}
      {audit && !RUNNING.has(audit.status) && <AuditResult audit={audit} />}
    </main>
  );
}
