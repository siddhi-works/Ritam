"use client";

import { ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { ListenButton } from "@/components/assist";
import { FIELD, PRIMARY } from "@/components/case-tools";
import { apiPost, problemMessage } from "@/lib/api";

const CATEGORIES = [
  { key: "online", label: "Online shopping" },
  { key: "dining", label: "Food delivery and dining" },
  { key: "groceries", label: "Groceries" },
  { key: "fuel", label: "Fuel" },
  { key: "travel", label: "Travel bookings" },
  { key: "bills", label: "Bills and utilities" },
  { key: "other", label: "Everything else" },
] as const;

interface Point {
  text: string;
  maths: string | null;
  benchmark: string | null;
}

interface Checklist {
  yearly_spend: number;
  must_have: Point[];
  nice_to_have: Point[];
  skip_if: Point[];
  ask_the_bank: string[];
}

const CHECK_QUESTION =
  "Check this card's annual fee and waiver, reward rates, caps and exclusions, foreign currency markup and lounge conditions.";

function Points({ title, points, tone }: { title: string; points: Point[]; tone: "good" | "maybe" | "avoid" }) {
  if (!points.length) return null;
  const border = tone === "avoid" ? "border-uncertain/60" : tone === "good" ? "border-neon/50" : "border-rule";
  return (
    <section aria-label={title} className={`rounded-lg border ${border} bg-surface p-5`}>
      <h3 className="text-lg font-semibold text-ink">{title}</h3>
      <ul className="mt-3 space-y-4">
        {points.map((p) => (
          <li key={p.text}>
            <p className="text-[0.9375rem] font-medium text-ink">{p.text}</p>
            {p.maths && <p className="mt-1 text-sm leading-relaxed text-ink/75">{p.maths}</p>}
            {p.benchmark && <p className="mt-1 text-sm text-mute">{p.benchmark}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** What to look for in a card, from the person's own spending. No card is recommended by name. */
export function CardFinder() {
  const [spend, setSpend] = useState<Record<string, string>>({});
  const [abroad, setAbroad] = useState("");
  const [lounge, setLounge] = useState("");
  const [maxFee, setMaxFee] = useState("0");
  const [paysInFull, setPaysInFull] = useState(true);
  const [apps, setApps] = useState("");
  const [card, setCard] = useState("");
  const [out, setOut] = useState<Checklist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const resultRef = useRef<HTMLHeadingElement>(null);

  const num = (v: string) => Math.max(0, Number(v.replace(/[^\d.]/g, "")) || 0);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<Checklist>("/api/advisor", {
        spend: Object.fromEntries(Object.entries(spend).map(([k, v]) => [k, num(v)])),
        abroad_per_year: num(abroad),
        lounge_visits_per_year: Math.round(num(lounge)),
        max_fee: num(maxFee),
        pays_in_full: paysInFull,
        apps: apps
          .split(",")
          .map((a) => a.trim())
          .filter(Boolean)
          .slice(0, 5),
      });
      setOut(result);
      setTimeout(() => resultRef.current?.focus(), 50);
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-8">
      <form onSubmit={submit} noValidate className="space-y-6 rounded-lg border border-rule bg-surface p-5 sm:p-6">
        <fieldset>
          <legend className="text-[0.9375rem] font-semibold text-ink">Roughly how much do you spend a month?</legend>
          <p className="mt-1 text-sm text-mute">Round numbers are fine. Leave a box empty if you don&apos;t spend on it.</p>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {CATEGORIES.map((c) => (
              <div key={c.key}>
                <label htmlFor={`spend-${c.key}`} className="block text-sm text-ink">
                  {c.label} (₹ a month)
                </label>
                <input
                  id={`spend-${c.key}`}
                  inputMode="numeric"
                  value={spend[c.key] ?? ""}
                  onChange={(e) => setSpend((s) => ({ ...s, [c.key]: e.target.value }))}
                  className={`${FIELD} mt-1`}
                />
              </div>
            ))}
          </div>
        </fieldset>

        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="abroad" className="block text-sm text-ink">
              Spent abroad or on foreign websites (₹ a year)
            </label>
            <input id="abroad" inputMode="numeric" value={abroad} onChange={(e) => setAbroad(e.target.value)} className={`${FIELD} mt-1`} />
          </div>
          <div>
            <label htmlFor="lounge" className="block text-sm text-ink">
              Airport lounge visits you&apos;d use (a year)
            </label>
            <input id="lounge" inputMode="numeric" value={lounge} onChange={(e) => setLounge(e.target.value)} className={`${FIELD} mt-1`} />
          </div>
          <div>
            <label htmlFor="max-fee" className="block text-sm text-ink">
              Most you&apos;d pay as a yearly fee (₹)
            </label>
            <input id="max-fee" inputMode="numeric" value={maxFee} onChange={(e) => setMaxFee(e.target.value)} className={`${FIELD} mt-1`} />
          </div>
        </div>

        <div>
          <label htmlFor="apps" className="block text-sm text-ink">
            Apps or stores you use most <span className="text-mute">(optional, separated by commas)</span>
          </label>
          <input
            id="apps"
            value={apps}
            onChange={(e) => setApps(e.target.value)}
            placeholder="For example: Amazon, Swiggy"
            className={`${FIELD} mt-1`}
          />
        </div>

        <label className="flex min-h-11 cursor-pointer items-start gap-3 text-[0.9375rem] text-ink">
          <input
            type="checkbox"
            checked={paysInFull}
            onChange={(e) => setPaysInFull(e.target.checked)}
            className="mt-1 size-5 accent-[var(--color-neon)]"
          />
          I usually pay my full bill every month
        </label>

        <button type="submit" disabled={busy} className={PRIMARY}>
          {busy && <Loader2 aria-hidden className="size-4 animate-spin" />}
          Show what to look for
        </button>
        <p className="text-sm text-mute">Your answers aren&apos;t stored. Ritam doesn&apos;t sell cards or earn from any bank.</p>
      </form>

      {error && (
        <p role="alert" className="rounded-lg border border-uncertain/60 bg-surface p-4 text-ink">
          {error}
        </p>
      )}

      {out && (
        <section id="finder-result" aria-labelledby="finder-title" className="space-y-5">
          <ListenButton targetId="finder-result" label="Listen to this" />
          <h2 id="finder-title" ref={resultRef} tabIndex={-1} className="font-display text-2xl font-bold text-ink outline-none">
            What to look for in your next card
          </h2>
          <Points title="Must have" points={out.must_have} tone="good" />
          <Points title="Nice to have" points={out.nice_to_have} tone="maybe" />
          <Points title="Skip a card if" points={out.skip_if} tone="avoid" />
          <section aria-labelledby="ask-title" className="rounded-lg border border-rule bg-surface p-5">
            <h3 id="ask-title" className="text-lg font-semibold text-ink">
              Ask before you apply
            </h3>
            <ul className="mt-3 list-disc space-y-2 pl-5 text-[0.9375rem] text-ink/90 marker:text-mute">
              {out.ask_the_bank.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          </section>

          <section aria-labelledby="check-title" className="space-y-3 rounded-lg border border-neon/50 bg-surface p-5">
            <h3 id="check-title" className="text-lg font-semibold text-ink">
              Check a card against this list
            </h3>
            <p className="text-[0.9375rem] text-ink/85">
              Found a card you like? Ritam reads its official terms and shows its real fees, rewards, caps and recent
              changes.
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-[14rem] flex-1">
                <label htmlFor="check-card" className="block text-sm text-ink">
                  Card name
                </label>
                <input
                  id="check-card"
                  value={card}
                  onChange={(e) => setCard(e.target.value)}
                  placeholder="For example: SBI Cashback"
                  className={`${FIELD} mt-1`}
                />
              </div>
              <Link
                href={`/?${new URLSearchParams({ card: card.trim(), q: CHECK_QUESTION })}#start`}
                aria-disabled={!card.trim()}
                className={`${PRIMARY} ${card.trim() ? "" : "pointer-events-none opacity-60"}`}
              >
                Check this card
                <ArrowRight aria-hidden className="size-4" />
              </Link>
            </div>
          </section>
          <p className="text-sm text-mute">
            General guidance from your own numbers, not financial advice. Banks also set income and credit-score
            requirements: check those with the bank.
          </p>
        </section>
      )}
    </div>
  );
}
