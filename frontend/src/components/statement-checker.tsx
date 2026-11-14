"use client";

import { FileUp, ShieldCheck, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ListenButton } from "@/components/assist";
import { LetterBox } from "@/components/case-tools";
import { ComplaintHelp, SavePdfButton } from "@/components/complaint-help";
import { LabelTag } from "@/components/label-tag";
import { Working } from "@/components/working";
import { formatDate } from "@/lib/vocab";
import {
  checkStatement,
  compareStatements,
  problemMessage,
  type StatementFinding,
  type StatementOut,
} from "@/lib/api";

const KIND: Record<string, string> = {
  annual_fee: "Annual fee",
  joining_fee: "Joining fee",
  late_payment_fee: "Late payment fee",
  finance_charge: "Interest",
  cash_advance_fee: "Cash withdrawal fee",
  forex_markup: "Foreign currency fee",
  dcc_markup: "Rupee payment abroad fee",
  overlimit_fee: "Over-limit fee",
  rent_payment_fee: "Rent payment fee",
  fuel_surcharge: "Fuel surcharge",
  emi_processing_fee: "EMI processing fee",
  emi_interest: "EMI interest",
  emi_foreclosure_fee: "EMI early closure fee",
  gst: "GST",
  other_charge: "Other charge",
};

// One plain line on why each kind of charge appears.
const WHY: Record<string, string> = {
  finance_charge: "Charged when the last bill wasn't paid in full by the due date, even by a few rupees.",
  late_payment_fee: "Charged when not even the minimum amount was paid in time.",
  gst: "18% tax on the bank's fees and interest.",
  forex_markup: "Added to payments made in a foreign currency.",
  dcc_markup: "Added when you paid in rupees abroad or on a foreign website.",
  cash_advance_fee: "Charged for taking cash from an ATM with the card.",
  annual_fee: "The yearly fee. Many cards waive it if you spend enough in the year.",
  overlimit_fee: "Charged for going over the credit limit.",
  rent_payment_fee: "Charged for paying rent with the card.",
  fuel_surcharge: "Added at petrol pumps; many cards refund it within a spend range.",
  emi_processing_fee: "One-time fee for turning a purchase into EMIs.",
  emi_interest: "Interest on an EMI. A no-cost EMI should give this back as a discount.",
  emi_foreclosure_fee: "Charged for closing an EMI early.",
};

const LINES = [
  "Reading your bill",
  "Hiding your card number, phone and email before anything else",
  "Picking out the fees, interest and GST",
  "Checking every amount is really printed on your bill",
  "Comparing the charges with RBI's rules and your card's terms",
];

