"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import { FIELD, PRIMARY } from "@/components/case-tools";
import { LinkOut } from "@/components/link-out";
import { apiGet, problemMessage, type TermSnapshot, type TermsOut } from "@/lib/api";
import { formatDate } from "@/lib/vocab";

interface CardOption {
  id: string;
  name: string;
  report_id: string | null;
}

function Values({ snap }: { snap: TermSnapshot | null }) {
  if (!snap) return <span className="text-mute">Not in the documents Ritam read</span>;
  return (
    <span className="block space-y-1">
      {snap.values.slice(0, 4).map((v, i) => (
        <span key={i} className="block">
          {v.value}
        </span>
      ))}
      {snap.values.length > 4 && <span className="block text-sm text-mute">+{snap.values.length - 4} more</span>}
    </span>
  );
}

/** A card's terms on the day you got it next to today's, from the bank's own documents. */
export function CardChanges({ initialCard = "", initialSince = "" }: { initialCard?: string; initialSince?: string }) {
  const [cards, setCards] = useState<CardOption[]>([]);
  const [card, setCard] = useState(initialCard);
  const [since, setSince] = useState(initialSince);
  const [out, setOut] = useState<TermsOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<CardOption[]>("/api/cards")
      .then(setCards)
      .catch((err) => setError(problemMessage(err)));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!card || !since) {
      setError("Choose the card and the date you got it.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setOut(await apiGet<TermsOut>(`/api/cards/${encodeURIComponent(card)}/terms?since=${since}`));
    } catch (err) {
      setError(problemMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const changed = out?.terms.filter((t) => t.changed) ?? [];
  const same = out?.terms.filter((t) => !t.changed) ?? [];
  const chosen = cards.find((c) => c.id === card);

  return (
    <div className="space-y-8">
      <form onSubmit={submit} noValidate className="space-y-5 rounded-lg border border-rule bg-surface p-5 sm:p-6">
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="changes-card" className="block text-[0.9375rem] font-semibold text-ink">
              Your card
            </label>
            <select
              id="changes-card"
              value={card}
              onChange={(e) => setCard(e.target.value)}
              className={`${FIELD} mt-2`}
            >
              <option value="">Choose a card</option>
              {cards.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="changes-since" className="block text-[0.9375rem] font-semibold text-ink">
              When did you get it?
            </label>
            <input
              id="changes-since"
              type="date"
              max={new Date().toISOString().slice(0, 10)}
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className={`${FIELD} mt-2`}
            />
          </div>
        </div>
        <button type="submit" disabled={busy} className={PRIMARY}>
          {busy && <Loader2 aria-hidden className="size-4 animate-spin" />}
          Show what changed
        </button>
      </form>

      {error && (
        <p role="alert" className="rounded-lg border border-uncertain/60 bg-surface p-4 text-ink">
          {error}
        </p>
      )}

      {out && (
        <section aria-labelledby="changes-result" className="space-y-6">
          <h2 id="changes-result" className="font-display text-2xl font-bold text-ink">
            {changed.length
              ? `${changed.length} ${changed.length === 1 ? "term looks" : "terms look"} different since ${formatDate(out.since)}`
              : `No change Ritam can see since ${formatDate(out.since)}`}
          </h2>
          {out.coverage.values === 0 ? (
            <p className="text-[0.9375rem] text-ink/85">
              Ritam hasn&apos;t read this card&apos;s documents yet.{" "}
              <LinkOut href="/#start">Get a report on it first</LinkOut>, then come back.
            </p>
          ) : (
            <div tabIndex={0} role="region" aria-label="Terms then and now" className="overflow-x-auto rounded-lg border border-rule">
              <table className="w-full min-w-[34rem] text-left text-[0.9375rem]">
                <caption className="sr-only">Terms then and now</caption>
                <thead className="text-sm text-mute">
                  <tr>
                    <th scope="col" className="px-4 py-2 font-medium">Term</th>
                    <th scope="col" className="px-4 py-2 font-medium">When you got it</th>
                    <th scope="col" className="px-4 py-2 font-medium">Now</th>
                  </tr>
                </thead>
                <tbody>
                  {[...changed, ...same].map((t) => (
                    <tr key={t.attribute} className="border-t border-rule align-top text-ink">
                      <th scope="row" className="px-4 py-3 font-medium">
                        {t.label}
                        {t.changed === true && <span className="mt-1 block text-sm text-uncertain">Changed</span>}
                        {t.changed === "maybe" && (
                          <span className="mt-1 block text-sm text-uncertain">Worded differently: check the quotes</span>
                        )}
                      </th>
                      <td className="px-4 py-3">
                        <Values snap={t.then} />
                      </td>
                      <td className="px-4 py-3">
                        <Values snap={t.now} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-sm text-mute">
            {out.coverage.note}
            {chosen?.report_id && (
              <>
                {" "}
                <LinkOut href={`/audit/${chosen.report_id}`}>See the full report with every quote</LinkOut>.
              </>
            )}
          </p>
        </section>
      )}
    </div>
  );
}
