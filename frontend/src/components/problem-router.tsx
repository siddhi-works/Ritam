"use client";

import { ArrowRight, Loader2, Phone, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";

import { ListenButton, VoiceButton } from "@/components/assist";
import { PRIMARY } from "@/components/case-tools";
import { LinkOut } from "@/components/link-out";
import { apiPost, problemMessage, type TriageOut } from "@/lib/api";
import { CYBERCRIME, RBI_COMPLAINT } from "@/lib/questions";

const EXAMPLES = [
  "Annual fee charged on my lifetime free card",
  "Late fee although I paid on time",
  "Bank isn't closing my card",
  "My reward points disappeared",
  "Charged twice for one purchase",
  "A payment I didn't make",
];

function next(r: TriageOut): { href: string; label: string } | null {
  const q = (params: Record<string, string | undefined>) => {
    const s = new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => Boolean(e[1])));
    return s.size ? `?${s}` : "";
  };
  const card = r.prefill.card ?? undefined;
  const date = r.prefill.dates.at(-1);
  switch (r.tool) {
    case "statement_check":
      return { href: "/statement", label: "Check my bill" };
    case "compare_bills":
      return { href: "/statement?bills=2", label: "Check my last two bills" };
    case "closure_claim":
      return { href: `/closure${q({ card, date })}`, label: "Work out what I'm owed" };
    case "terms_history":
      return { href: `/changes${q({ card: r.prefill.card_id ?? undefined })}`, label: "See what changed on my card" };
    case "complaint_dates":
      return { href: `/complaint${q({ date })}`, label: "Show my complaint dates" };
    case "complaint_letter":
      return { href: `/complaint${q({ problem: r.problem ?? undefined, card })}`, label: "Write my letter" };
    case "card_report":
      return { href: "/#start", label: "Get a report on my card" };
    default:
      return null;
  }
}

/** "What went wrong?" in a sentence or two, spoken or typed, to the Ritam tool that handles it. */
export function ProblemRouter() {
  const id = useId();
  const [text, setText] = useState("");
  const [out, setOut] = useState<TriageOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function ask(message: string) {
    if (message.trim().length < 3) {
      setError("Tell Ritam what happened in a few words.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setOut(await apiPost<TriageOut>("/api/triage", { text: message.trim() }));
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const go = out && !out.not_indian ? next(out) : null;
  const fraud = out?.tool === "fraud_help";

  return (
    <div className="space-y-5">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(text);
        }}
        className="space-y-3"
      >
        <label htmlFor={id} className="block text-[1.0625rem] font-medium text-ink">
          In your own words, what happened?
        </label>
        <textarea
          id={id}
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          maxLength={2000}
          placeholder="For example: the bank charged me ₹1,180 annual fee but the agent said the card was lifetime free"
          className="w-full rounded-md border border-ink/40 bg-surface px-3 py-2.5 text-base text-ink placeholder:text-mute focus:border-neon"
        />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <VoiceButton
            what="what happened"
            languages={["en-IN", "hi-IN"]}
            onText={(t) => {
              setText(t);
              ask(t);
            }}
          />
          <button type="submit" disabled={busy} className={PRIMARY}>
            {busy && <Loader2 aria-hidden className="size-4 animate-spin" />}
            Find what to do
          </button>
        </div>
      </form>

      <div className="flex flex-wrap gap-2" aria-label="Common problems">
        {EXAMPLES.map((e) => (
          <button
            key={e}
            type="button"
            onClick={() => {
              setText(e);
              ask(e);
            }}
            className="min-h-11 rounded-full border border-rule bg-surface px-4 text-left text-[0.9375rem] text-ink hover:border-ink"
          >
            {e}
          </button>
        ))}
      </div>

      {error && (
        <p role="alert" className="text-[0.9375rem] text-uncertain">
          {error}
        </p>
      )}

      {out && (
        <section
          id="problem-result"
          aria-live="polite"
          className={`space-y-4 rounded-lg border p-5 sm:p-6 ${fraud ? "border-uncertain bg-uncertain-soft" : "border-neon/50 bg-surface"}`}
        >
          {out.not_indian ? (
            <p className="text-[0.9375rem] text-ink">
              Ritam only checks credit cards issued in India, against RBI&apos;s rules. This sounds like a card from a bank
              outside India.
            </p>
          ) : (
            <>
              <h3 className="flex items-center gap-2 text-lg font-semibold text-ink">
                {fraud && <ShieldAlert aria-hidden className="size-5 text-uncertain" />}
                {out.title ?? "Tell Ritam a little more"}
              </h3>
              <ol className="list-decimal space-y-2 pl-5 text-[0.9375rem] leading-relaxed text-ink/90 marker:text-mute">
                {out.steps.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ol>
              {out.ref && <p className="text-sm text-mute">Rule: {out.ref}</p>}
              <ListenButton targetId="problem-result" label="Listen to this" />
              {out.prefill.card && <p className="text-sm text-mute">Card: {out.prefill.card}</p>}
              <div className="flex flex-wrap items-center gap-3">
                {fraud && (
                  <>
                    <a href="tel:1930" className={PRIMARY}>
                      <Phone aria-hidden className="size-4" />
                      Call 1930
                    </a>
                    <LinkOut href={CYBERCRIME.href} className="hover:text-neon">
                      Report at cybercrime.gov.in
                    </LinkOut>
                  </>
                )}
                {go && (
                  <Link href={go.href} className={PRIMARY}>
                    {go.label}
                    <ArrowRight aria-hidden className="size-4" />
                  </Link>
                )}
                {out.tool === "guide" && (
                  <LinkOut href={RBI_COMPLAINT.href} className="hover:text-neon">
                    {RBI_COMPLAINT.label}
                  </LinkOut>
                )}
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