/** "21469.29" or "21,469.29 Dr" as printed → ₹21,469.29. */
const money = (printed: string) => {
  const n = Number(printed.replace(/[^\d.]/g, ""));
  return Number.isFinite(n) && n > 0 ? rupees(n) : printed;
};
const rupees = (n: number) => `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
function FilePicker({
  id,
  label,
  hint,
  file,
  onFile,
}: {
  id: string;
  label: string;
  hint?: string;
  file: File | null;
  onFile: (f: File | null) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-[0.9375rem] font-semibold text-ink">
        {label}
      </label>
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-sm text-mute">
          {hint}
        </p>
      )}
      <label
        htmlFor={id}
        className="mt-3 flex min-h-20 cursor-pointer items-center gap-3 rounded-lg border border-dashed border-ink/40 px-4 py-4 text-ink hover:border-neon focus-within:border-neon"
      >
        <FileUp aria-hidden className="size-6 shrink-0 text-neon" />
        <span className="text-[0.9375rem]">{file ? file.name : "Choose a PDF from your phone or computer"}</span>
        <input
          id={id}
          type="file"
          accept="application/pdf,.pdf"
          aria-describedby={hint ? `${id}-hint` : undefined}
          className="sr-only"
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
        />
      </label>
    </div>
  );
}

export function StatementChecker({ twoBills = false }: { twoBills?: boolean }) {
  const [file, setFile] = useState<File | null>(null);
  const [previous, setPrevious] = useState<File | null>(null);
  const [compare, setCompare] = useState(twoBills);
  const [lifetimeFree, setLifetimeFree] = useState(false);
  const [card, setCard] = useState("");
  const [busy, setBusy] = useState(false);
  const [percent, setPercent] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<StatementOut | null>(null);
  const resultRef = useRef<HTMLHeadingElement>(null);
  const workingRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => setPercent((p) => p + (95 - p) * 0.05), 800);
    return () => clearInterval(t);
  }, [busy]);

  useEffect(() => {
    if (result) resultRef.current?.focus();
  }, [result]);

  useEffect(() => {
    if (busy) workingRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [busy]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || (compare && !previous)) {
      setError(compare ? "Choose both bills first." : "Choose your bill's PDF first.");
      return;
    }
    setBusy(true);
    setPercent(4);
    setError(null);
    setResult(null);
    try {
      setResult(
        compare && previous
          ? await compareStatements(previous, file, card, lifetimeFree)
          : await checkStatement(file, card, lifetimeFree),
      );
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const asks = result?.findings.filter((f) => f.ask) ?? [];
  const notes = result?.findings.filter((f) => !f.ask) ?? [];
  const charged = result?.charges.reduce((a, c) => a + c.amount, 0) ?? 0;

  return (
    <div className="space-y-8">
      <form onSubmit={submit} className="space-y-5 rounded-lg border border-rule bg-surface p-5 sm:p-6" noValidate>
        <FilePicker
          id="bill"
          label={compare ? "This month's bill (PDF)" : "Your credit card bill (PDF)"}
          hint="The statement PDF your bank emails you. If it asks for a password, open it, save a copy without one, and upload that."
          file={file}
          onFile={setFile}
        />
        <label className="flex min-h-11 cursor-pointer items-start gap-3 text-[0.9375rem] text-ink">
          <input
            type="checkbox"
            checked={compare}
            onChange={(e) => setCompare(e.target.checked)}
            className="mt-1 size-5 accent-[var(--color-neon)]"
          />
          <span>
            I also have last month&apos;s bill
            <span className="block text-sm text-mute">
              Then Ritam can check a late fee against the right due date, interest after a full payment, a cut in
              your credit limit and missing reward points.
            </span>
          </span>
        </label>
        {compare && <FilePicker id="previous-bill" label="Last month's bill (PDF)" file={previous} onFile={setPrevious} />}
        <div>
          <label htmlFor="card" className="block text-[0.9375rem] font-semibold text-ink">
            Card name <span className="font-normal text-mute">(optional)</span>
          </label>
          <p id="card-hint" className="mt-1 text-sm text-mute">
            For example, HDFC Millennia. Ritam then also compares the charges with that card&apos;s terms.
          </p>
          <input
            id="card"
            value={card}
            onChange={(e) => setCard(e.target.value)}
            aria-describedby="card-hint"
            maxLength={200}
            autoComplete="off"
            className="mt-2 min-h-11 w-full rounded-md border border-ink/40 bg-night px-3 text-ink placeholder:text-mute focus:border-neon"
          />
        </div>
        <label className="flex min-h-11 cursor-pointer items-start gap-3 text-[0.9375rem] text-ink">
          <input
            type="checkbox"
            checked={lifetimeFree}
            onChange={(e) => setLifetimeFree(e.target.checked)}
            className="mt-1 size-5 accent-[var(--color-neon)]"
          />
          <span>
            This card was sold to me as lifetime free
            <span className="block text-sm text-mute">
              Then an annual or joining fee on the bill is something to ask the bank about. Keep the offer email, SMS
              or screenshot ready.
            </span>
          </span>
        </label>
        <button
          type="submit"
          disabled={busy}
          className="inline-flex min-h-12 items-center justify-center rounded-md bg-neon px-6 font-semibold text-night hover:brightness-110 disabled:opacity-60"
        >
          {busy ? "Checking…" : compare ? "Check both bills" : "Check my bill"}
        </button>
        <p className="flex items-start gap-2 text-sm text-mute">
          <ShieldCheck aria-hidden className="mt-0.5 size-4 shrink-0 text-neon" />
          Your bill is read once and not saved. Only the lines with dates, amounts and charges are read, so your name and address are usually left out, and card numbers, phone numbers and emails are hidden.
        </p>
      </form>

      {busy && (
        <div ref={workingRef}>
          <Working title="Checking your bill" percent={percent} lines={LINES} />
        </div>
      )}

      {error && (
        <p role="alert" className="flex items-start gap-2 rounded-lg border border-uncertain/60 bg-surface p-4 text-ink">
          <TriangleAlert aria-hidden className="mt-0.5 size-5 shrink-0 text-uncertain" />
          {error}
        </p>
      )}

      {result && (
        <section id="bill-result" aria-labelledby="result-title" className="space-y-6">
          <ListenButton targetId="bill-result" label="Listen to this" />
          <h2 id="result-title" ref={resultRef} tabIndex={-1} className="font-display text-2xl font-bold text-ink outline-none">
            {asks.length
              ? `${asks.length} ${asks.length === 1 ? "thing" : "things"} worth asking your bank about`
              : "Nothing to question in the charges Ritam could read"}
          </h2>

          <dl className="grid gap-3 sm:grid-cols-3">
            {[
              ["Total due", result.total_due && money(result.total_due)],
              ["Pay by", result.dates.payment_due_date && formatDate(result.dates.payment_due_date)],
              ["Fees, interest and GST", result.charges.length ? rupees(charged) : "None found"],
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-rule bg-surface p-4">
                <dt className="text-sm text-mute">{k}</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums text-ink">{v ?? "Not found"}</dd>
              </div>
            ))}
          </dl>

          {asks.length > 0 && <FindingList findings={asks} />}
          {asks.length > 0 && (
            <LetterBox
              card={result.card ?? (card.trim() || null)}
              statementDate={result.dates.statement_date}
              findings={asks.map((f) => ({
                rule: f.rule,
                charge: f.charge,
                amount: f.amount,
                ref: f.ref,
              }))}
            />
          )}
          {notes.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-lg font-semibold text-ink">Good to know</h3>
              <FindingList findings={notes} level={4} />
            </div>
          )}

          {result.charges.length > 0 && (
            <div className="rounded-lg border border-rule">
              <h3 className="px-4 pt-4 font-semibold text-ink">Charges on this bill</h3>
              <ul className="mt-2">
                {result.charges.map((c, i) => (
                  <li key={i} className="flex items-start justify-between gap-4 border-t border-rule px-4 py-3">
                    <div>
                      <p className="text-[0.9375rem] font-medium text-ink">{KIND[c.kind] ?? "Other charge"}</p>
                      <p className="text-sm text-mute">
                        Printed as “{c.description}”{WHY[c.kind] ? `. ${WHY[c.kind]}` : ""}
                      </p>
                    </div>
                    <p className="shrink-0 text-[0.9375rem] font-semibold tabular-nums text-ink">{rupees(c.amount)}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="space-y-2 text-sm text-mute">
            {result.card && result.report_id ? (
              <p>
                Compared with the terms in Ritam&apos;s{" "}
                <Link href={`/audit/${result.report_id}`} className="text-ink underline underline-offset-4 hover:text-neon">
                  {result.card} report
                </Link>
                .
              </p>
            ) : result.card ? (
              <p>
                Ritam has no checked report for {result.card} yet, so the charges were checked against RBI&apos;s rules only.{" "}
                <Link href="/#start" className="text-ink underline underline-offset-4 hover:text-neon">
                  Get a report for this card
                </Link>
                .
              </p>
            ) : (
              <p>
                {card.trim()
                  ? `Ritam doesn't have “${card.trim()}” on its list of checked cards yet, so the charges were checked against RBI's rules only.`
                  : "Add your card's name to also compare the charges with its terms."}
              </p>
            )}
            {result.dropped > 0 && (
              <p>
                {result.dropped} {result.dropped === 1 ? "line was" : "lines were"} left out because the bill itself didn&apos;t
                confirm the amount and the kind of charge on the same line.
              </p>
            )}
            {result.truncated && <p>This bill is long, so only its first part was read.</p>}
            {result.masked > 0 && <p>{result.masked} personal details were hidden before reading.</p>}
          </div>
          <ComplaintHelp />
          <SavePdfButton />
        </section>
      )}
    </div>
  );
}

function FindingList({ findings, level = 3 }: { findings: StatementFinding[]; level?: 3 | 4 }) {
  const Heading = level === 3 ? "h3" : "h4";
  return (
    <ul className="space-y-3">
      {findings.map((f, i) => (
        <li key={i} className="rounded-lg border border-rule bg-surface p-5">
          <div className="flex flex-wrap items-center gap-2">
            <Heading className="text-lg font-semibold text-ink">{f.title}</Heading>
            <LabelTag label={f.label} />
          </div>
          <p className="mt-2 max-w-prose leading-relaxed text-ink/85">{f.detail}</p>
          {f.ref && <p className="mt-2 text-sm text-mute">Rule: {f.ref}</p>}
        </li>
      ))}
    </ul>
  );
}
