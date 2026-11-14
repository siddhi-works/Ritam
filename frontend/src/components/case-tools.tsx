"use client";

import { CalendarPlus, Check, Copy, Download, FileText, Loader2 } from "lucide-react";
import { useId, useState } from "react";

import { LinkOut } from "@/components/link-out";
import {
  apiGet,
  apiPost,
  problemMessage,
  remindersUrl,
  type LetterFinding,
  type LetterOut,
  type TimelineStep,
} from "@/lib/api";
import { formatDate } from "@/lib/vocab";

export const PRIMARY =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-md bg-neon px-6 font-semibold text-night hover:brightness-110 disabled:opacity-60";
export const SECONDARY =
  "inline-flex min-h-11 items-center gap-2 rounded-md border border-ink/45 px-4 text-sm font-medium text-ink hover:border-neon";
export const FIELD =
  "min-h-11 w-full rounded-md border border-ink/40 bg-night px-3 text-ink placeholder:text-mute focus:border-neon";

const today = () => new Date().toISOString().slice(0, 10);

export function CopyButton({ text, label = "Copy the letter" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <button type="button" onClick={copy} className={SECONDARY}>
      {copied ? <Check aria-hidden className="size-4 text-neon" /> : <Copy aria-hidden className="size-4" />}
      {copied ? "Copied" : label}
    </button>
  );
}

function DownloadButton({ text, name }: { text: string; name: string }) {
  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <button type="button" onClick={download} className={SECONDARY}>
      <Download aria-hidden className="size-4" />
      Download as text
    </button>
  );
}

/** The letter itself, ready to copy, with blanks the person fills in. */
export function LetterText({ text, fileName }: { text: string; fileName: string }) {
  return (
    <div className="space-y-3">
      <pre
        tabIndex={0}
        aria-label="Your letter"
        className="max-h-[28rem] overflow-auto whitespace-pre-wrap rounded-md border border-rule bg-night p-4 font-sans text-[0.9375rem] leading-relaxed text-ink"
      >
        {text}
      </pre>
      <p className="text-sm text-mute">
        Fill in the parts in [square brackets] before sending. Ritam never sees your name or card number.
      </p>
      <div className="flex flex-wrap gap-2">
        <CopyButton text={text} />
        <DownloadButton text={text} name={fileName} />
      </div>
    </div>
  );
}

/** Pick the day you complained; get the bank-reply and RBI Ombudsman dates, and a calendar file. */
export function ComplaintDates({ title = "Card complaint", initial }: { title?: string; initial?: string }) {
  const id = useId();
  const [on, setOn] = useState(initial ?? today());
  const [steps, setSteps] = useState<TimelineStep[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function show(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setSteps(await apiGet<TimelineStep[]>(`/api/cases/timeline?complained_on=${encodeURIComponent(on)}`));
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const upcoming = steps?.some((s) => s.date >= today());
  return (
    <div className="space-y-4">
      <form onSubmit={show} className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={id} className="block text-[0.9375rem] font-semibold text-ink">
            When did you (or will you) send it to the bank?
          </label>
          <input
            id={id}
            type="date"
            value={on}
            max={today()}
            onChange={(e) => setOn(e.target.value)}
            className={`${FIELD} mt-2 w-auto`}
          />
        </div>
        <button type="submit" disabled={busy || !on} className={SECONDARY}>
          {busy && <Loader2 aria-hidden className="size-4 animate-spin" />}
          Show my dates
        </button>
      </form>
      {error && (
        <p role="alert" className="text-[0.9375rem] text-uncertain">
          {error}
        </p>
      )}
      {steps && (
        <>
          <ol className="space-y-3" aria-label="Your complaint dates">
            {steps.map((s) => (
              <li key={s.what} className="flex gap-4 rounded-md border border-rule bg-night p-3">
                <span className="w-28 shrink-0 font-semibold tabular-nums text-ink">{formatDate(s.date)}</span>
                <span>
                  <span className="block text-[0.9375rem] text-ink">{s.what}</span>
                  <span className="block text-sm text-mute">{s.why}</span>
                </span>
              </li>
            ))}
          </ol>
          {upcoming && (
            <a href={remindersUrl(on, title)} className={SECONDARY}>
              <CalendarPlus aria-hidden className="size-4" />
              Add these dates to my calendar
            </a>
          )}
        </>
      )}
    </div>
  );
}

/** Turns findings into a complaint letter, says where to send it, and gives the RBI dates. */
export function LetterBox({
  findings,
  card,
  statementDate,
  level = 3,
}: {
  findings: LetterFinding[];
  card: string | null;
  statementDate: string | null;
  level?: 2 | 3;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  const Sub = level === 2 ? "h3" : "h4";
  const [letter, setLetter] = useState<LetterOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function write() {
    setBusy(true);
    setError(null);
    try {
      setLetter(
        await apiPost<LetterOut>("/api/cases/letter", {
          findings,
          card,
          statement_date: statementDate,
        }),
      );
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="letter-title" className="space-y-4 rounded-lg border border-neon/50 bg-surface p-5 sm:p-6">
      <Heading id="letter-title" className="text-lg font-semibold text-ink">
        Ask your bank to fix this
      </Heading>
      {!letter && (
        <>
          <p className="max-w-prose text-[0.9375rem] leading-relaxed text-ink/85">
            Ritam writes the complaint for you, with the bill line, the rule and the amount to reverse. You send it from
            your own email or the bank&apos;s complaint form.
          </p>
          <button type="button" onClick={write} disabled={busy} className={PRIMARY}>
            {busy ? <Loader2 aria-hidden className="size-4 animate-spin" /> : <FileText aria-hidden className="size-4" />}
            Write my complaint letter
          </button>
        </>
      )}
      {error && (
        <p role="alert" className="text-[0.9375rem] text-uncertain">
          {error}
        </p>
      )}
      {letter && (
        <div className="space-y-6">
          <LetterText text={letter.letter} fileName="ritam-complaint.txt" />
          <div className="space-y-2">
            <Sub className="font-semibold text-ink">Where to send it</Sub>
            {letter.where_to_send ? (
              <div className="rounded-md border border-rule bg-night p-4 text-[0.9375rem] text-ink/85">
                <p>{letter.where_to_send.text}</p>
                <p className="mt-2 text-sm text-mute">
                  From the bank&apos;s own document
                  {letter.where_to_send.url && (
                    <>
                      :{" "}
                      <LinkOut href={letter.where_to_send.url} className="hover:text-neon">
                        {letter.where_to_send.source ?? "open it"}
                      </LinkOut>
                    </>
                  )}
                </p>
              </div>
            ) : (
              <p className="text-[0.9375rem] text-ink/85">
                Send it to the bank&apos;s grievance redressal officer. Their email is on the bank&apos;s website,
                usually under &quot;Grievance redressal&quot;, and often printed on your bill.
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Sub className="font-semibold text-ink">If the bank doesn&apos;t fix it</Sub>
            <ComplaintDates title={`${card ?? "Card"} complaint`} />
          </div>
        </div>
      )}
    </section>
  );
}
