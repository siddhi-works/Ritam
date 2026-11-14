"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";

import { ComplaintDates, FIELD, LetterText, PRIMARY } from "@/components/case-tools";
import { apiPost, problemMessage, type ClosureOut } from "@/lib/api";
import { formatDate } from "@/lib/vocab";

const today = () => new Date().toISOString().slice(0, 10);
const rupees = (n: number) => `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

/** Card not closed in time: the penalty RBI's rules give you, and a letter claiming it. */
export function ClosureClaim({ initialCard = "", initialDate = "" }: { initialCard?: string; initialDate?: string }) {
  const [requested, setRequested] = useState(initialDate);
  const [closed, setClosed] = useState("");
  const [card, setCard] = useState(initialCard);
  const [out, setOut] = useState<ClosureOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!requested) {
      setError("Enter the day you asked for the card to be closed.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setOut(
        await apiPost<ClosureOut>("/api/cases/closure", {
          requested_on: requested,
          closed_on: closed || null,
          card: card.trim() || null,
        }),
      );
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <form onSubmit={submit} noValidate className="space-y-5 rounded-lg border border-rule bg-surface p-5 sm:p-6">
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="requested" className="block text-[0.9375rem] font-semibold text-ink">
              When did you ask for it to be closed?
            </label>
            <input
              id="requested"
              type="date"
              required
              max={today()}
              value={requested}
              onChange={(e) => setRequested(e.target.value)}
              className={`${FIELD} mt-2`}
            />
          </div>
          <div>
            <label htmlFor="closed" className="block text-[0.9375rem] font-semibold text-ink">
              When was it closed? <span className="font-normal text-mute">(leave empty if still open)</span>
            </label>
            <input
              id="closed"
              type="date"
              min={requested || undefined}
              max={today()}
              value={closed}
              onChange={(e) => setClosed(e.target.value)}
              className={`${FIELD} mt-2`}
            />
          </div>
        </div>
        <div>
          <label htmlFor="closure-card" className="block text-[0.9375rem] font-semibold text-ink">
            Card name <span className="font-normal text-mute">(optional)</span>
          </label>
          <input
            id="closure-card"
            value={card}
            onChange={(e) => setCard(e.target.value)}
            maxLength={200}
            autoComplete="off"
            placeholder="For example: Axis ACE"
            className={`${FIELD} mt-2`}
          />
        </div>
        <button type="submit" disabled={busy} className={PRIMARY}>
          {busy && <Loader2 aria-hidden className="size-4 animate-spin" />}
          Work out what I&apos;m owed
        </button>
      </form>

      {error && (
        <p role="alert" className="rounded-lg border border-uncertain/60 bg-surface p-4 text-ink">
          {error}
        </p>
      )}

      {out && (
        <section aria-labelledby="closure-result" className="space-y-6">
          <h2 id="closure-result" className="font-display text-2xl font-bold text-ink">
            {out.days_late
              ? `${out.days_late} days late: at least ${rupees(out.penalty)} is due to you`
              : "The bank is still within its 7 working days"}
          </h2>
          <dl className="grid gap-3 sm:grid-cols-3">
            {[
              ["You asked on", formatDate(out.requested_on)],
              ["Bank had to close it by", formatDate(out.due_by)],
              ["Penalty so far", rupees(out.penalty)],
            ].map(([k, v]) => (
              <div key={k} className="rounded-lg border border-rule bg-surface p-4">
                <dt className="text-sm text-mute">{k}</dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums text-ink">{v}</dd>
              </div>
            ))}
          </dl>
          <p className="text-sm text-mute">{out.note}</p>
          {out.letter && (
            <div className="space-y-6 rounded-lg border border-neon/50 bg-surface p-5 sm:p-6">
              <h3 className="text-lg font-semibold text-ink">Your claim letter</h3>
              <LetterText text={out.letter} fileName="ritam-closure-claim.txt" />
              <div className="space-y-2">
                <h4 className="font-semibold text-ink">If the bank doesn&apos;t pay</h4>
                <ComplaintDates title="Card closure claim" />
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
